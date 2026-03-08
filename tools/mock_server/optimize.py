#!/usr/bin/env python3
"""Automated test → analyze → fix → retest loop for tool description optimization.

Runs LLM test scenarios, analyzes failures, generates description improvement
suggestions (via Claude API or manual review), applies fixes to
consolidated_tools.py, and re-runs to measure improvement.

Usage:
    # Full automated loop (requires ANTHROPIC_API_KEY)
    python tools/mock_server/optimize.py --model qwen3-4b

    # From existing test results (skip initial test run)
    python tools/mock_server/optimize.py --from-results mock_test_results.json

    # Manual mode (prints suggestions, waits for user to apply)
    python tools/mock_server/optimize.py --from-results results.json --manual

    # Multiple iterations
    python tools/mock_server/optimize.py --max-iterations 3
"""

import argparse
import json
import os
import re
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
    failure_type: str  # "wrong_tool", "wrong_param", "missing_call", "extra_param"
    expected_tool: str
    actual_tool: Optional[str]
    param_issues: List[Dict[str, Any]] = field(default_factory=list)
    llm_explanation: Optional[str] = None


@dataclass
class Suggestion:
    """A suggested edit to consolidated_tools.py."""

    tool_name: str
    field: str  # "description", "param_description", "param_name"
    param_name: Optional[str]
    old_text: str
    new_text: str
    rationale: str


@dataclass
class IterationResult:
    """Result of one optimize iteration."""

    iteration: int
    before_pass_rate: float
    after_pass_rate: float
    suggestions_applied: int
    suggestions_total: int
    failures_before: int
    failures_after: int
    duration_seconds: float


# ---------------------------------------------------------------------------
# Phase 1: Run tests
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
    # Collect all scenario files
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
                # Show last few lines of stderr
                lines = result.stderr.strip().split("\n")
                for line in lines[-5:]:
                    print(f"    {line}")

        # Parse results from output file
        try:
            with open(output_path) as f:
                data = json.load(f)
            all_results.extend(data.get("results", []))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"    WARNING: Could not parse results: {e}")

    # Merge all results into single report
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
# Phase 2: Analyze failures
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

            # Determine failure type
            if step.get("missing"):
                failure_type = "missing_call"
            elif not step.get("tool_match"):
                failure_type = "wrong_tool"
            else:
                # Right tool, wrong params
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


def group_failures_by_tool(
    patterns: List[FailurePattern],
) -> Dict[str, List[FailurePattern]]:
    """Group failure patterns by the tool that should have been called."""
    groups: Dict[str, List[FailurePattern]] = {}
    for p in patterns:
        groups.setdefault(p.expected_tool, []).append(p)
    return groups


def build_analysis_summary(patterns: List[FailurePattern]) -> str:
    """Build a human-readable analysis summary."""
    if not patterns:
        return "No failures detected. All scenarios passed."

    lines = [f"Found {len(patterns)} failure(s):\n"]

    by_type: Dict[str, int] = {}
    for p in patterns:
        by_type[p.failure_type] = by_type.get(p.failure_type, 0) + 1

    lines.append("By failure type:")
    for ft, count in sorted(by_type.items()):
        lines.append(f"  {ft}: {count}")

    by_tool = group_failures_by_tool(patterns)
    lines.append("\nBy expected tool:")
    for tool, fps in sorted(by_tool.items()):
        lines.append(f"  {tool}: {len(fps)} failure(s)")
        for fp in fps[:3]:  # Show first 3
            lines.append(f"    [{fp.scenario_id}] {fp.failure_type}: {fp.query[:60]}")
            if fp.llm_explanation:
                short = fp.llm_explanation[:150].replace("\n", " ")
                lines.append(f"      LLM: {short}...")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 3: Generate suggestions (Claude API or manual)
# ---------------------------------------------------------------------------


def _read_tool_definitions() -> str:
    """Read current tool definitions from consolidated_tools.py."""
    return CONSOLIDATED_TOOLS_PATH.read_text()


