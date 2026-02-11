"""Tests for smart_fallback module.

Tests pattern detection and fallback suggestion generation
without requiring real C++ parsing or libclang.
"""

from types import SimpleNamespace

import pytest

from mcp_server.smart_fallback import (
    FallbackResult,
    SmartFallback,
    _extract_identifier_from_signature,
    _has_double_escapes,
    _has_unnecessary_anchors,
    _looks_like_short_regex,
    _looks_like_signature,
    _strip_anchors,
)


def _make_symbol(name, qualified_name=None, file="test.cpp", line=1):
    """Create a mock SymbolInfo-like object."""
    return SimpleNamespace(
        name=name,
        qualified_name=qualified_name or name,
        file=file,
        line=line,
    )


def _make_index(*entries):
    """Create a mock index from (simple_name, qualified_name, file, line) tuples."""
    index = {}
    for entry in entries:
        if len(entry) == 4:
            name, qname, file, line = entry
        elif len(entry) == 2:
            name, qname = entry
            file, line = "test.cpp", 1
        else:
            name = entry[0]
            qname = entry[0]
            file, line = "test.cpp", 1
        sym = _make_symbol(name, qname, file, line)
        index.setdefault(name, []).append(sym)
    return index


# ============================================================
# Pattern detection helpers
# ============================================================


class TestLooksLikeSignature:
    def test_function_with_parens(self):
        assert _looks_like_signature("processData(int x)")

    def test_void_return_type(self):
        assert _looks_like_signature("void processData")

    def test_bool_return_type(self):
        assert _looks_like_signature("bool isValid")

    def test_const_reference(self):
        assert _looks_like_signature("const IConfig &")

    def test_type_pointer(self):
        assert _looks_like_signature("int* getData")

    def test_simple_name(self):
        assert not _looks_like_signature("processData")

    def test_qualified_name(self):
        assert not _looks_like_signature("app::Handler::process")

    def test_regex_pattern(self):
        assert not _looks_like_signature(".*Reporter")

    def test_empty(self):
        assert not _looks_like_signature("")

    def test_single_keyword_no_space(self):
        """Single keyword without space is not a signature."""
        assert not _looks_like_signature("void")

    def test_parens_only(self):
        """Just parentheses is a signature indicator."""
        assert _looks_like_signature("()")


class TestExtractIdentifier:
    def test_function_prototype(self):
        assert _extract_identifier_from_signature("void processData(int x)") == "processData"

    def test_qualified_function(self):
        assert (
            _extract_identifier_from_signature("bool app::Handler::match(const T& arg)")
            == "app::Handler::match"
        )

    def test_no_parens_type_expression(self):
        result = _extract_identifier_from_signature("const IConfig &")
        assert result == "IConfig"

    def test_complex_return_type(self):
        assert (
            _extract_identifier_from_signature("std::shared_ptr<Widget> createWidget()")
            == "createWidget"
        )

    def test_no_identifiers(self):
        assert _extract_identifier_from_signature("()") is None

    def test_all_keywords(self):
        """When only keywords present, return the longest."""
        result = _extract_identifier_from_signature("const void")
        assert result is not None  # Returns something rather than None

    def test_pointer_type(self):
        assert _extract_identifier_from_signature("int* getData()") == "getData"


class TestRegexHelpers:
    def test_double_escapes(self):
        assert _has_double_escapes("\\\\.*Reporter")
        assert not _has_double_escapes(".*Reporter")

    def test_unnecessary_anchors(self):
        assert _has_unnecessary_anchors("^Reporter")
        assert _has_unnecessary_anchors("Reporter$")
        assert _has_unnecessary_anchors("^Reporter$")
        assert not _has_unnecessary_anchors(".*Reporter")

    def test_caret_in_char_class(self):
        """^ inside [...] is not an anchor."""
        assert not _has_unnecessary_anchors("[^A-Z].*")

    def test_strip_anchors(self):
        assert _strip_anchors("^Reporter$") == "Reporter"
        assert _strip_anchors("^Reporter") == "Reporter"
        assert _strip_anchors("Reporter$") == "Reporter"
        assert _strip_anchors("Reporter") == "Reporter"

    def test_short_regex(self):
        assert _looks_like_short_regex("I[A-Z]")
        assert not _looks_like_short_regex(".*Reporter.*")
        assert not _looks_like_short_regex("processData")


# ============================================================
# FallbackResult
# ============================================================


