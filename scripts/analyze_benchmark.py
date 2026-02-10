#!/usr/bin/env python3
"""Analyze benchmark JSONL output from the LLM benchmark harness.

Reads JSONL records produced by benchmark_llm_tools.py and generates:
- Per-model summary table
- Per-category breakdown
- Tool usage analysis
- Failure pattern classification
- Model x Query success matrix
- Argument dump for each (model, query)

Usage:
    python scripts/analyze_benchmark.py benchmark_results.jsonl
    python scripts/analyze_benchmark.py benchmark_results.jsonl --json
    python scripts/analyze_benchmark.py benchmark_results.jsonl --section summary
    python scripts/analyze_benchmark.py benchmark_results.jsonl --section failures
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_records(path: str) -> list[dict[str, Any]]:
    """Load JSONL benchmark records."""
    records: list[dict[str, Any]] = []
    with open(path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"Warning: skipping malformed line {line_num}: {e}", file=sys.stderr)
    return records


# ---------------------------------------------------------------------------
# Failure pattern classification
# ---------------------------------------------------------------------------

# Patterns that indicate a function signature was used as a search pattern
_SIGNATURE_PATTERNS = [
    r".*\(.*\).*",  # contains parentheses (function args)
    r".*\bconst\b.*&.*",  # "const&" in pattern
    r".*\bvoid\b\s+\w+.*",  # "void funcname"
    r".*\bbool\b\s+\w+.*",  # "bool funcname"
    r".*\bint\b\s+\w+.*",  # "int funcname"
]

# Patterns indicating qualified name used in search pattern argument
_QUALIFIED_NAME_RE = re.compile(r"^[\w]+(::\w+)+$")


def classify_failures(record: dict[str, Any]) -> list[str]:
    """Classify failure patterns for a single benchmark record.

    Returns a list of failure pattern labels (may be empty for success).
    """
    patterns: list[str] = []

    # No tool calls at all
    if record["total_tool_calls"] == 0 and not record.get("error"):
        patterns.append("no_tool_calls")
        return patterns

    # Connection/API error
    if record.get("error"):
        error = record["error"]
        if "connection_error" in error:
            patterns.append("connection_error")
        elif "max_tokens" in error:
            patterns.append("max_tokens_exceeded")
        elif "json_decode" in error:
            patterns.append("json_decode_error")
        else:
            patterns.append("other_error")
        return patterns

    tool_calls = record.get("tool_calls", [])

    for tc in tool_calls:
        args = tc.get("arguments", {})
        tool = tc.get("tool", "")

        # Check search tools for pattern issues
        if tool in ("search_classes", "search_functions", "search_symbols"):
            pattern = args.get("pattern", "")
            if not pattern and not args.get("file_name"):
                patterns.append("empty_pattern")
                continue

            # Signature in pattern: contains parens or type keywords
            for sig_pat in _SIGNATURE_PATTERNS:
                if re.match(sig_pat, pattern):
                    patterns.append("signature_in_pattern")
                    break

            # Qualified name as search pattern (ns::Class)
            if _QUALIFIED_NAME_RE.match(pattern):
                patterns.append("qualified_name_as_pattern")

    # Empty results without retry
    if record["empty_result_count"] > 0:
        # Check if there was a subsequent call with different args
        empty_tools = set()
        retried = False
        for tc in tool_calls:
            result_count = tc.get("result_count")
            if result_count == 0:
                empty_tools.add(tc["tool"])
            elif tc["tool"] in empty_tools:
                retried = True
        if not retried:
            patterns.append("empty_results_no_retry")

    # Wrong regex: pattern doesn't match expected tools' typical usage
    for tc in tool_calls:
        args = tc.get("arguments", {})
        pattern = args.get("pattern", "")
        if pattern and tc.get("result_count") == 0:
            # Check for common regex mistakes
            if pattern.startswith("^") or pattern.endswith("$"):
                patterns.append("wrong_regex")
            elif "\\" in pattern and not re.match(r".*\\[.*+?dswb]", pattern):
                patterns.append("wrong_regex")

    # Deduplicate
    return list(dict.fromkeys(patterns))


# ---------------------------------------------------------------------------
# Analysis sections
# ---------------------------------------------------------------------------


def _success_heuristic(record: dict[str, Any]) -> bool:
    """Heuristic: a query is 'successful' if it used tools and got results."""
    if record.get("error"):
        return False
    if record["total_tool_calls"] == 0:
        return False
    # If ALL tool calls returned 0 results, it's a failure
    tool_calls = record.get("tool_calls", [])
    if tool_calls:
        result_counts = [tc.get("result_count") for tc in tool_calls if "result_count" in tc]
        if result_counts and all(c == 0 for c in result_counts):
            return False
    return True


def analyze_per_model(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-model summary statistics."""
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_model[r["model_id"]].append(r)

    summaries: list[dict[str, Any]] = []
    for model_id, recs in sorted(by_model.items()):
        total = len(recs)
        successes = sum(1 for r in recs if _success_heuristic(r))
        errors = sum(1 for r in recs if r.get("error"))
        tool_calls_total = sum(r["total_tool_calls"] for r in recs)
        empty_results_total = sum(r["empty_result_count"] for r in recs)
        wall_times = [r["wall_time_seconds"] for r in recs]
        tps_values = [
            r["stats"].get("tokens_per_second")
            for r in recs
            if r.get("stats", {}).get("tokens_per_second")
        ]
        input_tokens = sum(r["stats"].get("input_tokens", 0) for r in recs if r.get("stats"))
        output_tokens = sum(r["stats"].get("output_tokens", 0) for r in recs if r.get("stats"))

        summaries.append(
            {
                "model_id": model_id,
                "total_queries": total,
                "successes": successes,
                "success_rate": round(successes / total * 100, 1) if total else 0,
                "errors": errors,
                "total_tool_calls": tool_calls_total,
                "avg_tool_calls": round(tool_calls_total / total, 1) if total else 0,
                "empty_results": empty_results_total,
                "total_wall_time": round(sum(wall_times), 1),
                "avg_wall_time": round(sum(wall_times) / total, 1) if total else 0,
                "avg_tokens_per_sec": (
                    round(sum(tps_values) / len(tps_values), 1) if tps_values else None
                ),
                "total_input_tokens": input_tokens,
                "total_output_tokens": output_tokens,
            }
        )
    return summaries


