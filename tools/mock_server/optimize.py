#!/usr/bin/env python3
"""Test runner + failure analyzer for tool description optimization.

Runs LLM test scenarios against a local model (LM Studio), analyzes failures,
and produces a compact summary report designed for Claude Code to read and act on.

The optimization loop is driven by Claude Code (ideally switched to Haiku model
for cost efficiency). Claude Code reads the compact report, understands the
failure patterns, and directly edits consolidated_tools.py. Then this script
re-runs tests to measure improvement.

Workflow (driven by Claude Code):
    1. Claude Code runs: python tools/mock_server/optimize.py run --model qwen3-4b
       → Produces compact failure report
    2. Claude Code reads the report, edits consolidated_tools.py
    3. Claude Code runs: python tools/mock_server/optimize.py run --model qwen3-4b
       → Verifies improvement
    4. Repeat until satisfied

Usage:
    # Run all scenarios and produce analysis report
    python tools/mock_server/optimize.py run --model qwen3-4b

    # Analyze existing results file (skip test run)
    python tools/mock_server/optimize.py analyze results.json

    # Compare two result files (before/after)
    python tools/mock_server/optimize.py compare before.json after.json

    # Apply a suggestions.json file (find-and-replace edits)
    python tools/mock_server/optimize.py apply suggestions.json [--dry-run]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONSOLIDATED_TOOLS_PATH = _PROJECT_ROOT / "mcp_server" / "consolidated_tools.py"
RUNNER_PATH = Path(__file__).parent / "runner.py"
DEFAULT_SCENARIOS_DIR = Path(__file__).parent / "scenarios"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "optimization_runs"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FailurePattern:
    """A pattern extracted from test failures."""

    scenario_id: str
    category: str
    query: str
    failure_type: str  # "wrong_tool", "wrong_param", "missing_call"
    expected_tool: str
    actual_tool: Optional[str]
    param_issues: List[Dict[str, Any]] = field(default_factory=list)
    llm_explanation: Optional[str] = None


@dataclass
class Suggestion:
    """A suggested edit to consolidated_tools.py."""

    tool_name: str
    field: str  # "description", "param_description"
    param_name: Optional[str]
    old_text: str
    new_text: str
    rationale: str


# ---------------------------------------------------------------------------
# Run tests
# ---------------------------------------------------------------------------


def run_tests(
    model: Optional[str],
    scenarios_dir: str,
    output_path: str,
    lm_url: str,
    token: str,
    explain_failures: bool = True,
    extra_args: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run test scenarios via runner.py and return parsed results."""
    scenario_files = sorted(Path(scenarios_dir).glob("*.yaml"))
    if not scenario_files:
        print(f"  No scenario files found in {scenarios_dir}")
        return {"summary": {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0}}

    all_results: List[Dict[str, Any]] = []

    for sf in scenario_files:
        cmd = [
            sys.executable,
            str(RUNNER_PATH),
            "--scenarios", str(sf),
            "--output", output_path,
            "--lm-url", lm_url,
            "--token", token,
        ]
        if model:
            cmd.extend(["--model", model])
        if explain_failures:
            cmd.append("--explain-failures")
        if extra_args:
            cmd.extend(extra_args)

        print(f"  Running: {sf.name}...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            print(f"    WARNING: runner.py returned {result.returncode}")
            if result.stderr:
                lines = result.stderr.strip().split("\n")
                for line in lines[-5:]:
                    print(f"    {line}")

        try:
            with open(output_path) as f:
                data = json.load(f)
            all_results.extend(data.get("results", []))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"    WARNING: Could not parse results: {e}")

    passed = sum(1 for r in all_results if r.get("overall_pass"))
    total = len(all_results)
    merged = {
        "results": all_results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 3) if total > 0 else 0,
        },
    }

    with open(output_path, "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    return merged


# ---------------------------------------------------------------------------
# Analyze failures
# ---------------------------------------------------------------------------


def extract_failure_patterns(report: Dict[str, Any]) -> List[FailurePattern]:
    """Extract structured failure patterns from test results."""
    patterns: List[FailurePattern] = []

    for result in report.get("results", []):
        if result.get("overall_pass"):
            continue

        for step in result.get("steps", []):
            if step.get("tool_match") and step.get("params_pass"):
                continue

            if step.get("missing"):
                failure_type = "missing_call"
            elif not step.get("tool_match"):
                failure_type = "wrong_tool"
            else:
                param_issues = []
                for pname, assertion in step.get("param_assertions", {}).items():
                    if not assertion.get("pass"):
                        actual = assertion.get("actual")
                        expected = assertion.get("expected", "")
                        if expected == "absent":
                            param_issues.append({
                                "param": pname,
                                "issue": "unexpected",
                                "actual": actual,
                                "expected": "absent",
                            })
                        elif actual is None:
                            param_issues.append({
                                "param": pname,
                                "issue": "missing",
                                "actual": None,
                                "expected": expected,
                            })
                        else:
                            param_issues.append({
                                "param": pname,
                                "issue": "wrong_value",
                                "actual": actual,
                                "expected": expected,
                            })
                failure_type = "wrong_param"

            pattern = FailurePattern(
                scenario_id=result.get("scenario_id", ""),
                category=result.get("category", ""),
                query=result.get("query", ""),
                failure_type=failure_type,
                expected_tool=step.get("expected_tool", ""),
                actual_tool=step.get("actual_tool"),
                param_issues=param_issues if failure_type == "wrong_param" else [],
                llm_explanation=step.get("llm_explanation"),
            )
            patterns.append(pattern)

    return patterns


def build_compact_report(report: Dict[str, Any]) -> str:
    """Build a compact failure report designed for Claude Code consumption.

    This report is intentionally concise (~500-1000 tokens) to minimize
    token usage when Claude Code reads it for analysis.
    """
    summary = report.get("summary", {})
    patterns = extract_failure_patterns(report)

    lines = [
        f"Pass rate: {summary.get('passed', 0)}/{summary.get('total', 0)} "
        f"({summary.get('pass_rate', 0) * 100:.1f}%)",
    ]

    if not patterns:
        lines.append("All scenarios passed. No failures to analyze.")
        return "\n".join(lines)

    # Group by failure type
    by_type: Dict[str, int] = {}
    for p in patterns:
        by_type[p.failure_type] = by_type.get(p.failure_type, 0) + 1

    type_summary = ", ".join(f"{ft}: {c}" for ft, c in sorted(by_type.items()))
    lines.append(f"Failures by type: {type_summary}")
    lines.append("")

    # Group by expected tool for actionable output
    by_tool: Dict[str, List[FailurePattern]] = {}
    for p in patterns:
        by_tool.setdefault(p.expected_tool, []).append(p)

    for tool, fps in sorted(by_tool.items()):
        lines.append(f"--- {tool} ({len(fps)} failures) ---")
        for fp in fps:
            lines.append(f"  [{fp.scenario_id}] {fp.failure_type}")
            lines.append(f"    Query: {fp.query[:80]}")
            if fp.failure_type == "wrong_tool":
                lines.append(f"    Got: {fp.actual_tool}")
            elif fp.failure_type == "wrong_param":
                for pi in fp.param_issues:
                    lines.append(
                        f"    Param '{pi['param']}': {pi['issue']} "
                        f"(got={pi['actual']}, expected={pi['expected']})"
                    )
            if fp.llm_explanation:
                # Truncate explanation to keep report compact
                short = fp.llm_explanation[:200].replace("\n", " ").strip()
                if len(fp.llm_explanation) > 200:
                    short += "..."
                lines.append(f"    LLM says: {short}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Compare results
# ---------------------------------------------------------------------------


def compare_results(
    before: Dict[str, Any],
    after: Dict[str, Any],
) -> str:
    """Generate a comparison report between before and after results."""
    b_summary = before.get("summary", {})
    a_summary = after.get("summary", {})

    b_rate = b_summary.get("pass_rate", 0)
    a_rate = a_summary.get("pass_rate", 0)
    delta = a_rate - b_rate

    lines = [
        "OPTIMIZATION RESULT",
        f"Before: {b_summary.get('passed', 0)}/{b_summary.get('total', 0)} "
        f"({b_rate * 100:.1f}%)",
        f"After:  {a_summary.get('passed', 0)}/{a_summary.get('total', 0)} "
        f"({a_rate * 100:.1f}%)",
        f"Delta:  {delta * 100:+.1f}%",
        "",
    ]

    before_by_id = {r["scenario_id"]: r for r in before.get("results", [])}
    after_by_id = {r["scenario_id"]: r for r in after.get("results", [])}

    fixed = []
    broken = []
    for sid in set(before_by_id) | set(after_by_id):
        b_pass = before_by_id.get(sid, {}).get("overall_pass", False)
        a_pass = after_by_id.get(sid, {}).get("overall_pass", False)
        if not b_pass and a_pass:
            fixed.append(sid)
        elif b_pass and not a_pass:
            broken.append(sid)

    if fixed:
        lines.append(f"Fixed ({len(fixed)}):")
        for sid in sorted(fixed):
            lines.append(f"  + {sid}")

    if broken:
        lines.append(f"Regressions ({len(broken)}):")
        for sid in sorted(broken):
            lines.append(f"  - {sid}")

    if not fixed and not broken:
        lines.append("No changes in individual scenario outcomes.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Apply suggestions from JSON file
# ---------------------------------------------------------------------------


def apply_suggestions(
    suggestions_path: str,
    dry_run: bool = False,
) -> Tuple[int, int]:
    """Apply suggestions from a JSON file to consolidated_tools.py.

    Suggestions format: JSON array of objects with old_text/new_text fields.
    Returns (applied_count, total_count).
    """
    with open(suggestions_path) as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("ERROR: suggestions file must contain a JSON array")
        return 0, 0

    source = CONSOLIDATED_TOOLS_PATH.read_text()
    applied = 0

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue

        old_text = item.get("old_text", "")
        new_text = item.get("new_text", "")
        tool_name = item.get("tool_name", "?")
        rationale = item.get("rationale", "")

        if not old_text or not new_text:
            print(f"  [{i + 1}] SKIP: missing old_text or new_text")
            continue

        if old_text == new_text:
            print(f"  [{i + 1}] SKIP: old_text == new_text")
            continue

        if old_text not in source:
            print(f"  [{i + 1}] SKIP: old_text not found ({tool_name})")
            print(f"         old: {old_text[:80]}...")
            continue

        count = source.count(old_text)
        if count > 1:
            print(f"  [{i + 1}] SKIP: old_text appears {count} times (ambiguous)")
            continue

        if dry_run:
            print(f"  [{i + 1}] WOULD APPLY: {tool_name}")
            print(f"         rationale: {rationale}")
            print(f"         old: {old_text[:80]}...")
            print(f"         new: {new_text[:80]}...")
            applied += 1
            continue

        source = source.replace(old_text, new_text, 1)
        applied += 1
        print(f"  [{i + 1}] APPLIED: {tool_name} — {rationale[:60]}")

    if not dry_run and applied > 0:
        backup_path = CONSOLIDATED_TOOLS_PATH.with_suffix(".py.bak")
        shutil.copy2(CONSOLIDATED_TOOLS_PATH, backup_path)
        CONSOLIDATED_TOOLS_PATH.write_text(source)
        print(f"  Backup saved: {backup_path}")

    return applied, len(data)


def restore_backup() -> bool:
    """Restore consolidated_tools.py from backup."""
    backup_path = CONSOLIDATED_TOOLS_PATH.with_suffix(".py.bak")
    if backup_path.exists():
        shutil.copy2(backup_path, CONSOLIDATED_TOOLS_PATH)
        print(f"Restored from {backup_path}")
        return True
    print("No backup found")
    return False


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> None:
    """Run tests and produce compact analysis report."""
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    results_path = str(out / f"results_{timestamp}.json")

    print("Running test scenarios...")
    report = run_tests(
        model=args.model,
        scenarios_dir=args.scenarios_dir,
        output_path=results_path,
        lm_url=args.lm_url,
        token=args.token,
        explain_failures=args.explain_failures,
    )

    print(f"\nResults saved: {results_path}")
    print()
    compact = build_compact_report(report)
    print(compact)


def cmd_analyze(args: argparse.Namespace) -> None:
    """Analyze existing results file and print compact report."""
    with open(args.results_file) as f:
        report = json.load(f)

    compact = build_compact_report(report)
    print(compact)


def cmd_compare(args: argparse.Namespace) -> None:
    """Compare two results files."""
    with open(args.before_file) as f:
        before = json.load(f)
    with open(args.after_file) as f:
        after = json.load(f)

    print(compare_results(before, after))


def cmd_apply(args: argparse.Namespace) -> None:
    """Apply suggestions from JSON file."""
    applied, total = apply_suggestions(args.suggestions_file, dry_run=args.dry_run)
    print(f"Applied {applied}/{total} suggestion(s)")


def cmd_restore(args: argparse.Namespace) -> None:
    """Restore consolidated_tools.py from backup."""
    restore_backup()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Tool description optimization helper. "
            "Runs tests, analyzes failures, produces compact reports "
            "for Claude Code to read and act on."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Workflow (driven by Claude Code):\n"
            "  1. Run:     python optimize.py run --model qwen3-4b\n"
            "  2. Claude Code reads the report and edits consolidated_tools.py\n"
            "  3. Re-run:  python optimize.py run --model qwen3-4b\n"
            "  4. Compare: python optimize.py compare before.json after.json\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- run ---
    p_run = subparsers.add_parser(
        "run", help="Run test scenarios and produce analysis report"
    )
    p_run.add_argument("--model", type=str, default=None, help="LM Studio model ID")
    p_run.add_argument(
        "--scenarios-dir",
        type=str,
        default=str(DEFAULT_SCENARIOS_DIR),
        help=f"Directory with scenario YAML files (default: {DEFAULT_SCENARIOS_DIR})",
    )
    p_run.add_argument(
        "--lm-url",
        default=os.environ.get("LM_STUDIO_URL", "http://localhost:1234"),
        help="LM Studio base URL",
    )
    p_run.add_argument(
        "--token",
        default=os.environ.get("LM_STUDIO_TOKEN", ""),
        help="LM Studio auth token",
    )
    p_run.add_argument(
        "--explain-failures",
        action="store_true",
        help="Ask LLM to explain incorrect tool choices",
    )
    p_run.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    p_run.set_defaults(func=cmd_run)

    # --- analyze ---
    p_analyze = subparsers.add_parser(
        "analyze", help="Analyze existing results file"
    )
    p_analyze.add_argument("results_file", help="Path to results JSON")
    p_analyze.set_defaults(func=cmd_analyze)

    # --- compare ---
    p_compare = subparsers.add_parser(
        "compare", help="Compare before/after results"
    )
    p_compare.add_argument("before_file", help="Before results JSON")
    p_compare.add_argument("after_file", help="After results JSON")
    p_compare.set_defaults(func=cmd_compare)

    # --- apply ---
    p_apply = subparsers.add_parser(
        "apply", help="Apply suggestions from JSON file"
    )
    p_apply.add_argument("suggestions_file", help="Path to suggestions JSON")
    p_apply.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without applying",
    )
    p_apply.set_defaults(func=cmd_apply)

    # --- restore ---
    p_restore = subparsers.add_parser(
        "restore", help="Restore consolidated_tools.py from backup"
    )
    p_restore.set_defaults(func=cmd_restore)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
