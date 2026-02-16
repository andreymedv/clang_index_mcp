#!/usr/bin/env python3
"""
Analyze MCP tool usage from LM Studio conversation JSON files.

Extracts tool call pairs (request → result), classifies patterns,
detects retries, and outputs JSONL with the same schema as the
server-side tool_call_logger plus an llm_reasoning field.

Usage:
    python scripts/analyze_tool_usage.py <conversation.json> [-o output.jsonl]
    python scripts/analyze_tool_usage.py <conversation.json> --append-to <server_log.jsonl>
"""

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server.smart_fallback import _PROTOTYPE_PATTERN, _looks_like_signature  # noqa: E402

# Same regex meta detection as tool_call_logger
_REGEX_META = re.compile(r"[.*+?\[\]{}()|\\^$]")

_SEARCH_TOOLS = {
    "search_classes",
    "search_functions",
    "search_symbols",
    "find_in_file",
}

# MCP plugin identifiers that indicate our server
_MCP_PLUGIN_IDS = {"cpp-analyzer", "clang-index-mcp"}


def _classify_pattern(pattern: str) -> str:
    """Classify a search pattern (same logic as server-side logger)."""
    if _looks_like_signature(pattern):
        return "signature_like"
    if _PROTOTYPE_PATTERN.search(pattern):
        return "prototype_like"
    has_colons = "::" in pattern
    has_meta = bool(_REGEX_META.search(pattern))
    if has_colons and not has_meta:
        return "qualified_name"
    if has_meta:
        return "regex"
    return "plain_name"


def _extract_pattern_features(pattern: str) -> Dict[str, bool]:
    """Extract boolean features from a pattern."""
    type_keywords = {
        "void",
        "bool",
        "int",
        "float",
        "double",
        "char",
        "const",
        "auto",
        "unsigned",
        "long",
        "short",
        "typename",
        "struct",
        "class",
    }
    tokens = set(re.findall(r"\b\w+\b", pattern.lower()))
    return {
        "has_parens": "(" in pattern,
        "has_spaces": " " in pattern,
        "has_colons": "::" in pattern,
        "has_regex_meta": bool(_REGEX_META.search(pattern)),
        "has_type_keywords": bool(tokens & type_keywords),
    }


def _is_analysis_step(step: dict) -> bool:
    """Check if a step is a thinking/analysis step (from lmsconv2bin.py)."""
    style = step.get("style", {})
    prefix = step.get("prefix", "") or ""
    if style.get("type") == "thinking":
        return True
    if "<|channel|>analysis" in prefix:
        return True
    return False


def _extract_text_content(block_content: list) -> str:
    """Extract text parts from content[] (from lmsconv2bin.py)."""
    parts = []
    for c in block_content:
        if c.get("type") == "text":
            parts.append(c.get("text", ""))
    return "\n".join(parts).strip()


def _extract_tool_call_info(content: list) -> Optional[Dict[str, Any]]:
    """Extract tool name and parameters from a toolCallRequest content block."""
    for c in content:
        if c.get("type") == "toolCallRequest":
            return {
                "name": c.get("name", "unknown"),
                "parameters": c.get("parameters", {}),
                "plugin": c.get("pluginIdentifier", ""),
            }
    return None


def _extract_tool_result_text(content: list) -> str:
    """Extract result text from a toolCallResult content block."""
    for c in content:
        if c.get("type") == "toolCallResult":
            raw = c.get("content", "")
            try:
                parsed = json.loads(raw)
                text_parts = []
                for item in parsed:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                return "\n".join(text_parts).strip()
            except (json.JSONDecodeError, TypeError):
                return raw
    return ""


def _count_results(result_text: str) -> int:
    """Count results from tool result text."""
    try:
        parsed = json.loads(result_text)
        if isinstance(parsed, list):
            return len(parsed)
        if isinstance(parsed, dict):
            results_list = parsed.get("results")
            if isinstance(results_list, list):
                return len(results_list)
            for key in ("callers", "callees"):
                sub = parsed.get(key)
                if isinstance(sub, list):
                    return len(sub)
    except (json.JSONDecodeError, TypeError):
        pass
    return 0


def _extract_distributions(
    result_text: str,
) -> Tuple[Optional[Dict[str, int]], Optional[Dict[str, int]]]:
    """Extract class and namespace distribution from result JSON."""
    try:
        parsed = json.loads(result_text)
        items = parsed.get("results", parsed) if isinstance(parsed, dict) else parsed
        if not isinstance(items, list):
            return None, None
        classes: Counter = Counter()
        namespaces: Counter = Counter()
        for item in items:
            if isinstance(item, dict):
                cn = item.get("class_name", "")
                ns = item.get("namespace", "")
                if cn:
                    classes[cn] += 1
                if ns:
                    namespaces[ns] += 1
        class_dist = dict(classes.most_common(5)) if classes else None
        ns_dist = dict(namespaces.most_common(5)) if namespaces else None
        return class_dist, ns_dist
    except (json.JSONDecodeError, TypeError):
        return None, None


