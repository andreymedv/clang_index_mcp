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


class TestFindInFileQualifiedPatterns:
    """Test T2.2.4: find_in_file() with qualified pattern matching."""

    def test_find_in_file_delegates_to_search_methods(self):
        """find_in_file() should delegate to search_classes() and search_functions()."""
        # This test verifies that find_in_file() inherits qualified pattern matching
        # by delegating to the already-updated search methods.
        # The actual integration testing happens in integration tests.
        from mcp_server.cpp_analyzer import CppAnalyzer
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create minimal test project
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace app {
    namespace ui {
        class View {};
    }
}

class View {};
void testFunc() {}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Test unqualified pattern
            response = analyzer.find_in_file(str(test_file), "View")
            results = response["results"]
            assert len(results) >= 1
            names = [r["name"] for r in results]
            assert "View" in names

            # Test empty pattern (all symbols)
            all_response = analyzer.find_in_file(str(test_file), "")
            all_results = all_response["results"]
            assert len(all_results) >= 2  # At least 2 View classes + testFunc

            # Verify results include qualified_name field
            for result in all_results:
                assert "qualified_name" in result
                assert "namespace" in result

    def test_find_in_file_qualified_patterns_integration(self):
        """Test find_in_file() with various qualified patterns."""
        from mcp_server.cpp_analyzer import CppAnalyzer
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test project with namespaced classes
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace app {
    namespace ui {
        class View {};
        class ListView {};
    }
}

namespace legacy {
    namespace ui {
        class View {};
    }
}

class View {};
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Test unqualified: should find all 3 View classes
            unqualified_response = analyzer.find_in_file(str(test_file), "View")
            unqualified_results = unqualified_response["results"]
            view_results = [r for r in unqualified_results if r["name"] == "View"]
            assert len(view_results) == 3

            # Test qualified suffix: ui::View should find 2 (app::ui::View and legacy::ui::View)
            suffix_response = analyzer.find_in_file(str(test_file), "ui::View")
            suffix_results = suffix_response["results"]
            assert len(suffix_results) == 2
            qualified_names = {r["qualified_name"] for r in suffix_results}
            assert "app::ui::View" in qualified_names
            assert "legacy::ui::View" in qualified_names

            # Test exact: ::View should find only global View
            exact_response = analyzer.find_in_file(str(test_file), "::View")
            exact_results = exact_response["results"]
            assert len(exact_results) == 1
            assert exact_results[0]["qualified_name"] == "View"
            assert exact_results[0]["namespace"] == ""

            # Test regex: .*ListView should find ListView
            regex_response = analyzer.find_in_file(str(test_file), ".*ListView")
            regex_results = regex_response["results"]
            assert len(regex_results) >= 1
            assert any(r["name"] == "ListView" for r in regex_results)


class TestBackwardCompatibility:
    """Test T2.3.1: Backward compatibility with unqualified patterns."""

    def test_unqualified_pattern_still_works(self):
        """Old-style unqualified search must work."""
        from mcp_server.cpp_analyzer import CppAnalyzer
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace ns1 {
    class View {};
}

namespace ns2 {
    class View {};
}

class View {};
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Old-style unqualified search should find all Views
            results = analyzer.search_classes("View")
            assert len(results) >= 3  # At least 3 View classes

    def test_qualified_pattern_narrows_results(self):
        """Qualified pattern should reduce ambiguity."""
        from mcp_server.cpp_analyzer import CppAnalyzer
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace ns1 {
    class View {};
}

namespace ns2 {
    class View {};
}

class View {};
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Unqualified search finds all
            all_views = analyzer.search_classes("View")
            # Qualified search narrows down
            ns1_views = analyzer.search_classes("ns1::View")

            assert len(ns1_views) <= len(all_views)
            assert len(ns1_views) >= 1
            # Verify it's the right one
            assert any(r["qualified_name"] == "ns1::View" for r in ns1_views)

    def test_leading_colon_exact_match(self):
        """Leading :: means exact match in global namespace."""
        from mcp_server.cpp_analyzer import CppAnalyzer
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace ns1 {
    class GlobalClass {};
}