def analyze_per_category(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-category breakdown: success rate per (model, category)."""
    # category -> model -> list of records
    by_cat_model: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in records:
        by_cat_model[r["query_category"]][r["model_id"]].append(r)

    result: dict[str, dict[str, Any]] = {}
    for category in sorted(by_cat_model):
        cat_data: dict[str, Any] = {}
        for model_id in sorted(by_cat_model[category]):
            recs = by_cat_model[category][model_id]
            total = len(recs)
            successes = sum(1 for r in recs if _success_heuristic(r))
            cat_data[model_id] = {
                "total": total,
                "successes": successes,
                "success_rate": round(successes / total * 100, 1) if total else 0,
            }
        result[category] = cat_data
    return result


def analyze_tool_usage(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Tool usage analysis: expected vs actual, common argument patterns."""
    tool_counts: dict[str, int] = defaultdict(int)
    expected_vs_actual: list[dict[str, Any]] = []

    for r in records:
        actual_tools = [tc["tool"] for tc in r.get("tool_calls", [])]
        expected = r.get("expected_tools", [])

        for tool in actual_tools:
            tool_counts[tool] += 1

        expected_set = set(expected)
        actual_set = set(actual_tools)

        expected_vs_actual.append(
            {
                "model_id": r["model_id"],
                "query_id": r["query_id"],
                "expected": sorted(expected_set),
                "actual": sorted(actual_set),
                "missing": sorted(expected_set - actual_set),
                "extra": sorted(actual_set - expected_set),
                "match": expected_set == actual_set,
            }
        )

    # Tool match rate per model
    match_by_model: dict[str, dict[str, int]] = defaultdict(lambda: {"match": 0, "total": 0})
    for item in expected_vs_actual:
        match_by_model[item["model_id"]]["total"] += 1
        if item["match"]:
            match_by_model[item["model_id"]]["match"] += 1

    return {
        "tool_call_frequency": dict(sorted(tool_counts.items(), key=lambda x: -x[1])),
        "tool_match_rate": {
            model: round(v["match"] / v["total"] * 100, 1) if v["total"] else 0
            for model, v in sorted(match_by_model.items())
        },
        "mismatches": [item for item in expected_vs_actual if not item["match"]],
    }


def analyze_failures(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Failure pattern classification across all records."""
    pattern_counts: dict[str, int] = defaultdict(int)
    pattern_examples: dict[str, list[dict[str, str]]] = defaultdict(list)

    for r in records:
        patterns = classify_failures(r)
        for p in patterns:
            pattern_counts[p] += 1
            if len(pattern_examples[p]) < 3:  # Keep up to 3 examples
                pattern_examples[p].append(
                    {
                        "model_id": r["model_id"],
                        "query_id": r["query_id"],
                    }
                )

    # Per-model failure patterns
    by_model: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in records:
        patterns = classify_failures(r)
        for p in patterns:
            by_model[r["model_id"]][p] += 1

    return {
        "pattern_counts": dict(sorted(pattern_counts.items(), key=lambda x: -x[1])),
        "pattern_examples": dict(pattern_examples),
        "by_model": {m: dict(v) for m, v in sorted(by_model.items())},
    }


def build_query_matrix(records: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Model x Query success/fail matrix.

    Returns: {model_id: {query_id: status_char}}
    Status chars: OK=success, FAIL=failure, ERR=error, NONE=no tool calls
    """
    matrix: dict[str, dict[str, str]] = defaultdict(dict)
    for r in records:
        model = r["model_id"]
        query = r["query_id"]
        if r.get("error"):
            matrix[model][query] = "ERR"
        elif r["total_tool_calls"] == 0:
            matrix[model][query] = "NONE"
        elif _success_heuristic(r):
            matrix[model][query] = "OK"
        else:
            matrix[model][query] = "FAIL"
    return dict(matrix)


def build_argument_dump(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For each (model, query), show actual arguments used."""
    dump: list[dict[str, Any]] = []
    for r in records:
        calls_summary: list[dict[str, Any]] = []
        for tc in r.get("tool_calls", []):
            entry: dict[str, Any] = {
                "tool": tc["tool"],
                "arguments": tc.get("arguments", {}),
            }
            if "result_count" in tc:
                entry["result_count"] = tc["result_count"]
            calls_summary.append(entry)
        dump.append(
            {
                "model_id": r["model_id"],
                "query_id": r["query_id"],
                "query_text": r["query_text"],
                "tool_calls": calls_summary,
                "failure_patterns": classify_failures(r),
            }
        )
    return dump


# ---------------------------------------------------------------------------
# Text output formatting
# ---------------------------------------------------------------------------

CATEGORY_LABELS = {
    "baseline": "A: Baseline",
    "qualified_names": "B: Qualified names",
    "signature_confusion": "C: Signature confusion",
    "regex_patterns": "D: Regex patterns",
    "multi_tool": "E: Multi-tool workflows",
}


def _short_model(model_id: str, max_len: int = 28) -> str:
    """Shorten model ID for table display."""
    if len(model_id) <= max_len:
        return model_id
    return model_id[: max_len - 2] + ".."


def print_summary(summaries: list[dict[str, Any]]) -> None:
    """Print per-model summary table."""
    print("=" * 100)
    print("PER-MODEL SUMMARY")
    print("=" * 100)
    header = (
        f"{'Model':<30} {'Success':>7} {'Errors':>6} {'ToolCalls':>9} "
        f"{'Empty':>5} {'AvgTime':>7} {'TPS':>7} {'InTok':>7} {'OutTok':>7}"
    )
    print(header)
    print("-" * 100)
    for s in summaries:
        tps = f"{s['avg_tokens_per_sec']:>7.1f}" if s["avg_tokens_per_sec"] else "    N/A"
        print(
            f"{_short_model(s['model_id']):<30} "
            f"{s['success_rate']:>6.1f}% "
            f"{s['errors']:>6} "
            f"{s['avg_tool_calls']:>9.1f} "
            f"{s['empty_results']:>5} "
            f"{s['avg_wall_time']:>6.1f}s "
            f"{tps} "
            f"{s['total_input_tokens']:>7} "
            f"{s['total_output_tokens']:>7}"
        )
    print()


def print_category_breakdown(cat_data: dict[str, dict[str, Any]]) -> None:
    """Print per-category success rates."""
    print("=" * 100)
    print("PER-CATEGORY SUCCESS RATES (%)")
    print("=" * 100)

    # Collect all models
    all_models: list[str] = []
    for cat_models in cat_data.values():
        for m in cat_models:
            if m not in all_models:
                all_models.append(m)
    all_models.sort()

    # Header
    short_models = [_short_model(m, 12) for m in all_models]
    header = f"{'Category':<26}" + "".join(f"{sm:>14}" for sm in short_models)
    print(header)
    print("-" * 100)

    for category in sorted(cat_data):
        label = CATEGORY_LABELS.get(category, category)
        row = f"{label:<26}"
        for model in all_models:
            if model in cat_data[category]:
                rate = cat_data[category][model]["success_rate"]
                total = cat_data[category][model]["total"]
                row += f"{rate:>6.0f}% ({total})" + " " * 2
            else:
                row += f"{'N/A':>14}"
        print(row)
    print()


def print_tool_usage(tool_data: dict[str, Any]) -> None:
    """Print tool usage analysis."""
    print("=" * 80)
    print("TOOL USAGE ANALYSIS")
    print("=" * 80)

    print("\nTool call frequency:")
    for tool, count in tool_data["tool_call_frequency"].items():
        print(f"  {tool:<35} {count:>5} calls")

    print("\nExpected tool set match rate:")
    for model, rate in tool_data["tool_match_rate"].items():
        print(f"  {_short_model(model):<30} {rate:>5.1f}%")

    # Show mismatches summary
    mismatches = tool_data["mismatches"]
    if mismatches:
        print(f"\nTool set mismatches ({len(mismatches)} total):")
        # Group by type of mismatch
        missing_counts: dict[str, int] = defaultdict(int)
        extra_counts: dict[str, int] = defaultdict(int)
        for m in mismatches:
            for tool in m["missing"]:
                missing_counts[tool] += 1
            for tool in m["extra"]:
                extra_counts[tool] += 1
        if missing_counts:
            print("  Missing tools (expected but not used):")
            for tool, count in sorted(missing_counts.items(), key=lambda x: -x[1]):
                print(f"    {tool:<35} {count:>3} times")
        if extra_counts:
            print("  Extra tools (used but not expected):")
            for tool, count in sorted(extra_counts.items(), key=lambda x: -x[1]):
                print(f"    {tool:<35} {count:>3} times")
    print()


def print_failures(failure_data: dict[str, Any]) -> None:
    """Print failure pattern classification."""
    print("=" * 80)
    print("FAILURE PATTERN CLASSIFICATION")
    print("=" * 80)

    pattern_counts = failure_data["pattern_counts"]
    if not pattern_counts:
        print("No failure patterns detected!")
        print()
        return

    print("\nPattern frequency:")
    for pattern, count in pattern_counts.items():
        examples = failure_data["pattern_examples"].get(pattern, [])
        example_str = ", ".join(f"{e['model_id']}:{e['query_id']}" for e in examples[:2])
        print(f"  {pattern:<30} {count:>3} occurrences  (e.g. {example_str})")

    print("\nFailure patterns by model:")
    by_model = failure_data["by_model"]
    for model, patterns in sorted(by_model.items()):
        if patterns:
            pattern_str = ", ".join(f"{p}={c}" for p, c in sorted(patterns.items()))
            print(f"  {_short_model(model):<30} {pattern_str}")
    print()


def print_query_matrix(matrix: dict[str, dict[str, str]]) -> None:
    """Print model x query compact grid."""
    print("=" * 100)
    print("MODEL x QUERY MATRIX (OK=success, FAIL=failure, ERR=error, NONE=no tools)")
    print("=" * 100)

    if not matrix:
        print("No data.")
        return

    # Collect all query IDs
    all_queries: list[str] = sorted(
        {qid for model_queries in matrix.values() for qid in model_queries}
    )

    # Header
    header = f"{'Model':<30}" + "".join(f"{q:>6}" for q in all_queries)
    print(header)
    print("-" * (30 + 6 * len(all_queries)))

    for model in sorted(matrix):
        row = f"{_short_model(model):<30}"
        ok_count = 0
        for q in all_queries:
            status = matrix[model].get(q, "?")
            if status == "OK":
                ok_count += 1
            row += f"{status:>6}"
        row += f"  [{ok_count}/{len(all_queries)}]"
        print(row)
    print()


def print_argument_dump(dump: list[dict[str, Any]], model_filter: Optional[str] = None) -> None:
    """Print argument dump for each (model, query)."""
    print("=" * 80)
    print("ARGUMENT DUMP")
    print("=" * 80)

    for entry in dump:
        if model_filter and model_filter not in entry["model_id"]:
            continue

        failures = entry["failure_patterns"]
        failure_str = f" [{', '.join(failures)}]" if failures else ""
        print(f"\n--- {entry['model_id']} / {entry['query_id']}{failure_str} ---")
        print(f"  Query: {entry['query_text'][:80]}")

        if not entry["tool_calls"]:
            print("  (no tool calls)")
            continue

        for i, tc in enumerate(entry["tool_calls"], 1):
            result = f" -> {tc['result_count']} results" if "result_count" in tc else ""
            print(f"  [{i}] {tc['tool']}{result}")
            args = tc.get("arguments", {})
            for k, v in args.items():
                val_str = json.dumps(v) if not isinstance(v, str) else v
                print(f"      {k}: {val_str}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

ALL_SECTIONS = ["summary", "categories", "tools", "failures", "matrix", "arguments"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze LLM benchmark JSONL results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s benchmark_results.jsonl\n"
            "  %(prog)s benchmark_results.jsonl --json\n"
            "  %(prog)s benchmark_results.jsonl --section summary --section matrix\n"
            "  %(prog)s benchmark_results.jsonl --section arguments --model gpt-oss-20b\n"
        ),
    )
    parser.add_argument("input", help="JSONL file from benchmark_llm_tools.py")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON instead of text tables",
    )
    parser.add_argument(
        "--section",
        action="append",
        dest="sections",
        choices=ALL_SECTIONS,
        help=f"Show only specific section(s). Options: {', '.join(ALL_SECTIONS)}",
    )
    parser.add_argument(
        "--model",
        metavar="SUBSTR",
        help="Filter argument dump to model matching substring",
    )
    args = parser.parse_args()

    records = load_records(args.input)
    if not records:
        print(f"No records found in {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(records)} records from {args.input}", file=sys.stderr)

    sections = args.sections or ALL_SECTIONS

    # Compute all analyses
    summaries = analyze_per_model(records)
    cat_data = analyze_per_category(records)
    tool_data = analyze_tool_usage(records)
    failure_data = analyze_failures(records)
    matrix = build_query_matrix(records)
    arg_dump = build_argument_dump(records)

    if args.json:
        output: dict[str, Any] = {}
        if "summary" in sections:
            output["per_model_summary"] = summaries
        if "categories" in sections:
            output["per_category"] = cat_data
        if "tools" in sections:
            output["tool_usage"] = tool_data
        if "failures" in sections:
            output["failure_patterns"] = failure_data
        if "matrix" in sections:
            output["query_matrix"] = matrix
        if "arguments" in sections:
            output["argument_dump"] = arg_dump
        json.dump(output, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return

    # Text output
    if "summary" in sections:
        print_summary(summaries)
    if "categories" in sections:
        print_category_breakdown(cat_data)
    if "tools" in sections:
        print_tool_usage(tool_data)
    if "failures" in sections:
        print_failures(failure_data)
    if "matrix" in sections:
        print_query_matrix(matrix)
    if "arguments" in sections:
        print_argument_dump(arg_dump, model_filter=args.model)


if __name__ == "__main__":
    main()