def extract_tool_calls(data: dict) -> List[Dict[str, Any]]:
    """Extract all MCP tool call pairs from an LM Studio conversation.

    Walks through messages → versions → steps, pairing toolCallRequest
    steps with their following toolCallResult steps.
    """
    entries = []
    recent_calls: List[Dict[str, Any]] = []  # For retry detection

    for msg in data.get("messages", []):
        versions = msg.get("versions", [])
        if not versions:
            continue

        version = versions[msg.get("currentlySelected", 0)]
        if version.get("type") not in ("multiStep", "singleStep"):
            continue

        steps = version.get("steps", [])
        pending_call: Optional[Dict[str, Any]] = None
        preceding_analysis: Optional[str] = None

        for step in steps:
            stype = step.get("type")
            content = step.get("content", [])

            # Capture analysis/thinking that precedes tool calls
            if stype == "contentBlock" and _is_analysis_step(step):
                text = _extract_text_content(content)
                if text:
                    preceding_analysis = text
                continue

            # Tool call request
            if stype == "contentBlock" and any(c.get("type") == "toolCallRequest" for c in content):
                call_info = _extract_tool_call_info(content)
                if call_info:
                    pending_call = call_info
                    pending_call["preceding_analysis"] = preceding_analysis
                    preceding_analysis = None
                continue

            # Tool call result — pair with pending call
            if stype == "contentBlock" and any(c.get("type") == "toolCallResult" for c in content):
                if pending_call is None:
                    continue

                result_text = _extract_tool_result_text(content)
                result_count = _count_results(result_text)
                tool_name = pending_call["name"]
                arguments = pending_call["parameters"]

                now = time.time()
                entry: Dict[str, Any] = {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "result_count": result_count,
                    "timestamp": now,
                    "timestamp_readable": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                    "session_id": "lm-studio-analysis",
                    "source": "lm_studio",
                }

                # LLM reasoning field
                if pending_call.get("preceding_analysis"):
                    entry["llm_reasoning"] = pending_call["preceding_analysis"]

                pattern = arguments.get("pattern", "")

                # Empty-result enrichment
                if result_count == 0 and tool_name in _SEARCH_TOOLS and pattern:
                    entry["pattern_classification"] = _classify_pattern(pattern)
                    entry["pattern_features"] = _extract_pattern_features(pattern)

                # Large-result enrichment
                if result_count > 50:
                    filter_keys = [
                        "class_name",
                        "namespace",
                        "file_name",
                        "signature_pattern",
                        "file_path",
                        "symbol_types",
                    ]
                    filters = [k for k in filter_keys if arguments.get(k)]
                    if filters:
                        entry["filters_used"] = filters
                    class_dist, ns_dist = _extract_distributions(result_text)
                    if class_dist:
                        entry["class_distribution_top5"] = class_dist
                    if ns_dist:
                        entry["namespace_distribution_top5"] = ns_dist

                # Classify result size
                if result_count == 0:
                    entry["result_category"] = "empty"
                elif result_count > 50:
                    entry["result_category"] = "large"
                else:
                    entry["result_category"] = "normal"

                # Retry detection
                for prev in reversed(recent_calls):
                    if prev["tool_name"] == tool_name and prev["result_count"] == 0:
                        entry["retry_after_empty"] = True
                        break
                    if prev["tool_name"] == tool_name:
                        break

                recent_calls.append(
                    {
                        "tool_name": tool_name,
                        "result_count": result_count,
                    }
                )
                # Keep only last 20
                if len(recent_calls) > 20:
                    recent_calls = recent_calls[-20:]

                entries.append(entry)
                pending_call = None
                continue

            # Reset preceding_analysis on non-analysis, non-tool content
            if stype == "contentBlock":
                preceding_analysis = None

    return entries


def main():
    parser = argparse.ArgumentParser(
        description="Analyze MCP tool usage from LM Studio conversation files"
    )
    parser.add_argument("input_file", help="LM Studio conversation JSON file")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output JSONL file (default: stdout)",
    )
    parser.add_argument(
        "--append-to",
        default=None,
        help="Append entries to existing JSONL file (e.g., server-side log)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print summary statistics instead of JSONL output",
    )
    args = parser.parse_args()

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path) as f:
        data = json.load(f)

    entries = extract_tool_calls(data)

    if not entries:
        print("No MCP tool calls found in conversation.", file=sys.stderr)
        sys.exit(0)

    if args.summary:
        _print_summary(entries)
        return

    # Output JSONL
    if args.append_to:
        with open(args.append_to, "a") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
        print(f"Appended {len(entries)} entries to {args.append_to}", file=sys.stderr)
    elif args.output:
        with open(args.output, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
        print(f"Wrote {len(entries)} entries to {args.output}", file=sys.stderr)
    else:
        for entry in entries:
            print(json.dumps(entry))


def _print_summary(entries: List[Dict[str, Any]]) -> None:
    """Print summary statistics."""
    total = len(entries)
    empty = sum(1 for e in entries if e.get("result_category") == "empty")
    large = sum(1 for e in entries if e.get("result_category") == "large")
    retries = sum(1 for e in entries if e.get("retry_after_empty"))

    tool_counts: Counter = Counter()
    pattern_classes: Counter = Counter()
    for e in entries:
        tool_counts[e["tool_name"]] += 1
        pc = e.get("pattern_classification")
        if pc:
            pattern_classes[pc] += 1

    print(f"Total tool calls: {total}")
    print(f"Empty results: {empty} ({100 * empty / total:.1f}%)")
    print(f"Large results (>50): {large} ({100 * large / total:.1f}%)")
    print(f"Retries after empty: {retries}")
    print()
    print("Tool usage:")
    for tool, count in tool_counts.most_common():
        print(f"  {tool}: {count}")
    if pattern_classes:
        print()
        print("Pattern classifications (empty results only):")
        for cls, count in pattern_classes.most_common():
            print(f"  {cls}: {count}")


if __name__ == "__main__":
    main()
