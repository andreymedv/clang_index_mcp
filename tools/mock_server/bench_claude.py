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
    # Support both single `query` and multi-query `queries` formats
    if "queries" in scenario:
        query = scenario["queries"][0]  # use first query
    else:
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


ALL_SCENARIO_FILES = [
    "basic",
    "edge_cases",
    "multi_step",
    "probes_rootcauses",
    "probes_usage_ambiguity",
    "real_workflows",
]


def resolve_scenarios_path(name_or_path):
    p = Path(name_or_path)
    if p.is_absolute():
        return p
    # Try as bare name (e.g. "basic" → scenarios/basic.yaml)
    root = Path(__file__).parent.parent.parent
    candidate = root / "tools" / "mock_server" / "scenarios" / f"{name_or_path}.yaml"
    if candidate.exists():
        return candidate
    return root / name_or_path


def main():
    parser = argparse.ArgumentParser(description="Benchmark Claude models on tool selection")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Claude model ID")
    parser.add_argument("--scenario", help="Run single scenario by ID")
    parser.add_argument(
        "--scenarios-file",
        help="Path or bare name of a scenarios YAML file (default: run all)",
    )
    parser.add_argument(
        "--all", action="store_true", help="Run all scenario files and save combined report"
    )
    parser.add_argument("--output", help="Save JSON results to this file")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    tools = list_tools_b()
    tools_text = build_tools_text(tools)

    # Decide which files to run
    if args.all or (not args.scenarios_file and not args.scenario):
        files_to_run = ALL_SCENARIO_FILES
    else:
        files_to_run = [args.scenarios_file or "probes_rootcauses"]

    import datetime
    run_ts = datetime.datetime.now().isoformat(timespec="seconds")

    print(f"Model: {args.model}")
    print(f"Run:   {run_ts}")
    print(f"Files: {', '.join(files_to_run)}\n")

    all_results = []
    per_file_stats = []

    for fname in files_to_run:
        spath = resolve_scenarios_path(fname)
        if not spath.exists():
            print(f"  [SKIP] {fname} — file not found: {spath}")
            continue

        scenarios = load_scenarios(spath, args.scenario)
        if not scenarios:
            continue

        print(f"=== {spath.name} ({len(scenarios)} scenarios) ===")
        file_results = []
        for s in scenarios:
            print(f"Running {s['id']}...", end=" ", flush=True)
            r = evaluate_scenario(s, tools_text, args.model, verbose=args.verbose)
            r["scenarios_file"] = spath.name
            status = "PASS" if r.get("overall_pass") else ("SKIP" if r.get("skip") else "FAIL")
            print(status)
            if not r.get("overall_pass") and not r.get("skip"):
                print_result(r, verbose=args.verbose)
                print()
            file_results.append(r)

        passed = sum(1 for r in file_results if r.get("overall_pass"))
        total = sum(1 for r in file_results if not r.get("skip"))
        rate = 100 * passed / total if total else 0
        print(f"  → {passed}/{total} ({rate:.0f}%)\n")
        per_file_stats.append({"file": spath.name, "passed": passed, "total": total, "rate": rate})
        all_results.extend(file_results)

    # Overall summary
    total_passed = sum(s["passed"] for s in per_file_stats)
    total_total = sum(s["total"] for s in per_file_stats)
    overall_rate = 100 * total_passed / total_total if total_total else 0

    print("=" * 50)
    print(f"TOTAL: {total_passed}/{total_total} ({overall_rate:.1f}%)")
    print(f"Model: {args.model}")

    # Save JSON report
    output_path = args.output
    if not output_path and (args.all or (not args.scenarios_file and not args.scenario)):
        # Auto-save when running all files
        out_dir = Path(__file__).parent / "optimization_runs" / "bench_claude"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_model = args.model.replace("/", "_").replace(":", "_")
        output_path = str(out_dir / f"{safe_model}.json")

    if output_path:
        report = {
            "run_id": run_ts,
            "model": args.model,
            "method": "claude-cli-text-simulation",
            "note": "Tool selection tested via text prompt (no actual tool calling). First query used for multi-query scenarios.",
            "summary": {
                "total_passed": total_passed,
                "total_total": total_total,
                "overall_rate": round(overall_rate, 1),
            },
            "per_file": per_file_stats,
            "failures": [
                {k: v for k, v in r.items() if k != "skip"}
                for r in all_results
                if not r.get("overall_pass") and not r.get("skip")
            ],
            "results": all_results,
        }
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