def _build_suggestion_prompt(
    tool_source: str,
    patterns: List[FailurePattern],
) -> str:
    """Build a prompt asking Claude to suggest description improvements."""
    failures_json = []
    for p in patterns:
        entry: Dict[str, Any] = {
            "scenario_id": p.scenario_id,
            "query": p.query,
            "failure_type": p.failure_type,
            "expected_tool": p.expected_tool,
            "actual_tool": p.actual_tool,
        }
        if p.param_issues:
            entry["param_issues"] = p.param_issues
        if p.llm_explanation:
            entry["llm_explanation"] = p.llm_explanation[:500]
        failures_json.append(entry)

    return f"""\
You are an expert at writing tool descriptions for LLM function calling.

Below are the current MCP tool definitions from consolidated_tools.py, followed
by test failures where an LLM (a smaller model like Qwen 4B) chose the wrong
tool or wrong parameters.

Your task: suggest MINIMAL edits to tool descriptions (or parameter descriptions)
that would help the LLM make the correct choice. Focus on:
1. Clarifying when to use tool A vs tool B (if wrong_tool failures exist)
2. Clarifying parameter semantics (if wrong_param failures exist)
3. Adding disambiguation hints where the LLM got confused

Rules:
- Only modify description strings, never change tool names or parameter schemas
- Keep descriptions concise — smaller LLMs have limited context
- Each suggestion must be a precise find-and-replace in the source file
- Return suggestions as a JSON array

## Current tool definitions

```python
{tool_source}
```

## Test failures

```json
{json.dumps(failures_json, indent=2)}
```

## Response format

Return ONLY a JSON array (no markdown fences, no extra text):

[
  {{
    "tool_name": "the_tool",
    "field": "description" | "param_description",
    "param_name": null | "param_name",
    "old_text": "exact text to find in the source file",
    "new_text": "replacement text",
    "rationale": "why this change helps"
  }}
]

If no changes are needed, return an empty array: []
"""


def generate_suggestions_claude(
    patterns: List[FailurePattern],
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
) -> List[Suggestion]:
    """Use Claude API to generate description improvement suggestions."""
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic package required. Install: pip install anthropic")
        sys.exit(1)

    tool_source = _read_tool_definitions()
    prompt = _build_suggestion_prompt(tool_source, patterns)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    # Extract text content
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    # Parse JSON from response
    return _parse_suggestions(text)


def generate_suggestions_manual(
    patterns: List[FailurePattern],
) -> List[Suggestion]:
    """Print analysis for manual review. Returns empty list."""
    tool_source = _read_tool_definitions()
    prompt = _build_suggestion_prompt(tool_source, patterns)

    print("\n" + "=" * 70)
    print("MANUAL MODE: Copy the prompt below into Claude or another LLM")
    print("=" * 70)
    print(prompt)
    print("=" * 70)
    print("\nAfter getting suggestions, save them as suggestions.json and re-run with:")
    print("  python tools/mock_server/optimize.py --apply-suggestions suggestions.json")
    print()

    return []


def _parse_suggestions(text: str) -> List[Suggestion]:
    """Parse suggestions JSON from LLM response text."""
    # Try to extract JSON array from the text
    # Handle markdown fences if present
    text = text.strip()
    if text.startswith("```"):
        # Remove markdown fences
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON array in the text
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                print(f"  WARNING: Could not parse suggestions JSON")
                return []
        else:
            print(f"  WARNING: No JSON array found in response")
            return []

    if not isinstance(data, list):
        return []

    suggestions = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            suggestions.append(Suggestion(
                tool_name=item["tool_name"],
                field=item["field"],
                param_name=item.get("param_name"),
                old_text=item["old_text"],
                new_text=item["new_text"],
                rationale=item.get("rationale", ""),
            ))
        except KeyError as e:
            print(f"  WARNING: Skipping malformed suggestion (missing {e})")

    return suggestions


def load_suggestions_from_file(path: str) -> List[Suggestion]:
    """Load suggestions from a JSON file."""
    with open(path) as f:
        data = json.load(f)
    return _parse_suggestions(json.dumps(data))


# ---------------------------------------------------------------------------
# Phase 4: Apply fixes
# ---------------------------------------------------------------------------