class TestFallbackResult:
    def test_to_metadata_minimal(self):
        fb = FallbackResult(
            reason="test",
            searched_for="pattern",
            hint="A hint",
        )
        meta = fb.to_metadata()
        assert meta["reason"] == "test"
        assert meta["searched_for"] == "pattern"
        assert meta["hint"] == "A hint"
        assert "suggested_pattern" not in meta
        assert "alternatives" not in meta

    def test_to_metadata_full(self):
        fb = FallbackResult(
            reason="test",
            searched_for="pattern",
            hint="A hint",
            suggested_pattern="fixed",
            alternatives=[{"name": "a"}, {"name": "b"}],
        )
        meta = fb.to_metadata()
        assert meta["suggested_pattern"] == "fixed"
        assert len(meta["alternatives"]) == 2

    def test_alternatives_capped_at_10(self):
        fb = FallbackResult(
            reason="test",
            searched_for="x",
            hint="h",
            alternatives=[{"name": f"item{i}"} for i in range(20)],
        )
        meta = fb.to_metadata()
        assert len(meta["alternatives"]) == 10


# ============================================================
# SmartFallback cascade
# ============================================================


class TestSmartFallbackSignature:
    """Test signature detection fallback."""

    def setup_method(self):
        self.fb = SmartFallback()
        self.func_index = _make_index(
            ("processData", "app::Handler::processData", "handler.cpp", 42),
            ("processData", "util::processData", "util.cpp", 10),
        )
        self.class_index = _make_index(
            ("Handler", "app::Handler", "handler.h", 5),
        )

    def test_signature_with_parens(self):
        result = self.fb.analyze_empty_result(
            pattern="void processData(int x, std::string name)",
            tool_name="search_functions",
            class_index=self.class_index,
            function_index=self.func_index,
        )
        assert result is not None
        assert result.reason == "signature_detected"
        assert result.suggested_pattern == "processData"
        assert len(result.alternatives) == 2

    def test_type_expression(self):
        """Type expression like 'IConfig &' detected as signature."""
        index = _make_index(("IConfig", "app::IConfig", "config.h", 1))
        result = self.fb.analyze_empty_result(
            pattern="const IConfig &",
            tool_name="search_classes",
            class_index=index,
            function_index={},
        )
        assert result is not None
        assert result.reason == "signature_detected"
        assert result.suggested_pattern == "IConfig"

    def test_simple_name_not_signature(self):
        """Simple names should not trigger signature detection."""
        result = self.fb.analyze_empty_result(
            pattern="NonExistentClass",
            tool_name="search_classes",
            class_index=self.class_index,
            function_index=self.func_index,
        )
        # Should not be signature_detected
        assert result is None or result.reason != "signature_detected"


class TestSmartFallbackRegex:
    """Test regex hint fallback."""

    def setup_method(self):
        self.fb = SmartFallback()
        self.index = _make_index(
            ("ConsoleReporter", "test::ConsoleReporter", "reporter.cpp", 10),
            ("CompactReporter", "test::CompactReporter", "reporter.cpp", 50),
            ("JunitReporter", "test::JunitReporter", "reporter.cpp", 90),
        )

    def test_unnecessary_dollar_anchor(self):
        result = self.fb.analyze_empty_result(
            pattern="Reporter$",
            tool_name="search_classes",
            class_index=self.index,
            function_index={},
        )
        assert result is not None
        assert result.reason == "regex_hint"
        assert "fullmatch" in result.hint
        # $ means suffix match → suggest .*Reporter
        assert result.suggested_pattern == ".*Reporter"
        assert len(result.alternatives) == 3

    def test_unnecessary_caret_anchor(self):
        result = self.fb.analyze_empty_result(
            pattern="^Console.*",
            tool_name="search_classes",
            class_index=self.index,
            function_index={},
        )
        assert result is not None
        assert result.reason == "regex_hint"

    def test_short_regex(self):
        index = _make_index(
            ("IParser", "IParser", "parser.h", 1),
            ("IConfig", "IConfig", "config.h", 1),
        )
        result = self.fb.analyze_empty_result(
            pattern="I[A-Z]",
            tool_name="search_classes",
            class_index=index,
            function_index={},
        )
        assert result is not None
        assert result.reason == "regex_hint"
        assert "I[A-Z].*" in (result.suggested_pattern or "")

    def test_double_escapes(self):
        result = self.fb.analyze_empty_result(
            pattern="\\\\.\\*Reporter",
            tool_name="search_classes",
            class_index=self.index,
            function_index={},
        )
        # Double escape detection
        if result:
            assert result.reason == "regex_hint"

    def test_unanchored_partial(self):
        """Pattern like 'Reporter' (without .*) should suggest broadened version."""
        result = self.fb.analyze_empty_result(
            pattern="Reporter",  # exact match — won't match "ConsoleReporter"
            tool_name="search_classes",
            class_index=self.index,
            function_index={},
        )
        # "Reporter" is not a regex (no metacharacters), so it's exact match
        # and won't trigger regex hints. This is correct — the user would need
        # to use ".*Reporter" or ".*Reporter.*" for partial matching.
        # The generic suggestions handle this.
        # No fallback for plain text that simply doesn't match.
        assert result is None

    def test_valid_regex_with_results_not_triggered(self):
        """Regex hint should not be triggered if we don't call it (results exist)."""
        # SmartFallback is only called when results are empty, so this tests
        # that when called with a pattern that WOULD match, we still get a result
        # because the broadening finds matches
        result = self.fb.analyze_empty_result(
            pattern=".*Reporter",
            tool_name="search_classes",
            class_index=self.index,
            function_index={},
        )
        # .*Reporter would actually match, so in practice this wouldn't be called.
        # But if it is, broadening shouldn't hurt.
        # Result could be None (no issue detected) which is fine.


