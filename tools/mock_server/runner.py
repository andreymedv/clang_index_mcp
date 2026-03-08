#!/usr/bin/env python3
"""LLM test runner with tool-call mediation loop.

Loads test scenarios from YAML, runs each through an LLM via OpenAI-compat
API (LM Studio /v1/chat/completions), mediates the tool call loop using
canned fixture responses, and evaluates correctness.

Usage:
    python tools/mock_server/runner.py --scenarios scenarios/basic.yaml
    python tools/mock_server/runner.py --scenarios scenarios/basic.yaml --model qwen3-4b
    python tools/mock_server/runner.py --dry-run
"""

import argparse
import json
import os
import re
import signal
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Add project root to path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from mcp_server.consolidated_tools import list_tools_b  # noqa: E402
from tools.mock_server.fixtures import FixtureStore  # noqa: E402

DEFAULT_FIXTURES = Path(__file__).parent / "fixtures" / "responses.yaml"
DEFAULT_SCENARIOS = Path(__file__).parent / "scenarios" / "basic.yaml"


# ---------------------------------------------------------------------------
# MCP Tool → OpenAI function-calling format conversion
# ---------------------------------------------------------------------------


def mcp_tools_to_openai(tools: list) -> List[Dict[str, Any]]:
    """Convert MCP Tool objects to OpenAI function-calling format."""
    result = []
    for tool in tools:
        # Skip set_project and sync_project — mock server is "always indexed"
        if tool.name in ("set_project", "sync_project"):
            continue
        result.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema,
                },
            }
        )
    return result


# ---------------------------------------------------------------------------
# LM Studio OpenAI-compat client
# ---------------------------------------------------------------------------


@dataclass
class OpenAIClient:
    """Thin wrapper around OpenAI-compat /v1/chat/completions."""

    base_url: str = "http://localhost:1234"
    token: str = ""
    timeout: int = 300

    def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """Send a chat completion request with tool definitions."""
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        body = json.dumps(payload).encode()
        url = f"{self.base_url}/v1/chat/completions"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode())  # type: ignore[no-any-return]

    def list_models(self) -> List[str]:
        """GET /v1/models — return list of model IDs."""
        url = f"{self.base_url}/v1/models"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        models = data.get("data", [])
        return [
            m["id"]
            for m in models
            if not m.get("id", "").startswith("text-embedding-")
        ]


# ---------------------------------------------------------------------------
# Scenario loading
# ---------------------------------------------------------------------------


def load_scenarios(path: str | Path) -> List[Dict[str, Any]]:
    """Load test scenarios from YAML."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("scenarios", [])


# ---------------------------------------------------------------------------
# Step evaluation
# ---------------------------------------------------------------------------


def evaluate_step(
    expected: Dict[str, Any],
    actual_tool: str,
    actual_args: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate a single step: compare actual tool call vs expected.

    Returns a step result dict with pass/fail details.
    """
    result: Dict[str, Any] = {
        "expected_tool": expected["tool"],
        "actual_tool": actual_tool,
        "tool_match": actual_tool == expected["tool"],
        "param_assertions": {},
        "params_pass": True,
    }

    expected_params = expected.get("params", {})
    for param_name, assertion in expected_params.items():
        actual_value = actual_args.get(param_name)
        param_result = _check_param(assertion, actual_value)
        result["param_assertions"][param_name] = param_result
        if not param_result["pass"]:
            result["params_pass"] = False

    return result


def _check_param(assertion: Dict[str, Any], actual: Any) -> Dict[str, Any]:
    """Check a single parameter assertion."""
    assert_type = assertion.get("type", "any")
    expected_val = assertion.get("value")

    if assert_type == "any":
        return {"expected": "any", "actual": actual, "pass": actual is not None}

    if assert_type == "absent":
        return {"expected": "absent", "actual": actual, "pass": actual is None}

    actual_str = str(actual) if actual is not None else ""

    if assert_type == "exact":
        match = actual_str.lower() == str(expected_val).lower()
        return {
            "expected": f"exact:{expected_val}",
            "actual": actual,
            "pass": match,
        }

    if assert_type == "contains":
        match = str(expected_val).lower() in actual_str.lower()
        return {
            "expected": f"contains:{expected_val}",
            "actual": actual,
            "pass": match,
        }

    if assert_type == "regex":
        match = bool(re.search(str(expected_val), actual_str, re.IGNORECASE))
        return {
            "expected": f"regex:{expected_val}",
            "actual": actual,
            "pass": match,
        }

    if assert_type == "one_of":
        values = [str(v).lower() for v in expected_val]
        match = actual_str.lower() in values
        return {
            "expected": f"one_of:{expected_val}",
            "actual": actual,
            "pass": match,
        }

    return {"expected": f"unknown:{assert_type}", "actual": actual, "pass": False}