def apply_suggestions(
    suggestions: List[Suggestion],
    dry_run: bool = False,
) -> Tuple[int, int]:
    """Apply suggestions to consolidated_tools.py.

    Returns (applied_count, total_count).
    """
    if not suggestions:
        return 0, 0

    source = CONSOLIDATED_TOOLS_PATH.read_text()
    applied = 0

    for i, s in enumerate(suggestions):
        if s.old_text not in source:
            print(f"  [{i + 1}] SKIP: old_text not found for {s.tool_name}.{s.field}")
            if s.param_name:
                print(f"         param: {s.param_name}")
            print(f"         old: {s.old_text[:80]}...")
            continue

        if s.old_text == s.new_text:
            print(f"  [{i + 1}] SKIP: old_text == new_text for {s.tool_name}.{s.field}")
            continue

        # Check for ambiguous matches
        count = source.count(s.old_text)
        if count > 1:
            print(f"  [{i + 1}] SKIP: old_text appears {count} times (ambiguous)")
            continue

        if dry_run:
            print(f"  [{i + 1}] WOULD APPLY: {s.tool_name}.{s.field}")
            print(f"         rationale: {s.rationale}")
            print(f"         old: {s.old_text[:80]}...")
            print(f"         new: {s.new_text[:80]}...")
            applied += 1
            continue

        source = source.replace(s.old_text, s.new_text, 1)
        applied += 1
        print(f"  [{i + 1}] APPLIED: {s.tool_name}.{s.field} — {s.rationale[:60]}")

    if not dry_run and applied > 0:
        # Backup before writing
        backup_path = CONSOLIDATED_TOOLS_PATH.with_suffix(".py.bak")
        shutil.copy2(CONSOLIDATED_TOOLS_PATH, backup_path)
        CONSOLIDATED_TOOLS_PATH.write_text(source)
        print(f"  Backup saved: {backup_path}")

    return applied, len(suggestions)


def restore_backup() -> bool:
    """Restore consolidated_tools.py from backup."""
    backup_path = CONSOLIDATED_TOOLS_PATH.with_suffix(".py.bak")
    if backup_path.exists():
        shutil.copy2(backup_path, CONSOLIDATED_TOOLS_PATH)
        return True
    return False


# ---------------------------------------------------------------------------
# Phase 5: Comparison report
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
        "=" * 50,
        "OPTIMIZATION RESULT",
        "=" * 50,
        f"Before: {b_summary.get('passed', 0)}/{b_summary.get('total', 0)} "
        f"({b_rate * 100:.1f}%)",
        f"After:  {a_summary.get('passed', 0)}/{a_summary.get('total', 0)} "
        f"({a_rate * 100:.1f}%)",
        f"Delta:  {delta * 100:+.1f}%",
        "",
    ]

    # Show which scenarios changed
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
# Main optimization loop
# ---------------------------------------------------------------------------