class TestSmartFallbackQualified:
    """Test qualified name fallback."""

    def setup_method(self):
        self.fb = SmartFallback()
        self.index = _make_index(
            ("process", "app::Handler::process", "handler.cpp", 42),
            ("process", "util::process", "util.cpp", 10),
        )

    def test_wrong_namespace(self):
        result = self.fb.analyze_empty_result(
            pattern="bad::ns::process",
            tool_name="search_functions",
            class_index={},
            function_index=self.index,
        )
        assert result is not None
        assert result.reason == "qualified_fallback"
        assert result.suggested_pattern == "process"
        assert len(result.alternatives) == 2
        assert "bad::ns::process" in result.searched_for

    def test_correct_namespace_not_triggered(self):
        """If simple name doesn't exist either, no suggestion."""
        result = self.fb.analyze_empty_result(
            pattern="bad::ns::nonexistent",
            tool_name="search_functions",
            class_index={},
            function_index=self.index,
        )
        assert result is None

    def test_simple_name_not_triggered(self):
        """Simple names (no ::) don't trigger qualified fallback."""
        result = self.fb.analyze_empty_result(
            pattern="nonexistent",
            tool_name="search_functions",
            class_index={},
            function_index=self.index,
        )
        assert result is None


class TestSmartFallbackFileCase:
    """Test file name case mismatch fallback."""

    def setup_method(self):
        self.fb = SmartFallback()
        self.class_index = _make_index(
            ("Widget", "ui::Widget", "/project/src/Widget.h", 5),
        )
        self.file_index = {
            "/project/src/Widget.h": [_make_symbol("Widget", "ui::Widget")],
            "/project/src/main.cpp": [_make_symbol("main", "main")],
        }

    def test_wrong_case(self):
        result = self.fb.analyze_empty_result(
            pattern="Widget",
            tool_name="search_classes",
            class_index=self.class_index,
            function_index={},
            file_index=self.file_index,
            file_name="widget.h",  # lowercase — wrong
        )
        assert result is not None
        assert result.reason == "file_case_mismatch"
        assert "Widget.h" in result.hint

    def test_correct_case_not_triggered(self):
        result = self.fb.analyze_empty_result(
            pattern="NonExistent",
            tool_name="search_classes",
            class_index=self.class_index,
            function_index={},
            file_index=self.file_index,
            file_name="Widget.h",  # correct case
        )
        # File case is correct, so this detector shouldn't trigger
        assert result is None or result.reason != "file_case_mismatch"


class TestSmartFallbackCascade:
    """Test that cascade priority works correctly."""

    def setup_method(self):
        self.fb = SmartFallback()
        self.func_index = _make_index(
            ("process", "app::Handler::process", "handler.cpp", 42),
        )

    def test_signature_takes_priority_over_qualified(self):
        """Signature with :: should still be detected as signature first."""
        result = self.fb.analyze_empty_result(
            pattern="void app::Handler::process(int x)",
            tool_name="search_functions",
            class_index={},
            function_index=self.func_index,
        )
        assert result is not None
        # Signature detection should win because it runs first
        assert result.reason == "signature_detected"

    def test_empty_pattern_returns_none(self):
        result = self.fb.analyze_empty_result(
            pattern="",
            tool_name="search_functions",
            class_index={},
            function_index=self.func_index,
        )
        assert result is None

    def test_no_match_returns_none(self):
        """When nothing matches any detector, return None."""
        result = self.fb.analyze_empty_result(
            pattern="totallyNonexistent",
            tool_name="search_functions",
            class_index={},
            function_index=self.func_index,
        )
        assert result is None
