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

DEFAULT_FIXTURES_DIR = Path(__file__).parent / "fixtures"
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
        return [m["id"] for m in models if not m.get("id", "").startswith("text-embedding-")]


# ---------------------------------------------------------------------------
# Scenario loading
# ---------------------------------------------------------------------------


def load_scenarios(path: str | Path) -> List[Dict[str, Any]]:
    """Load test scenarios from YAML.

    Supports both single-query and multi-query scenarios:
      - query: "single query"        → 1 scenario
      - queries: ["q1", "q2", "q3"]  → 3 scenarios (same expected_steps)

    Multi-query scenarios are expanded into separate entries with
    scenario_id suffixed by /1, /2, etc. and a query_variant index.
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    raw = data.get("scenarios", [])
    expanded: List[Dict[str, Any]] = []

    for scenario in raw:
        queries = scenario.get("queries")
        if queries and isinstance(queries, list):
            for idx, q in enumerate(queries):
                variant = dict(scenario)
                variant["query"] = q
                variant["query_variant"] = idx + 1
                variant["query_variant_total"] = len(queries)
                variant["base_id"] = scenario["id"]
                variant["id"] = f"{scenario['id']}/{idx + 1}"
                variant.pop("queries", None)
                expanded.append(variant)
        else:
            scenario.setdefault("query_variant", 0)
            scenario.setdefault("query_variant_total", 1)
            scenario.setdefault("base_id", scenario["id"])
            expanded.append(scenario)

    return expanded


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
# Failure explanation
# ---------------------------------------------------------------------------


def _build_explanation_prompt(
    step_eval: Dict[str, Any],
    recorded_call: Optional[Dict[str, Any]],
) -> str:
    """Build a targeted question asking the LLM to explain its tool choice.

    Generates different questions based on failure type:
    - No tool call at all
    - Wrong tool selected
    - Right tool, wrong parameters (per-param detail)
    """
    # Case 1: LLM didn't call any tool
    if recorded_call is None:
        expected = step_eval["expected_tool"]
        return (
            "You did not call any tool. The expected action was to call "
            f"'{expected}'. Explain why you chose not to use any tool. "
            "What in the tool descriptions made you decide against calling one?"
        )

    actual_tool = recorded_call["tool"]
    actual_args = recorded_call["arguments"]
    expected_tool = step_eval["expected_tool"]

    # Case 2: Wrong tool
    if not step_eval["tool_match"]:
        return (
            f"You called '{actual_tool}' but the expected tool was "
            f"'{expected_tool}'. Explain your reasoning: what in the "
            f"description of '{actual_tool}' made it seem like the right "
            f"choice? What about '{expected_tool}' made you not choose it?"
        )

    # Case 3: Right tool, wrong parameters
    issues: List[str] = []
    for param_name, assertion in step_eval.get("param_assertions", {}).items():
        if assertion["pass"]:
            continue

        expected_desc = assertion["expected"]
        actual_val = assertion["actual"]

        if expected_desc == "absent":
            # LLM passed a parameter that shouldn't be there
            issues.append(
                f"- You passed parameter '{param_name}' = {actual_val!r}, "
                f"but this parameter was not expected. "
                f"Why did you include '{param_name}'?"
            )
        elif actual_val is None:
            # LLM omitted a required parameter
            issues.append(
                f"- You did not pass parameter '{param_name}' "
                f"(expected: {expected_desc}). "
                f"Why did you omit '{param_name}'?"
            )
        else:
            # LLM passed wrong value
            issues.append(
                f"- Parameter '{param_name}': you passed {actual_val!r} "
                f"but expected was {expected_desc}. "
                f"Why did you choose this value?"
            )

    if not issues:
        return (
            f"You called '{actual_tool}' with arguments {actual_args}. "
            "Explain why you chose these specific parameter values."
        )

    issues_text = "\n".join(issues)
    return (
        f"You called '{actual_tool}' (correct tool) but with "
        f"unexpected parameters:\n{issues_text}\n\n"
        "Analyze the tool description and your reasoning. "
        "What led you to these parameter choices?"
    )


def _request_explanation(
    client: OpenAIClient,
    model: str,
    messages: List[Dict[str, Any]],
    explanation_prompt: str,
    temperature: float = 0,
    max_tokens: int = 2048,
) -> Optional[str]:
    """Ask the LLM to explain its tool choice. Returns explanation text."""
    explain_messages = list(messages)
    explain_messages.append({"role": "user", "content": explanation_prompt})

    try:
        response = client.chat_completion(
            model=model,
            messages=explain_messages,
            tools=[],  # No tools — force text response
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choice = response.get("choices", [{}])[0]
        return choice.get("message", {}).get("content", "")
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


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
    explain_failures: bool = False,
    verbose_messages: bool = False,
) -> Dict[str, Any]:
    """Run a single scenario through the LLM tool-call mediation loop.

    Args:
        explain_failures: If True, on first mismatch stop the scenario and
            ask the LLM to explain its reasoning. The explanation is included
            in the result under step_results[i]["llm_explanation"].

    Returns a result dict with step-by-step evaluation.
    """
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": scenario["query"]},
    ]

    expected_steps = scenario.get("expected_steps", [])
    recorded_calls: List[Dict[str, Any]] = []
    step_results: List[Dict[str, Any]] = []
    start_time = time.time()
    error: Optional[str] = None
    final_answer = ""
    stopped_for_explanation = False

    for turn in range(max_turns):
        if verbose_messages:
            print(f"\n--- Turn {turn + 1}: messages sent to LLM ---")
            print(json.dumps(messages, indent=2, ensure_ascii=False))
            print("--- end messages ---\n")
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

            # Check if LLM should have called a tool but didn't
            if explain_failures and len(recorded_calls) < len(expected_steps):
                step_idx = len(recorded_calls)
                step_eval = {
                    "step": step_idx + 1,
                    "expected_tool": expected_steps[step_idx]["tool"],
                    "actual_tool": None,
                    "tool_match": False,
                    "param_assertions": {},
                    "params_pass": False,
                    "missing": True,
                }
                prompt = _build_explanation_prompt(step_eval, None)
                explanation = _request_explanation(
                    client,
                    model,
                    messages,
                    prompt,
                    temperature=temperature,
                    max_tokens=2048,
                )
                step_eval["llm_explanation"] = explanation
                step_results.append(step_eval)
                stopped_for_explanation = True
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

            call_record = {"tool": tool_name, "arguments": tool_args}
            recorded_calls.append(call_record)

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

            # Inline evaluation for explain_failures mode
            step_idx = len(recorded_calls) - 1
            if explain_failures and step_idx < len(expected_steps):
                step_eval = evaluate_step(
                    expected_steps[step_idx],
                    tool_name,
                    tool_args,
                )
                step_eval["step"] = step_idx + 1
                if not step_eval["tool_match"] or not step_eval["params_pass"]:
                    prompt = _build_explanation_prompt(step_eval, call_record)
                    explanation = _request_explanation(
                        client,
                        model,
                        messages,
                        prompt,
                        temperature=temperature,
                        max_tokens=2048,
                    )
                    step_eval["llm_explanation"] = explanation
                    step_results.append(step_eval)
                    stopped_for_explanation = True
                    break
                step_results.append(step_eval)

        if stopped_for_explanation:
            break

        if finish_reason == "length":
            error = "max_tokens_exceeded"
            break
    else:
        error = "max_turns_exceeded"

    wall_time = time.time() - start_time

    # Post-hoc evaluation (only for steps not already evaluated inline)
    if not explain_failures:
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
    else:
        # In explain mode, add remaining missing steps (not yet evaluated)
        evaluated_count = len(step_results)
        for i in range(evaluated_count, len(expected_steps)):
            if not stopped_for_explanation:
                if i < len(recorded_calls):
                    step_result = evaluate_step(
                        expected_steps[i],
                        recorded_calls[i]["tool"],
                        recorded_calls[i]["arguments"],
                    )
                    step_result["step"] = i + 1
                    step_results.append(step_result)
                else:
                    step_results.append(
                        {
                            "step": i + 1,
                            "expected_tool": expected_steps[i]["tool"],
                            "actual_tool": None,
                            "tool_match": False,
                            "param_assertions": {},
                            "params_pass": False,
                            "missing": True,
                            "skipped": True,
                        }
                    )

    # Overall pass: all expected steps matched
    overall_pass = (
        len(step_results) > 0
        and all(s["tool_match"] and s["params_pass"] for s in step_results)
        and error is None
    )

    result: Dict[str, Any] = {
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

    # Include query variant metadata if present
    if scenario.get("query_variant"):
        result["base_scenario_id"] = scenario.get("base_id", scenario["id"])
        result["query_variant"] = scenario["query_variant"]
        result["query_variant_total"] = scenario.get("query_variant_total", 1)

    return result


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

# Short addition for --validate-intent mode.
# Intentionally brief to avoid distracting small models from the main task.
VALIDATE_INTENT_ADDITION = (
    "\n\nBefore using any tool: if the request does not contain a specific C++ symbol name "
    "(a class name, function name, or filename), reply with a clarification question "
    "asking which specific class or function to look up. Do not guess or search broadly."
)


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
        default=str(DEFAULT_FIXTURES_DIR),
        help="Fixtures YAML file or directory (default: fixtures/)",
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
    parser.add_argument(
        "--explain-failures",
        action="store_true",
        help=(
            "On first mismatch, stop the scenario and ask the LLM "
            "to explain its reasoning. Adds 'llm_explanation' field "
            "to failed steps in the output."
        ),
    )
    parser.add_argument(
        "--verbose-messages",
        action="store_true",
        help=(
            "Print the exact messages array sent to the LLM before each API call. "
            "Useful for debugging context presentation issues (e.g. call_chain step-2 failures)."
        ),
    )
    parser.add_argument(
        "--validate-intent",
        action="store_true",
        help=(
            "Append a short instruction telling the model to ask for clarification "
            "when the request lacks a specific symbol name. "
            "Scenarios where the model asks for clarification instead of searching "
            "are marked as 'clarification_requested' (not PASS, not FAIL)."
        ),
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
            variant_tag = ""
            if s.get("query_variant"):
                variant_tag = f" [variant {s['query_variant']}/{s['query_variant_total']}]"
            print(f"  [{s['id']}] ({s.get('category', '')}){variant_tag} " f"{s['query'][:70]}")
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
    store = FixtureStore()
    fixtures_path = Path(args.fixtures)
    if fixtures_path.is_dir():
        fixture_files = sorted(fixtures_path.glob("*.yaml"))
        for ff in fixture_files:
            store.load(ff)
        fixtures_label = f"{len(fixture_files)} files from {args.fixtures}"
    else:
        store.load(args.fixtures)
        fixtures_label = args.fixtures
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
    print(f"Fixtures: {fixtures_label}")
    print(f"Output: {args.output}")
    if args.explain_failures:
        print("Explain failures: ON")
    if args.verbose_messages:
        print("Verbose messages: ON (printing messages array each turn)")
    if args.validate_intent:
        print("Validate intent: ON (model asked to clarify vague requests)")
    print()

    system_prompt = SYSTEM_PROMPT
    if args.validate_intent:
        system_prompt = SYSTEM_PROMPT + VALIDATE_INTENT_ADDITION

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
            system_prompt=system_prompt,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            explain_failures=args.explain_failures,
            verbose_messages=args.verbose_messages,
        )
        results.append(result)

        # Detect clarification_requested: no tool calls, model responded with text
        clarification = (
            args.validate_intent
            and not result["all_tool_calls"]
            and not result["overall_pass"]
            and result.get("final_answer", "").strip()
        )
        if clarification:
            result["clarification_requested"] = True

        if clarification:
            status = "CLAR"
        elif result["overall_pass"]:
            status = "PASS"
        else:
            status = "FAIL"
        tools_used = [tc["tool"] for tc in result["all_tool_calls"]]
        print(f"  {status} | Tools: {tools_used} | {result['wall_time_seconds']}s")
        if clarification:
            answer_preview = result.get("final_answer", "")[:120].replace("\n", " ")
            print(f"  CLARIFY: {answer_preview}")
        if result["error"]:
            print(f"  ERROR: {result['error']}")
        if args.explain_failures and not result["overall_pass"]:
            for step in result["steps"]:
                explanation = step.get("llm_explanation")
                if explanation:
                    # Show first 200 chars of explanation in console
                    short = explanation[:200].replace("\n", " ")
                    if len(explanation) > 200:
                        short += "..."
                    print(f"  EXPLAIN: {short}")

    # Export
    export_results(
        results=results,
        model=model,
        output_path=args.output,
        scenarios_file=args.scenarios,
        fixtures_file=fixtures_label,
    )

    # Summary
    passed = sum(1 for r in results if r["overall_pass"])
    clarified = sum(1 for r in results if r.get("clarification_requested"))
    total = len(results)
    print(f"\n{'=' * 50}")
    if clarified:
        print(f"Results: {passed}/{total} passed ({passed / total * 100:.0f}%), "
              f"{clarified} clarification requested")
    else:
        print(f"Results: {passed}/{total} passed ({passed / total * 100:.0f}%)")

    # Per-base-scenario variant summary (only if multi-query scenarios exist)
    has_variants = any(r.get("query_variant") for r in results)
    if has_variants:
        from collections import OrderedDict

        base_groups: Dict[str, List[Dict[str, Any]]] = OrderedDict()
        for r in results:
            base_id = r.get("base_scenario_id", r["scenario_id"])
            base_groups.setdefault(base_id, []).append(r)

        print("\nPer-scenario robustness:")
        for base_id, group in base_groups.items():
            if len(group) <= 1:
                continue
            group_passed = sum(1 for r in group if r["overall_pass"])
            group_total = len(group)
            pct = group_passed / group_total * 100
            bar = "+" * group_passed + "-" * (group_total - group_passed)
            print(f"  {base_id}: {group_passed}/{group_total} ({pct:.0f}%) [{bar}]")
            for r in group:
                if not r["overall_pass"]:
                    print(f"    FAIL: {r['query'][:70]}")

    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