# ---------------------------------------------------------------------------
# Tool-call mediation loop
# ---------------------------------------------------------------------------


def run_scenario(
    client: OpenAIClient,
    model: str,
    scenario: Dict[str, Any],
    openai_tools: List[Dict[str, Any]],
    store: FixtureStore,
    system_prompt: str,
    max_turns: int = 10,
    temperature: float = 0,
    max_tokens: int = 4096,
) -> Dict[str, Any]:
    """Run a single scenario through the LLM tool-call mediation loop.

    Returns a result dict with step-by-step evaluation.
    """
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": scenario["query"]},
    ]

    recorded_calls: List[Dict[str, Any]] = []
    start_time = time.time()
    error: Optional[str] = None
    final_answer = ""

    for turn in range(max_turns):
        try:
            response = client.chat_completion(
                model=model,
                messages=messages,
                tools=openai_tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            error = f"api_error: {e}"
            break
        except json.JSONDecodeError as e:
            error = f"json_error: {e}"
            break

        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "")

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            # LLM responded with text — conversation done
            final_answer = message.get("content", "") or ""
            break

        # Append assistant message with tool calls
        messages.append(message)

        # Process each tool call
        for tc in tool_calls:
            func = tc.get("function", {})
            tool_name = func.get("name", "")
            try:
                tool_args = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                tool_args = {}

            recorded_calls.append(
                {"tool": tool_name, "arguments": tool_args}
            )

            # Get canned response
            canned = store.match(tool_name, tool_args)
            canned_str = json.dumps(canned, indent=2)

            # Append tool result
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": canned_str,
                }
            )

        if finish_reason == "length":
            error = "max_tokens_exceeded"
            break
    else:
        error = "max_turns_exceeded"

    wall_time = time.time() - start_time

    # Evaluate steps
    expected_steps = scenario.get("expected_steps", [])
    step_results = []
    for i, expected_step in enumerate(expected_steps):
        if i < len(recorded_calls):
            step_result = evaluate_step(
                expected_step,
                recorded_calls[i]["tool"],
                recorded_calls[i]["arguments"],
            )
            step_result["step"] = i + 1
            step_results.append(step_result)
        else:
            step_results.append(
                {
                    "step": i + 1,
                    "expected_tool": expected_step["tool"],
                    "actual_tool": None,
                    "tool_match": False,
                    "param_assertions": {},
                    "params_pass": False,
                    "missing": True,
                }
            )

    # Overall pass: all expected steps matched
    overall_pass = (
        len(step_results) > 0
        and all(s["tool_match"] and s["params_pass"] for s in step_results)
        and error is None
    )

    return {
        "scenario_id": scenario["id"],
        "category": scenario.get("category", ""),
        "query": scenario["query"],
        "steps": step_results,
        "overall_pass": overall_pass,
        "total_tool_calls": len(recorded_calls),
        "all_tool_calls": recorded_calls,
        "final_answer": final_answer[:500],
        "wall_time_seconds": round(wall_time, 2),
        "error": error,
    }


# ---------------------------------------------------------------------------
# Results export
# ---------------------------------------------------------------------------


def export_results(
    results: List[Dict[str, Any]],
    model: str,
    output_path: str,
    scenarios_file: str,
    fixtures_file: str,
) -> None:
    """Export results as structured JSON."""
    passed = sum(1 for r in results if r["overall_pass"])
    total = len(results)

    report = {
        "run_id": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model,
        "scenarios_file": scenarios_file,
        "fixtures_file": fixtures_file,
        "results": results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 3) if total > 0 else 0,
        },
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Default system prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a C++ code analysis assistant. You have access to tools that can \
search and analyze an indexed C++ codebase.

The project is already indexed. Do NOT call set_project or sync_project. \
Go directly to answering the question using the available tools.

Use the available tools to answer the user's question. Be precise with tool \
arguments -- use class/function names, not signatures. For regex patterns, \
remember that patterns are anchored (matched against full name).

