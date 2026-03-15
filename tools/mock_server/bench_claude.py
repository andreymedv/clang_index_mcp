#!/usr/bin/env python3
"""
Benchmark Claude models (via claude CLI -p) on tool selection scenarios.

Usage:
    python tools/mock_server/bench_claude.py [--scenario SCENARIO_ID] [--model MODEL]
    python tools/mock_server/bench_claude.py --scenario PROBE-RC3-01
    python tools/mock_server/bench_claude.py --scenarios-file scenarios/probes_rootcauses.yaml

The script presents tool schemas as text and asks the model to select the right tool.
No actual tool calling — the model responds with structured JSON.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from mcp_server.consolidated_tools import list_tools_b  # noqa: E402

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
You are a C++ code analysis assistant. A C++ project is already indexed and ready to query.
The user will ask questions about the C++ codebase (classes, functions, call graphs, etc.).
Select the appropriate analysis tool and arguments to answer the question.

Do NOT use set_project or sync_project — the project is already set up.

Respond ONLY with a JSON object in this exact format (no markdown, no explanation):
{
  "tool": "<tool_name>",
  "arguments": {
    "<param>": "<value>"
  }
}

If no tool is needed, respond with: {"tool": null, "arguments": {}}
"""


def build_tools_text(tools):
    lines = ["=== AVAILABLE TOOLS ===\n"]
    for t in tools:
        lines.append(f"Tool: {t.name}")
        lines.append(f"Description: {t.description}")
        props = t.inputSchema.get("properties", {})
        required = t.inputSchema.get("required", [])
        if props:
            lines.append("Parameters:")
            for name, schema in props.items():
                req = " (required)" if name in required else " (optional)"
                desc = schema.get("description", "")
                enum = schema.get("enum", [])
                enum_str = f" Options: {enum}" if enum else ""
                lines.append(f"  - {name}{req}: {desc}{enum_str}")
        lines.append("")
    return "\n".join(lines)


def ask_claude(prompt, model):
    result = subprocess.run(
        ["claude", "-p", "--model", model],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI error: {result.stderr}")
    return result.stdout.strip()


def parse_response(raw):
    """Extract JSON from model response."""
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def check_assertion(assertion, actual_value):
    """Check a single param assertion against actual value."""
    if actual_value is None:
        return False
    expected_raw = assertion.get("value", "")
    match_type = assertion.get("type", "contains")
    actual_str = str(actual_value).lower()
    expected_str = str(expected_raw).lower()

    if match_type == "exact":
        return actual_str == expected_str
    elif match_type == "contains":
        return expected_str in actual_str
    elif match_type == "not_empty":
        return bool(actual_value)
    return False


def evaluate_scenario(scenario, tools_text, model, verbose=False):
    query = scenario["query"]
    expected_steps = scenario.get("expected_steps", [])

    if not expected_steps:
        return {"scenario_id": scenario["id"], "skip": True}

    # We only test the first step (tool selection decision)
    step = expected_steps[0]
    expected_tool = step["tool"]
    param_assertions = step.get("params", {})

    prompt = f"{SYSTEM_PROMPT}\n{tools_text}\n=== USER QUERY ===\n{query}"

    raw = ask_claude(prompt, model)
    parsed = parse_response(raw)

    if verbose:
        print(f"  Raw response: {raw[:200]}")

    if parsed is None:
        return {
            "scenario_id": scenario["id"],
            "query": query,
            "expected_tool": expected_tool,
            "actual_tool": None,
            "tool_match": False,
            "params_pass": False,
            "overall_pass": False,
            "error": f"JSON parse failed: {raw[:100]}",
        }

    actual_tool = parsed.get("tool")
    actual_args = parsed.get("arguments", {})
    tool_match = actual_tool == expected_tool

    param_results = {}
    params_pass = True
    for param_name, assertion in param_assertions.items():
        actual_val = actual_args.get(param_name)
        ok = check_assertion(assertion, actual_val)
        param_results[param_name] = {
            "expected": f"{assertion['type']}:{assertion['value']}",
            "actual": actual_val,
            "pass": ok,
        }
        if not ok:
            params_pass = False

    overall_pass = tool_match and params_pass

    return {
        "scenario_id": scenario["id"],
        "query": query,
        "expected_tool": expected_tool,
        "actual_tool": actual_tool,
        "actual_args": actual_args,
        "tool_match": tool_match,
        "param_results": param_results,
        "params_pass": params_pass,
        "overall_pass": overall_pass,
    }


def load_scenarios(path, scenario_id=None):
    with open(path) as f:
        data = yaml.safe_load(f)
    scenarios = data.get("scenarios", [])
    if scenario_id:
        scenarios = [s for s in scenarios if s["id"] == scenario_id]
    return scenarios


def print_result(r, verbose=False):
    if r.get("skip"):
        print(f"  [{r['scenario_id']}] SKIP (no steps defined)")
        return

    status = "PASS" if r["overall_pass"] else "FAIL"
    icon = "✅" if r["overall_pass"] else "❌"
    print(f"  {icon} {r['scenario_id']}: {status}")
    print(f"     Query: {r['query'][:70]}")
    print(f"     Tool:  expected={r['expected_tool']}  actual={r['actual_tool']}")

    if not r["tool_match"]:
        print(f"     ❌ Wrong tool")

    for param, pr in r.get("param_results", {}).items():
        icon2 = "✅" if pr["pass"] else "❌"
        print(f"     {icon2} {param}: expected={pr['expected']}  actual={pr['actual']}")

    if r.get("error"):
        print(f"     Error: {r['error']}")

    if verbose and r.get("actual_args"):
        print(f"     Full args: {json.dumps(r['actual_args'])}")


def main():
    parser = argparse.ArgumentParser(description="Benchmark Claude models on tool selection")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Claude model ID")
    parser.add_argument("--scenario", help="Run single scenario by ID")
    parser.add_argument(
        "--scenarios-file",
        default="tools/mock_server/scenarios/probes_rootcauses.yaml",
        help="Path to scenarios YAML file",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    tools = list_tools_b()
    tools_text = build_tools_text(tools)

    scenarios_path = Path(args.scenarios_file)
    if not scenarios_path.is_absolute():
        scenarios_path = Path(__file__).parent.parent.parent / scenarios_path

    scenarios = load_scenarios(scenarios_path, args.scenario)

    if not scenarios:
        print(f"No scenarios found (id={args.scenario})")
        sys.exit(1)

    print(f"Model: {args.model}")
    print(f"Scenarios: {scenarios_path.name}  ({len(scenarios)} to run)\n")

    results = []
    for s in scenarios:
        print(f"Running {s['id']}...")
        r = evaluate_scenario(s, tools_text, args.model, verbose=args.verbose)
        print_result(r, verbose=args.verbose)
        results.append(r)
        print()

    passed = sum(1 for r in results if r.get("overall_pass"))
    total = sum(1 for r in results if not r.get("skip"))
    print(f"Results: {passed}/{total} passed ({100*passed/total:.0f}%)" if total else "No results")


if __name__ == "__main__":
    main()
