"""
Tests for Qualified Names Phase 2 - Pattern Matching and Search.

This file tests the qualified name pattern matching capabilities added in Phase 2:
- Pattern type detection (_detect_pattern_type)
- Component-based suffix matching (matches_qualified_pattern)
- SQL query optimization (build_search_query)
- Search tool integration (search_classes, search_functions, etc.)
"""

import pytest
from mcp_server.search_engine import SearchEngine


class TestPatternTypeDetection:
    """Test T2.1.2: Pattern type detection helper."""

    def test_exact_pattern_leading_colons(self):
        """Leading :: should be detected as exact match."""
        assert SearchEngine._detect_pattern_type("::View") == "exact"
        assert SearchEngine._detect_pattern_type("::GlobalClass") == "exact"
        assert SearchEngine._detect_pattern_type("::std::string") == "exact"

    def test_unqualified_pattern_no_colons(self):
        """No :: should be detected as unqualified match."""
        assert SearchEngine._detect_pattern_type("View") == "unqualified"
        assert SearchEngine._detect_pattern_type("string") == "unqualified"
        assert SearchEngine._detect_pattern_type("MyClass") == "unqualified"

    def test_suffix_pattern_with_colons(self):
        """:: without leading :: should be detected as suffix match."""
        assert SearchEngine._detect_pattern_type("ui::View") == "suffix"
        assert SearchEngine._detect_pattern_type("app::core::Config") == "suffix"
        assert SearchEngine._detect_pattern_type("ns1::ns2::Class") == "suffix"

    def test_regex_pattern_with_metacharacters(self):
        """Regex metacharacters should be detected as regex."""
        assert SearchEngine._detect_pattern_type("app::.*::View") == "regex"
        assert SearchEngine._detect_pattern_type(".*View.*") == "regex"
        assert SearchEngine._detect_pattern_type("View.*") == "regex"
        assert SearchEngine._detect_pattern_type("View+") == "regex"
        assert SearchEngine._detect_pattern_type("View?") == "regex"
        assert SearchEngine._detect_pattern_type("View[A-Z]") == "regex"
        assert SearchEngine._detect_pattern_type("(View|Model)") == "regex"
        assert SearchEngine._detect_pattern_type("^View$") == "regex"
        assert SearchEngine._detect_pattern_type("View\\w+") == "regex"

    def test_empty_pattern(self):
        """Empty pattern should be unqualified."""
        assert SearchEngine._detect_pattern_type("") == "unqualified"

    def test_regex_takes_precedence_over_suffix(self):
        """Regex detection should take precedence over suffix."""
        # These have :: but also have regex chars → should be "regex" not "suffix"
        assert SearchEngine._detect_pattern_type("ns::View.*") == "regex"
        assert SearchEngine._detect_pattern_type("ns::(View|Model)") == "regex"
        assert SearchEngine._detect_pattern_type("ns::.*") == "regex"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
