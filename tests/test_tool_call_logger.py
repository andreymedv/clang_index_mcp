"""Tests for tool_call_logger module.

Tests telemetry logging including enable/disable, pattern classification,
empty/large result enrichment, retry detection, file rotation, and privacy.
"""

import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mcp_server.tool_call_logger import ToolCallLogger, _classify_pattern


@pytest.fixture
def cache_dir(tmp_path):
    """Provide a temporary cache directory."""
    d = tmp_path / "cache"
    d.mkdir()
    return d


@pytest.fixture
def session_id():
    return "test-session-123"


@pytest.fixture
def enabled_logger(cache_dir, session_id):
    """Logger with MCP_TOOL_LOGGING=1."""
    with patch.dict(os.environ, {"MCP_TOOL_LOGGING": "1"}):
        return ToolCallLogger(cache_dir, session_id)


@pytest.fixture
def disabled_logger(cache_dir, session_id):
    """Logger with MCP_TOOL_LOGGING unset."""
    with patch.dict(os.environ, {}, clear=True):
        env = os.environ.copy()
        env.pop("MCP_TOOL_LOGGING", None)
        with patch.dict(os.environ, env, clear=True):
            return ToolCallLogger(cache_dir, session_id)


def _make_analyzer():
    """Create a mock analyzer with class_index and function_index."""
    analyzer = SimpleNamespace()
    analyzer.class_index = {
        "MyClass": [
            SimpleNamespace(name="MyClass", qualified_name="ns::MyClass"),
        ],
        "Widget": [
            SimpleNamespace(name="Widget", qualified_name="ui::Widget"),
            SimpleNamespace(name="Widget", qualified_name="test::Widget"),
        ],
    }
    analyzer.function_index = {
        "processData": [
            SimpleNamespace(name="processData", qualified_name="ns::processData"),
        ],
    }
    return analyzer