When you find what you need, provide a concise answer summarizing the results.\
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@dataclass
class RunnerState:
    """Mutable state for graceful interrupt handling."""

    interrupted: bool = False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM test runner for MCP tool description optimization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --scenarios scenarios/basic.yaml\n"
            "  %(prog)s --scenarios scenarios/basic.yaml --model qwen3-4b\n"
            "  %(prog)s --dry-run\n"
            "  %(prog)s --list-models\n"
        ),
    )
    parser.add_argument(
        "--scenarios",
        type=str,
        default=str(DEFAULT_SCENARIOS),
        help=f"Scenarios YAML file (default: {DEFAULT_SCENARIOS})",
    )
    parser.add_argument(
        "--fixtures",
        type=str,
        default=str(DEFAULT_FIXTURES),
        help=f"Fixtures YAML file (default: {DEFAULT_FIXTURES})",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model ID (substring match). Default: first loaded model.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="mock_test_results.json",
        help="Output JSON file (default: mock_test_results.json)",
    )
    parser.add_argument(
        "--lm-url",
        default=os.environ.get("LM_STUDIO_URL", "http://localhost:1234"),
        help="LM Studio base URL",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("LM_STUDIO_TOKEN", ""),
        help="LM Studio auth token",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0,
        help="Temperature (default: 0)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4096,
        help="Max output tokens per turn (default: 4096)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Request timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--scenario-id",
        action="append",
        dest="scenario_ids",
        help="Run only this scenario (repeat for multiple).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show scenarios without running",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List available models from LM Studio",
    )
    args = parser.parse_args()

    client = OpenAIClient(
        base_url=args.lm_url,
        token=args.token,
        timeout=args.timeout,
    )

    # --list-models
    if args.list_models:
        try:
            models = client.list_models()
        except urllib.error.URLError as e:
            print(f"Error connecting to LM Studio: {e}")
            sys.exit(1)
        print(f"Available models ({len(models)}):")
        for m in models:
            print(f"  - {m}")
        return

    # Load scenarios
    scenarios = load_scenarios(args.scenarios)
    if args.scenario_ids:
        ids = set(args.scenario_ids)
        scenarios = [s for s in scenarios if s["id"] in ids]

    if not scenarios:
        print("No scenarios to run.")
        sys.exit(1)

    # --dry-run
    if args.dry_run:
        print(f"Scenarios ({len(scenarios)}):")
        for s in scenarios:
            print(f"  [{s['id']}] ({s.get('category', '')}) {s['query'][:70]}")
        return

    # Resolve model
    try:
        available_models = client.list_models()
    except urllib.error.URLError as e:
        print(f"Error connecting to LM Studio: {e}")
        sys.exit(1)

    if not available_models:
        print("No models loaded in LM Studio.")
        sys.exit(1)

    if args.model:
        matches = [m for m in available_models if args.model in m]
        if not matches:
            print(f"No model matching '{args.model}'. Available: {available_models}")
            sys.exit(1)
        model = matches[0]
    else:
        model = available_models[0]

    # Load fixtures and tools
    store = FixtureStore().load(args.fixtures)
    openai_tools = mcp_tools_to_openai(list_tools_b())

    # Interrupt handler
    state = RunnerState()

    def handle_interrupt(signum: int, frame: Any) -> None:
        if state.interrupted:
            print("\nForced exit.")
            sys.exit(1)
        print("\nInterrupted — finishing current scenario...")
        state.interrupted = True

    signal.signal(signal.SIGINT, handle_interrupt)

    # Run
    print(f"Model: {model}")
    print(f"Scenarios: {len(scenarios)} from {args.scenarios}")
    print(f"Fixtures: {args.fixtures}")
    print(f"Output: {args.output}")
    print()

    results: List[Dict[str, Any]] = []
    for i, scenario in enumerate(scenarios):
        if state.interrupted:
            break

        print(f"[{i + 1}/{len(scenarios)}] {scenario['id']}: {scenario['query'][:60]}...")

        result = run_scenario(
            client=client,
            model=model,
            scenario=scenario,
            openai_tools=openai_tools,
            store=store,
            system_prompt=SYSTEM_PROMPT,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        results.append(result)

        status = "PASS" if result["overall_pass"] else "FAIL"
        tools_used = [tc["tool"] for tc in result["all_tool_calls"]]
        print(f"  {status} | Tools: {tools_used} | {result['wall_time_seconds']}s")
        if result["error"]:
            print(f"  ERROR: {result['error']}")

    # Export
    export_results(
        results=results,
        model=model,
        output_path=args.output,
        scenarios_file=args.scenarios,
        fixtures_file=args.fixtures,
    )

    # Summary
    passed = sum(1 for r in results if r["overall_pass"])
    total = len(results)
    print(f"\n{'=' * 50}")
    print(f"Results: {passed}/{total} passed ({passed / total * 100:.0f}%)")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
