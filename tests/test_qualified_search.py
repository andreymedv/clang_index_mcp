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


class TestQualifiedPatternMatching:
    """Test T2.1.1: Component-based pattern matching."""

    def test_exact_match_with_leading_colons(self):
        """Leading :: should match only global namespace symbols."""
        # Exact match: must be in global namespace
        assert SearchEngine.matches_qualified_pattern("View", "::View") is True
        assert SearchEngine.matches_qualified_pattern("GlobalClass", "::GlobalClass") is True

        # Should NOT match namespaced symbols
        assert SearchEngine.matches_qualified_pattern("app::View", "::View") is False
        assert SearchEngine.matches_qualified_pattern("ns1::ns2::View", "::View") is False

    def test_unqualified_pattern_matches_any_namespace(self):
        """No :: in pattern should match unqualified name in any namespace."""
        # Should match in any namespace
        assert SearchEngine.matches_qualified_pattern("View", "View") is True
        assert SearchEngine.matches_qualified_pattern("app::View", "View") is True
        assert SearchEngine.matches_qualified_pattern("app::ui::View", "View") is True
        assert SearchEngine.matches_qualified_pattern("ns1::ns2::ns3::View", "View") is True

        # Should NOT match different names
        assert SearchEngine.matches_qualified_pattern("ViewManager", "View") is False
        assert SearchEngine.matches_qualified_pattern("app::ListView", "View") is False

    def test_suffix_match_component_boundaries(self):
        """Suffix patterns should respect component boundaries."""
        # Should match: suffix with correct boundaries
        assert SearchEngine.matches_qualified_pattern("app::ui::View", "ui::View") is True
        assert SearchEngine.matches_qualified_pattern("legacy::ui::View", "ui::View") is True
        assert SearchEngine.matches_qualified_pattern("app::core::ui::View", "ui::View") is True
        assert SearchEngine.matches_qualified_pattern("app::core::ui::View", "core::ui::View") is True

        # Should NOT match: wrong component boundaries
        assert SearchEngine.matches_qualified_pattern("myui::View", "ui::View") is False
        assert SearchEngine.matches_qualified_pattern("app::myui::View", "ui::View") is False

        # Should NOT match: pattern longer than name
        assert SearchEngine.matches_qualified_pattern("View", "app::View") is False
        assert SearchEngine.matches_qualified_pattern("ui::View", "app::ui::View") is False

    def test_suffix_match_case_insensitive(self):
        """Suffix matching should be case-insensitive."""
        assert SearchEngine.matches_qualified_pattern("App::UI::View", "ui::view") is True
        assert SearchEngine.matches_qualified_pattern("app::ui::view", "UI::VIEW") is True
        assert SearchEngine.matches_qualified_pattern("APP::ui::VieW", "Ui::ViEw") is True

    def test_regex_patterns(self):
        """Regex patterns should work with fullmatch semantics."""
        # Regex with :: separator
        assert SearchEngine.matches_qualified_pattern("app::core::View", "app::.*::View") is True
        assert SearchEngine.matches_qualified_pattern("app::ui::View", "app::.*::View") is True
        assert SearchEngine.matches_qualified_pattern("app::View", "app::.*::View") is False  # no middle component

        # Regex without :: (matches anywhere)
        assert SearchEngine.matches_qualified_pattern("View", ".*View.*") is True
        assert SearchEngine.matches_qualified_pattern("ViewManager", ".*View.*") is True
        assert SearchEngine.matches_qualified_pattern("app::View", ".*View.*") is True

        # Regex anchored patterns
        assert SearchEngine.matches_qualified_pattern("app::View", "app::View.*") is True
        assert SearchEngine.matches_qualified_pattern("app::ViewManager", "app::View.*") is True
        assert SearchEngine.matches_qualified_pattern("legacy::View", "app::View.*") is False

    def test_regex_invalid_patterns(self):
        """Invalid regex patterns should return False, not raise."""
        # Invalid regex should not raise, just return False
        assert SearchEngine.matches_qualified_pattern("app::View", "[invalid(regex") is False
        assert SearchEngine.matches_qualified_pattern("app::View", "(?P<invalid") is False

    def test_empty_pattern_matches_all(self):
        """Empty pattern should match everything."""
        assert SearchEngine.matches_qualified_pattern("View", "") is True
        assert SearchEngine.matches_qualified_pattern("app::View", "") is True
        assert SearchEngine.matches_qualified_pattern("ns1::ns2::View", "") is True

    def test_multi_component_suffix_patterns(self):
        """Multi-component suffix patterns should work."""
        # 3-component pattern
        assert SearchEngine.matches_qualified_pattern("app::core::ui::View", "core::ui::View") is True
        assert SearchEngine.matches_qualified_pattern("legacy::core::ui::View", "core::ui::View") is True
        assert SearchEngine.matches_qualified_pattern("app::ui::View", "core::ui::View") is False

        # 2-component pattern
        assert SearchEngine.matches_qualified_pattern("app::ui::View", "ui::View") is True
        assert SearchEngine.matches_qualified_pattern("app::View", "ui::View") is False

    def test_edge_cases(self):
        """Test edge cases and boundary conditions."""
        # Single component name with single component pattern
        assert SearchEngine.matches_qualified_pattern("View", "View") is True

        # Exact same qualified name
        assert SearchEngine.matches_qualified_pattern("app::ui::View", "app::ui::View") is True

        # Pattern equals qualified name (unqualified mode)
        assert SearchEngine.matches_qualified_pattern("View", "View") is True

        # Empty qualified name (shouldn't happen in practice, but handle gracefully)
        assert SearchEngine.matches_qualified_pattern("", "") is True
        assert SearchEngine.matches_qualified_pattern("", "View") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