def _read_log(logger):
    """Read all JSONL entries from the log file."""
    if not logger.log_path.exists():
        return []
    entries = []
    with open(logger.log_path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


class TestEnableDisable:
    def test_disabled_by_default(self, cache_dir, session_id):
        """No file created when env var unset."""
        with patch.dict(os.environ, {}, clear=True):
            env = os.environ.copy()
            env.pop("MCP_TOOL_LOGGING", None)
            with patch.dict(os.environ, env, clear=True):
                logger = ToolCallLogger(cache_dir, session_id)
                logger.log_tool_call("search_classes", {"pattern": "Foo"}, 5, "[]")
                assert not logger.log_path.exists()

    def test_enabled_via_env_var(self, cache_dir, session_id):
        """MCP_TOOL_LOGGING=1 enables logging."""
        with patch.dict(os.environ, {"MCP_TOOL_LOGGING": "1"}):
            logger = ToolCallLogger(cache_dir, session_id)
            logger.log_tool_call("search_classes", {"pattern": "Foo"}, 5, "[]")
            assert logger.log_path.exists()
            entries = _read_log(logger)
            assert len(entries) == 1


class TestBasicLogging:
    def test_log_basic_call(self, enabled_logger):
        """JSONL entry has expected fields."""
        enabled_logger.log_tool_call(
            "search_classes", {"pattern": "Foo"}, 3, '[{"name": "Foo"}]'
        )
        entries = _read_log(enabled_logger)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["tool_name"] == "search_classes"
        assert entry["arguments"] == {"pattern": "Foo"}
        assert entry["result_count"] == 3
        assert entry["session_id"] == "test-session-123"
        assert "timestamp" in entry
        assert "timestamp_readable" in entry

    def test_multiple_calls(self, enabled_logger):
        """Multiple calls append to same file."""
        enabled_logger.log_tool_call("search_classes", {"pattern": "A"}, 1, "[]")
        enabled_logger.log_tool_call("search_functions", {"pattern": "B"}, 2, "[]")
        entries = _read_log(enabled_logger)
        assert len(entries) == 2
        assert entries[0]["tool_name"] == "search_classes"
        assert entries[1]["tool_name"] == "search_functions"


class TestPatternClassification:
    def test_signature_like(self):
        assert _classify_pattern("void processData(int x)") == "signature_like"
        assert _classify_pattern("bool isReady()") == "signature_like"

    def test_prototype_like(self):
        # "int main(" has a paren, so _looks_like_signature catches it first.
        # signature_like is a superset of prototype_like in practice.
        # Test a pattern that matches _PROTOTYPE_PATTERN but without parens
        # is not possible since _PROTOTYPE_PATTERN requires '('. So we verify
        # that "int main(" is classified as signature_like (which includes prototypes).
        assert _classify_pattern("int main(") == "signature_like"

    def test_qualified_name(self):
        assert _classify_pattern("ns::MyClass") == "qualified_name"
        assert _classify_pattern("a::b::c") == "qualified_name"

    def test_regex(self):
        assert _classify_pattern("My.*Class") == "regex"
        assert _classify_pattern("Foo|Bar") == "regex"
        assert _classify_pattern("Widget[0-9]") == "regex"

    def test_plain_name(self):
        assert _classify_pattern("MyClass") == "plain_name"
        assert _classify_pattern("processData") == "plain_name"


class TestEmptyResultEnrichment:
    def test_enrichment_on_empty_search(self, enabled_logger):
        """Empty result on search tool triggers pattern classification."""
        enabled_logger.log_tool_call(
            "search_classes", {"pattern": "ns::MyClass"}, 0, "[]"
        )
        entries = _read_log(enabled_logger)
        entry = entries[0]
        assert entry["pattern_classification"] == "qualified_name"
        assert "pattern_features" in entry
        assert entry["pattern_features"]["has_colons"] is True
        assert entry["pattern_features"]["has_parens"] is False

    def test_no_enrichment_on_nonempty(self, enabled_logger):
        """Non-empty results don't get pattern classification."""
        enabled_logger.log_tool_call(
            "search_classes", {"pattern": "ns::MyClass"}, 5, "[]"
        )
        entries = _read_log(enabled_logger)
        assert "pattern_classification" not in entries[0]

    def test_no_enrichment_on_non_search_tool(self, enabled_logger):
        """Non-search tools don't get enrichment even on empty."""
        enabled_logger.log_tool_call(
            "get_class_info", {"class_name": "Foo"}, 0, "null"
        )
        entries = _read_log(enabled_logger)
        assert "pattern_classification" not in entries[0]

    def test_fallback_counts_with_analyzer(self, enabled_logger):
        """Fallback counts populated when analyzer is provided."""
        analyzer = _make_analyzer()
        enabled_logger.log_tool_call(
            "search_classes", {"pattern": "ns::MyClass"}, 0, "[]", analyzer=analyzer
        )
        entries = _read_log(enabled_logger)
        entry = entries[0]
        assert entry["simple_name_fallback_count"] == 1
        assert len(entry["simple_name_fallback_top3"]) == 1
        assert entry["simple_name_fallback_top3"][0] == "ns::MyClass"

    def test_case_insensitive_fallback(self, enabled_logger):
        """Case-insensitive fallback counts work."""
        analyzer = _make_analyzer()
        enabled_logger.log_tool_call(
            "search_classes", {"pattern": "myclass"}, 0, "[]", analyzer=analyzer
        )
        entries = _read_log(enabled_logger)
        entry = entries[0]
        # "myclass" won't match "MyClass" in direct lookup but will case-insensitive
        assert entry["simple_name_fallback_count"] == 0  # exact key miss
        assert entry["case_insensitive_fallback_count"] == 1  # case-insensitive hit

    def test_pattern_features(self, enabled_logger):
        """Pattern features extracted correctly."""
        enabled_logger.log_tool_call(
            "search_functions", {"pattern": "void processData(int x)"}, 0, "[]"
        )
        entries = _read_log(enabled_logger)
        features = entries[0]["pattern_features"]
        assert features["has_parens"] is True
        assert features["has_spaces"] is True
        assert features["has_type_keywords"] is True


class TestLargeResultEnrichment:
    def test_distribution_fields(self, enabled_logger):
        """Large results get class/namespace distribution."""
        items = [
            {"name": f"func{i}", "class_name": f"Class{i % 3}", "namespace": f"ns{i % 2}"}
            for i in range(60)
        ]
        result_text = json.dumps(items)
        enabled_logger.log_tool_call(
            "search_functions", {"pattern": ".*"}, 60, result_text
        )
        entries = _read_log(enabled_logger)
        entry = entries[0]
        assert "class_distribution_top5" in entry
        assert "namespace_distribution_top5" in entry
        assert len(entry["class_distribution_top5"]) <= 5

    def test_filters_used(self, enabled_logger):
        """Filters used are extracted from arguments."""
        items = [{"name": f"f{i}"} for i in range(51)]
        enabled_logger.log_tool_call(
            "search_functions",
            {"pattern": ".*", "class_name": "Foo", "namespace": "bar"},
            51,
            json.dumps(items),
        )
        entries = _read_log(enabled_logger)
        filters = entries[0]["filters_used"]
        assert "class_name" in filters
        assert "namespace" in filters

    def test_no_enrichment_on_small_result(self, enabled_logger):
        """Results <= 50 don't get distribution analysis."""
        items = [{"name": f"f{i}"} for i in range(50)]
        enabled_logger.log_tool_call(
            "search_functions", {"pattern": ".*"}, 50, json.dumps(items)
        )
        entries = _read_log(enabled_logger)
        assert "class_distribution_top5" not in entries[0]


class TestRetryDetection:
    def test_retry_after_empty(self, enabled_logger):
        """Second call to same tool after empty result flagged as retry."""
        enabled_logger.log_tool_call("search_classes", {"pattern": "A"}, 0, "[]")
        enabled_logger.log_tool_call("search_classes", {"pattern": "A.*"}, 3, "[]")
        entries = _read_log(enabled_logger)
        assert "retry_after_empty" not in entries[0]
        assert entries[1].get("retry_after_empty") is True

    def test_no_retry_after_nonempty(self, enabled_logger):
        """Call after non-empty result is not a retry."""
        enabled_logger.log_tool_call("search_classes", {"pattern": "A"}, 5, "[]")
        enabled_logger.log_tool_call("search_classes", {"pattern": "B"}, 3, "[]")
        entries = _read_log(enabled_logger)
        assert "retry_after_empty" not in entries[1]

    def test_no_retry_different_tool(self, enabled_logger):
        """Different tool after empty is not a retry."""
        enabled_logger.log_tool_call("search_classes", {"pattern": "A"}, 0, "[]")
        enabled_logger.log_tool_call("search_functions", {"pattern": "A"}, 3, "[]")
        entries = _read_log(enabled_logger)
        assert "retry_after_empty" not in entries[1]


class TestFileRotation:
    def test_rotation_on_large_file(self, enabled_logger):
        """File rotated when exceeding 10MB."""
        # Write a large log file to simulate exceeding limit
        enabled_logger.cache_dir.mkdir(parents=True, exist_ok=True)
        with open(enabled_logger.log_path, "w") as f:
            # Write >10MB of data
            line = json.dumps({"tool_name": "x", "data": "y" * 1000}) + "\n"
            lines_needed = (10 * 1024 * 1024) // len(line) + 1
            for _ in range(lines_needed):
                f.write(line)

        assert enabled_logger.log_path.stat().st_size > 10 * 1024 * 1024

        # Next log call should trigger rotation
        enabled_logger.log_tool_call("search_classes", {"pattern": "X"}, 1, "[]")

        rotated = enabled_logger.log_path.with_suffix(".jsonl.1")
        assert rotated.exists()
        # New log file should be small (just the one new entry)
        assert enabled_logger.log_path.stat().st_size < 1024


class TestPrivacy:
    def test_result_text_not_in_log(self, enabled_logger):
        """Result text content is NOT stored in the log file."""
        secret_text = "SENSITIVE_RESULT_DATA_12345"
        enabled_logger.log_tool_call(
            "search_classes", {"pattern": "Foo"}, 3, secret_text
        )
        log_content = enabled_logger.log_path.read_text()
        assert secret_text not in log_content

    def test_result_text_parsed_for_distribution_only(self, enabled_logger):
        """Large result text is parsed for distribution but not stored raw."""
        items = [{"name": f"f{i}", "class_name": "MySecret"} for i in range(60)]
        result_text = json.dumps(items)
        enabled_logger.log_tool_call(
            "search_functions", {"pattern": ".*"}, 60, result_text
        )
        log_content = enabled_logger.log_path.read_text()
        entry = json.loads(log_content.strip())
        # Distribution key is present but raw result_text is not
        assert "class_distribution_top5" in entry
        # The raw JSON array should not appear in the log
        assert result_text not in log_content