def run_optimization(
    model: Optional[str],
    scenarios_dir: str,
    lm_url: str,
    token: str,
    api_key: Optional[str],
    claude_model: str,
    max_iterations: int,
    manual: bool,
    from_results: Optional[str],
    apply_suggestions_file: Optional[str],
    dry_run: bool,
    output_dir: str,
) -> None:
    """Run the full optimization loop."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Handle --apply-suggestions mode
    if apply_suggestions_file:
        print(f"Loading suggestions from {apply_suggestions_file}")
        suggestions = load_suggestions_from_file(apply_suggestions_file)
        print(f"Found {len(suggestions)} suggestion(s)")
        applied, total = apply_suggestions(suggestions, dry_run=dry_run)
        print(f"Applied {applied}/{total} suggestion(s)")
        return

    for iteration in range(1, max_iterations + 1):
        iter_dir = out / f"iteration_{iteration:02d}"
        iter_dir.mkdir(exist_ok=True)
        iter_start = time.time()

        print(f"\n{'=' * 50}")
        print(f"ITERATION {iteration}/{max_iterations}")
        print(f"{'=' * 50}")

        # Phase 1: Run tests (or load from file)
        before_path = str(iter_dir / "before_results.json")
        if from_results and iteration == 1:
            print(f"\nPhase 1: Loading results from {from_results}")
            with open(from_results) as f:
                before_report = json.load(f)
            # Copy to iteration dir
            with open(before_path, "w") as f:
                json.dump(before_report, f, indent=2)
        else:
            print("\nPhase 1: Running test scenarios...")
            before_report = run_tests(
                model=model,
                scenarios_dir=scenarios_dir,
                output_path=before_path,
                lm_url=lm_url,
                token=token,
                explain_failures=True,
            )

        b_summary = before_report.get("summary", {})
        print(
            f"  Results: {b_summary.get('passed', 0)}/{b_summary.get('total', 0)} "
            f"passed ({b_summary.get('pass_rate', 0) * 100:.1f}%)"
        )

        if b_summary.get("pass_rate", 0) == 1.0:
            print("  All scenarios pass! Nothing to optimize.")
            break

        # Phase 2: Analyze failures
        print("\nPhase 2: Analyzing failures...")
        patterns = extract_failure_patterns(before_report)
        summary = build_analysis_summary(patterns)
        print(summary)

        # Save analysis
        analysis_path = iter_dir / "analysis.txt"
        analysis_path.write_text(summary)

        if not patterns:
            print("  No actionable failure patterns found.")
            break

        # Phase 3: Generate suggestions
        print("\nPhase 3: Generating improvement suggestions...")
        if manual:
            suggestions = generate_suggestions_manual(patterns)
            if not suggestions:
                print("  Manual mode: exiting after analysis.")
                break
        elif api_key:
            suggestions = generate_suggestions_claude(
                patterns, api_key, model=claude_model
            )
            print(f"  Generated {len(suggestions)} suggestion(s)")
        else:
            print(
                "  No API key provided. Use --manual or set ANTHROPIC_API_KEY.\n"
                "  Falling back to manual mode."
            )
            suggestions = generate_suggestions_manual(patterns)
            if not suggestions:
                break

        # Save suggestions
        suggestions_data = [
            {
                "tool_name": s.tool_name,
                "field": s.field,
                "param_name": s.param_name,
                "old_text": s.old_text,
                "new_text": s.new_text,
                "rationale": s.rationale,
            }
            for s in suggestions
        ]
        suggestions_path = iter_dir / "suggestions.json"
        with open(suggestions_path, "w") as f:
            json.dump(suggestions_data, f, indent=2, ensure_ascii=False)
        print(f"  Saved to {suggestions_path}")

        if not suggestions:
            print("  No suggestions generated.")
            break

        # Phase 4: Apply fixes
        print("\nPhase 4: Applying suggestions...")
        applied, total = apply_suggestions(suggestions, dry_run=dry_run)
        print(f"  Applied {applied}/{total}")

        if applied == 0 or dry_run:
            print("  No changes applied — skipping re-test.")
            break

        # Phase 5: Re-run tests
        print("\nPhase 5: Re-running test scenarios...")
        after_path = str(iter_dir / "after_results.json")
        after_report = run_tests(
            model=model,
            scenarios_dir=scenarios_dir,
            output_path=after_path,
            lm_url=lm_url,
            token=token,
            explain_failures=False,  # No explanations on verification run
        )

        # Phase 6: Compare
        print("\nPhase 6: Comparison")
        comparison = compare_results(before_report, after_report)
        print(comparison)

        comparison_path = iter_dir / "comparison.txt"
        comparison_path.write_text(comparison)

        a_summary = after_report.get("summary", {})
        iter_duration = time.time() - iter_start

        # Check for regressions
        a_rate = a_summary.get("pass_rate", 0)
        b_rate = b_summary.get("pass_rate", 0)
        if a_rate < b_rate:
            print("\n  WARNING: Regressions detected! Restoring backup...")
            if restore_backup():
                print("  Restored consolidated_tools.py from backup.")
            else:
                print("  WARNING: No backup found!")
            break

        if a_rate == 1.0:
            print("\n  All scenarios pass! Optimization complete.")
            break

        print(f"\n  Iteration {iteration} complete in {iter_duration:.1f}s")
        # Next iteration will use the updated tools

    print(f"\nResults saved to {output_dir}/")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Automated tool description optimization loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --model qwen3-4b\n"
            "  %(prog)s --from-results mock_test_results.json --manual\n"
            "  %(prog)s --apply-suggestions suggestions.json\n"
            "  %(prog)s --max-iterations 3 --model qwen3-4b\n"
        ),
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="LM Studio model ID (substring match). Default: first loaded model.",
    )
    parser.add_argument(
        "--scenarios-dir",
        type=str,
        default=str(DEFAULT_SCENARIOS_DIR),
        help=f"Directory with scenario YAML files (default: {DEFAULT_SCENARIOS_DIR})",
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
        "--api-key",
        default=os.environ.get("ANTHROPIC_API_KEY", ""),
        help="Anthropic API key for Claude-assisted analysis",
    )
    parser.add_argument(
        "--claude-model",
        default="claude-sonnet-4-20250514",
        help="Claude model for analysis (default: claude-sonnet-4-20250514)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=1,
        help="Max optimization iterations (default: 1)",
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Manual mode: print suggestions prompt instead of using Claude API",
    )
    parser.add_argument(
        "--from-results",
        type=str,
        default=None,
        help="Skip initial test run, load results from this JSON file",
    )
    parser.add_argument(
        "--apply-suggestions",
        type=str,
        default=None,
        help="Apply suggestions from a JSON file (skip test+analyze phases)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without applying",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory for iteration results (default: {DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args()

    run_optimization(
        model=args.model,
        scenarios_dir=args.scenarios_dir,
        lm_url=args.lm_url,
        token=args.token,
        api_key=args.api_key,
        claude_model=args.claude_model,
        max_iterations=args.max_iterations,
        manual=args.manual,
        from_results=args.from_results,
        apply_suggestions_file=args.apply_suggestions,
        dry_run=args.dry_run,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