class GlobalClass {};
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Leading :: should find only global namespace
            results = analyzer.search_classes("::GlobalClass")
            assert len(results) == 1
            assert results[0]["namespace"] == ""
            assert results[0]["qualified_name"] == "GlobalClass"

    def test_regex_patterns(self):
        """Regex patterns work with qualified names."""
        from mcp_server.cpp_analyzer import CppAnalyzer
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace app {
    namespace core {
        class Config {};
    }
    namespace ui {
        class Config {};
    }
}

class Config {};
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Regex pattern
            results = analyzer.search_classes("app::.*::Config")

            # Should find app::core::Config and app::ui::Config, but not global Config
            assert len(results) == 2
            for r in results:
                assert r["qualified_name"].startswith("app::")
                assert r["qualified_name"].endswith("::Config")

    def test_case_insensitive_backward_compatibility(self):
        """Case-insensitive matching works for all pattern types."""
        from mcp_server.cpp_analyzer import CppAnalyzer
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace MyApp {
    class MyClass {};
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Unqualified: case-insensitive
            assert len(analyzer.search_classes("myclass")) >= 1
            assert len(analyzer.search_classes("MYCLASS")) >= 1

            # Qualified: case-insensitive
            assert len(analyzer.search_classes("myapp::myclass")) >= 1
            assert len(analyzer.search_classes("MYAPP::MYCLASS")) >= 1

            # Regex: case-insensitive
            assert len(analyzer.search_classes("myapp::.*")) >= 1
            assert len(analyzer.search_classes("MYAPP::.*")) >= 1


class TestPartiallyQualifiedNameLookups:
    """Test partially qualified name support in get_class_info and related tools.

    Issue: get_class_info was using exact string matching for qualified names,
    which caused "builders::Presenter" to fail when the actual
    qualified name was "outer::builders::Presenter".

    The fix uses matches_qualified_pattern() for suffix-based matching.
    """

    def test_get_class_info_partially_qualified(self):
        """get_class_info should find class with partially qualified name."""
        from mcp_server.cpp_analyzer import CppAnalyzer
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace outer {
    namespace builders {
        class Presenter {
        public:
            void build();
        };
    }
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Fully qualified should work
            result = analyzer.get_class_info("outer::builders::Presenter")
            assert result is not None
            assert result["name"] == "Presenter"
            assert result["qualified_name"] == "outer::builders::Presenter"

            # Partially qualified (missing outer::) should also work
            result = analyzer.get_class_info("builders::Presenter")
            assert result is not None
            assert result["name"] == "Presenter"
            assert result["qualified_name"] == "outer::builders::Presenter"

            # Simple name should work
            result = analyzer.get_class_info("Presenter")
            assert result is not None
            assert result["name"] == "Presenter"

    def test_get_class_info_disambiguates_correctly(self):
        """Partially qualified name should find the right class when there are multiple."""
        from mcp_server.cpp_analyzer import CppAnalyzer
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace app {
    namespace ui {
        class View {
        public:
            void render();
        };
    }
}

namespace legacy {
    namespace ui {
        class View {
        public:
            void display();
        };
    }
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # "app::ui::View" should find the app version
            result = analyzer.get_class_info("app::ui::View")
            assert result is not None
            assert result["qualified_name"] == "app::ui::View"
            assert any(m["name"] == "render" for m in result["methods"])

            # "legacy::ui::View" should find the legacy version
            result = analyzer.get_class_info("legacy::ui::View")
            assert result is not None
            assert result["qualified_name"] == "legacy::ui::View"
            assert any(m["name"] == "display" for m in result["methods"])

            # "ui::View" (partial) should find one of them (first match)
            result = analyzer.get_class_info("ui::View")
            assert result is not None
            assert result["name"] == "View"
            assert "ui::View" in result["qualified_name"]

    def test_get_function_signature_partially_qualified(self):
        """get_function_signature should work with partially qualified names."""
        from mcp_server.cpp_analyzer import CppAnalyzer
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace outer {
    namespace inner {
        void myFunction(int x) {}
    }
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Fully qualified
            sigs = analyzer.get_function_signature("outer::inner::myFunction")
            assert len(sigs) >= 1
            assert any("myFunction" in s for s in sigs)

            # Partially qualified
            sigs = analyzer.get_function_signature("inner::myFunction")
            assert len(sigs) >= 1
            assert any("myFunction" in s for s in sigs)

    def test_get_class_info_exact_match_with_leading_colons(self):
        """Leading :: should still require exact global namespace match."""
        from mcp_server.cpp_analyzer import CppAnalyzer
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace ns {
    class MyClass {};
}

class MyClass {};
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Leading :: means global namespace only
            result = analyzer.get_class_info("::MyClass")
            assert result is not None
            assert result["qualified_name"] == "MyClass"
            assert result["namespace"] == ""

    def test_get_class_hierarchy_partially_qualified(self):
        """get_class_hierarchy should work with partially qualified names."""
        from mcp_server.cpp_analyzer import CppAnalyzer
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace outer {
    namespace inner {
        class Base {};
        class Derived : public Base {};
    }
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Partially qualified - flat adjacency list format
            hierarchy = analyzer.get_class_hierarchy("inner::Derived")
            assert "error" not in hierarchy
            assert "queried_class" in hierarchy
            assert "classes" in hierarchy
            # queried_class should be the canonical qualified name
            qname = hierarchy["queried_class"]
            assert qname in hierarchy["classes"]
            node = hierarchy["classes"][qname]
            assert node["name"] == "Derived"

    def test_case_insensitive_partially_qualified(self):
        """Partially qualified matching should be case-insensitive."""
        from mcp_server.cpp_analyzer import CppAnalyzer
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace MyApp {
    namespace Core {
        class MyClass {};
    }
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Case-insensitive partial match
            result = analyzer.get_class_info("core::myclass")
            assert result is not None
            assert result["name"] == "MyClass"

            result = analyzer.get_class_info("CORE::MYCLASS")
            assert result is not None
            assert result["name"] == "MyClass"


class TestAmbiguousClassNameHandling:
    """Test ambiguity detection when multiple classes have the same simple name.

    Issue: get_class_info was silently returning the first match when multiple
    classes had the same simple name (e.g., SomeClass in two namespaces).
    The fix returns an ambiguity error with all matches.
    """

    def test_get_class_info_detects_ambiguous_simple_name(self):
        """get_class_info should return ambiguity error for simple name with multiple matches."""
        from mcp_server.cpp_analyzer import CppAnalyzer
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace ns1 {
    class SomeClass {
    public:
        void build1();
    };
}

namespace ns2 {
    class SomeClass {
    public:
        void build2();
    };
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Simple name should return ambiguity error
            result = analyzer.get_class_info("SomeClass")
            assert result is not None
            assert result.get("is_ambiguous") is True
            assert "error" in result
            assert "Ambiguous" in result["error"]
            assert "matches" in result
            assert len(result["matches"]) == 2

            # Verify both matches are present
            qualified_names = {m["qualified_name"] for m in result["matches"]}
            assert "ns1::SomeClass" in qualified_names
            assert "ns2::SomeClass" in qualified_names

            # Verify suggestion is present
            assert "suggestion" in result

    def test_get_class_info_qualified_name_no_ambiguity(self):
        """Qualified name should return exact match, not ambiguity error."""
        from mcp_server.cpp_analyzer import CppAnalyzer
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace ns1 {
    class SomeClass {
    public:
        void build1();
    };
}

namespace ns2 {
    class SomeClass {
    public:
        void build2();
    };
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Qualified name should return exact match
            result = analyzer.get_class_info("ns1::SomeClass")
            assert result is not None
            assert result.get("is_ambiguous") is not True
            assert result["qualified_name"] == "ns1::SomeClass"
            assert any(m["name"] == "build1" for m in result["methods"])

            result = analyzer.get_class_info("ns2::SomeClass")
            assert result is not None
            assert result.get("is_ambiguous") is not True
            assert result["qualified_name"] == "ns2::SomeClass"
            assert any(m["name"] == "build2" for m in result["methods"])

    def test_get_class_info_single_match_no_ambiguity(self):
        """Single class with simple name should return normally, not ambiguity error."""
        from mcp_server.cpp_analyzer import CppAnalyzer
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace ns1 {
    class UniqueClass {
    public:
        void method();
    };
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Single match should return normally
            result = analyzer.get_class_info("UniqueClass")
            assert result is not None
            assert result.get("is_ambiguous") is not True
            assert result["name"] == "UniqueClass"
            assert result["qualified_name"] == "ns1::UniqueClass"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
