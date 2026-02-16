"""
Tool call telemetry logger for MCP server.

Logs structured JSONL data about how LLMs use MCP tools, with enrichment
for empty results (pattern classification, fallback counts), large results
(distribution analysis), and retry detection. Controlled by MCP_TOOL_LOGGING=1.

Design: Append-only JSONL with 10MB rotation. Never blocks tool execution.
"""

import json
import os
import re
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any, Dict, List

from mcp_server.smart_fallback import (
    _PROTOTYPE_PATTERN,
    _looks_like_signature,
)

# Regex metacharacters that distinguish regex patterns from plain names
_REGEX_META = re.compile(r"[.*+?\[\]{}()|\\^$]")

# Tools that accept a "pattern" argument for symbol search
_SEARCH_TOOLS = {
    "search_classes",
    "search_functions",
    "search_symbols",
    "find_in_file",
}

# Max size before log rotation (10 MB)
_MAX_LOG_SIZE = 10 * 1024 * 1024


def _classify_pattern(pattern: str) -> str:
    """Classify a search pattern into one of 5 categories.

    Classification order (first match wins):
    1. signature_like — looks like a C++ function signature
    2. prototype_like — matches "type name(" prototype pattern
    3. qualified_name — has :: but no regex metacharacters
    4. regex — has regex metacharacters
    5. plain_name — simple identifier
    """
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
    """Extract boolean features from a pattern for analysis."""
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


class ToolCallLogger:
    """JSONL logger for MCP tool call telemetry.

    Enabled only when MCP_TOOL_LOGGING=1. Logs to cache_dir/tool_call_log.jsonl.
    """

    def __init__(self, cache_dir: Path, session_id: str):
        self.enabled = os.environ.get("MCP_TOOL_LOGGING", "0") == "1"
        self.cache_dir = cache_dir
        self.session_id = session_id
        self.log_path = cache_dir / "tool_call_log.jsonl"
        self._recent_calls: deque = deque(maxlen=20)

    def log_tool_call(
        self,
        name: str,
        arguments: Dict[str, Any],
        result_count: int,
        result_text: str,
        analyzer: Any = None,
    ) -> None:
        """Log a tool call with enrichment. Never raises."""
        if not self.enabled:
            return
        try:
            self._log_tool_call_inner(name, arguments, result_count, result_text, analyzer)
        except Exception:
            pass  # Logging must never break tool calls

    def _log_tool_call_inner(
        self,
        name: str,
        arguments: Dict[str, Any],
        result_count: int,
        result_text: str,
        analyzer: Any,
    ) -> None:
        now = time.time()
        entry: Dict[str, Any] = {
            "tool_name": name,
            "arguments": arguments,
            "result_count": result_count,
            "timestamp": now,
            "timestamp_readable": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "session_id": self.session_id,
        }

        pattern = arguments.get("pattern", "")

        # Empty-result enrichment (search tools only)
        if result_count == 0 and name in _SEARCH_TOOLS and pattern:
            entry["pattern_classification"] = _classify_pattern(pattern)
            entry["pattern_features"] = _extract_pattern_features(pattern)

            # Fallback counts using analyzer indexes
            if analyzer is not None:
                simple_name = pattern.split("::")[-1]
                # Strip regex metacharacters for index lookup
                clean_name = re.sub(r"[.*+?\[\]{}()|\\^$]", "", simple_name)
                if clean_name:
                    self._add_fallback_counts(entry, analyzer, clean_name)

        # Large-result enrichment
        if result_count > 50:
            entry["filters_used"] = self._extract_filters(arguments)
            self._add_distribution(entry, result_text)

        # Retry detection
        is_retry = self._detect_retry(name, result_count, now)
        if is_retry:
            entry["retry_after_empty"] = True

        # Track this call for future retry detection
        self._recent_calls.append(
            {
                "tool_name": name,
                "result_count": result_count,
                "timestamp": now,
            }
        )

        # Rotate if needed, then write
        self._maybe_rotate()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _add_fallback_counts(self, entry: Dict[str, Any], analyzer: Any, clean_name: str) -> None:
        """Add simple_name_fallback and case_insensitive_fallback counts."""
        # Simple name lookup in class_index and function_index
        class_hits = analyzer.class_index.get(clean_name, [])
        func_hits = analyzer.function_index.get(clean_name, [])
        all_hits = list(class_hits) + list(func_hits)
        entry["simple_name_fallback_count"] = len(all_hits)
        entry["simple_name_fallback_top3"] = [
            getattr(h, "qualified_name", getattr(h, "name", str(h))) for h in all_hits[:3]
        ]

        # Case-insensitive scan
        lower_name = clean_name.lower()
        ci_count = 0
        for key in analyzer.class_index:
            if key.lower() == lower_name:
                ci_count += len(analyzer.class_index[key])
        for key in analyzer.function_index:
            if key.lower() == lower_name:
                ci_count += len(analyzer.function_index[key])
        entry["case_insensitive_fallback_count"] = ci_count

    def _extract_filters(self, arguments: Dict[str, Any]) -> List[str]:
        """Return list of filter arguments that were provided."""
        filter_keys = [
            "class_name",
            "namespace",
            "file_name",
            "signature_pattern",
            "file_path",
            "symbol_types",
        ]
        return [k for k in filter_keys if arguments.get(k)]

    def _add_distribution(self, entry: Dict[str, Any], result_text: str) -> None:
        """Add class/namespace distribution from result_text JSON."""
        try:
            parsed = json.loads(result_text)
            # Handle EnhancedQueryResult wrapper
            items = parsed.get("results", parsed) if isinstance(parsed, dict) else parsed
            if not isinstance(items, list):
                return

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

            if classes:
                entry["class_distribution_top5"] = dict(classes.most_common(5))
            if namespaces:
                entry["namespace_distribution_top5"] = dict(namespaces.most_common(5))
        except (json.JSONDecodeError, TypeError):
            pass

    def _detect_retry(self, name: str, result_count: int, now: float) -> bool:
        """Check if this call is a retry after a recent empty result for same tool."""
        for prev in reversed(self._recent_calls):
            # Only look at calls within last 60 seconds
            if now - prev["timestamp"] > 60:
                break
            if prev["tool_name"] == name and prev["result_count"] == 0:
                return True
            # Stop at first match of same tool (whether empty or not)
            if prev["tool_name"] == name:
                break
        return False

    def _maybe_rotate(self) -> None:
        """Rotate log file if it exceeds 10MB."""
        try:
            if self.log_path.exists() and self.log_path.stat().st_size > _MAX_LOG_SIZE:
                rotated = self.log_path.with_suffix(".jsonl.1")
                # Overwrite old rotation
                if rotated.exists():
                    rotated.unlink()
                self.log_path.rename(rotated)
        except OSError:
            pass
