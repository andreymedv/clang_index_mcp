#!/usr/bin/env python3
"""
Tests for namespace filtering feature (Issue #100 / cplusplus_mcp-481)

These tests verify that the namespace parameter correctly filters search results
to disambiguate when multiple namespaces have the same class/function name.
"""

import pytest
from pathlib import Path
from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.fixture
def multi_namespace_project(tmp_path):
    """
    Create a C++ project with the same class names in different namespaces
    to test namespace disambiguation.
    """
    project = tmp_path / "multi_namespace"
    project.mkdir()

    # Create ns1::View and ns1::Controller
    ns1_header = project / "ns1.h"
    ns1_header.write_text(
        """
namespace ns1 {
    class View {
    public:
        void render();
    };

    class Controller {
    public:
        void process();
    };

    void handleEvent();
}
"""
    )

    # Create ns2::View and ns2::Controller
    ns2_header = project / "ns2.h"
    ns2_header.write_text(
        """
namespace ns2 {
    class View {
    public:
        void display();
    };

    class Controller {
    public:
        void execute();
    };

    void handleEvent();
}
"""
    )

    # Create global namespace View
    global_header = project / "global.h"
    global_header.write_text(
        """
class View {
public:
    void show();
};

void handleEvent();
"""
    )

    return project


def test_filter_classes_by_namespace(multi_namespace_project):
    """
    Test that namespace parameter filters classes correctly
    """
    analyzer = CppAnalyzer(str(multi_namespace_project))
    analyzer.index_project()

    # Search without namespace filter - should return all 3 View classes
    all_views = analyzer.search_classes("View")
    assert len(all_views) == 3, f"Expected 3 View classes, got {len(all_views)}"

    # Filter by ns1 namespace
    ns1_views = analyzer.search_classes("View", namespace="ns1")
    assert len(ns1_views) == 1, f"Expected 1 View in ns1, got {len(ns1_views)}"
    assert ns1_views[0]["namespace"] == "ns1"
    assert ns1_views[0]["qualified_name"] == "ns1::View"

    # Filter by ns2 namespace
    ns2_views = analyzer.search_classes("View", namespace="ns2")
    assert len(ns2_views) == 1, f"Expected 1 View in ns2, got {len(ns2_views)}"
    assert ns2_views[0]["namespace"] == "ns2"
    assert ns2_views[0]["qualified_name"] == "ns2::View"

    # Filter by global namespace (empty string)
    global_views = analyzer.search_classes("View", namespace="")
    assert len(global_views) == 1, f"Expected 1 View in global namespace, got {len(global_views)}"
    assert global_views[0]["namespace"] == ""
    assert global_views[0]["qualified_name"] == "View"


def test_filter_functions_by_namespace(multi_namespace_project):
    """
    Test that namespace parameter filters functions correctly
    """
    analyzer = CppAnalyzer(str(multi_namespace_project))
    analyzer.index_project()

    # Search without namespace filter - should return all 3 handleEvent functions
    all_handles = analyzer.search_functions("handleEvent")
    assert len(all_handles) == 3, f"Expected 3 handleEvent functions, got {len(all_handles)}"

    # Filter by ns1 namespace
    ns1_handles = analyzer.search_functions("handleEvent", namespace="ns1")
    assert len(ns1_handles) == 1, f"Expected 1 handleEvent in ns1, got {len(ns1_handles)}"
    assert ns1_handles[0]["namespace"] == "ns1"
    assert ns1_handles[0]["qualified_name"] == "ns1::handleEvent"

    # Filter by ns2 namespace
    ns2_handles = analyzer.search_functions("handleEvent", namespace="ns2")
    assert len(ns2_handles) == 1, f"Expected 1 handleEvent in ns2, got {len(ns2_handles)}"
    assert ns2_handles[0]["namespace"] == "ns2"
    assert ns2_handles[0]["qualified_name"] == "ns2::handleEvent"

    # Filter by global namespace
    global_handles = analyzer.search_functions("handleEvent", namespace="")
    assert (
        len(global_handles) == 1
    ), f"Expected 1 handleEvent in global namespace, got {len(global_handles)}"
    assert global_handles[0]["namespace"] == ""
    assert global_handles[0]["qualified_name"] == "handleEvent"


def test_filter_methods_by_namespace_and_class(multi_namespace_project):
    """
    Test that namespace parameter filters methods correctly
    For methods, namespace includes both namespace and class (e.g., "ns1::View")
    """
    analyzer = CppAnalyzer(str(multi_namespace_project))
    analyzer.index_project()

    # Search without namespace filter - should return all render/display/show methods
    all_render_methods = analyzer.search_functions("render")
    assert len(all_render_methods) == 1  # Only ns1::View::render exists

    # Filter methods by namespace + class
    ns1_view_methods = analyzer.search_functions("render", namespace="ns1::View")
    assert len(ns1_view_methods) == 1
    assert ns1_view_methods[0]["namespace"] == "ns1::View"
    assert ns1_view_methods[0]["parent_class"] == "View"

    # Search for display method
    ns2_display = analyzer.search_functions("display", namespace="ns2::View")
    assert len(ns2_display) == 1
    assert ns2_display[0]["namespace"] == "ns2::View"

    # Search for global View::show method
    global_show = analyzer.search_functions("show", namespace="View")
    assert len(global_show) == 1
    assert global_show[0]["namespace"] == "View"


def test_search_symbols_with_namespace_filter(multi_namespace_project):
    """
    Test that search_symbols respects namespace parameter
    """
    analyzer = CppAnalyzer(str(multi_namespace_project))
    analyzer.index_project()

    # Search without namespace filter
    all_symbols = analyzer.search_symbols("View")
    assert len(all_symbols["classes"]) == 3, "Should find all 3 View classes"

    # Filter by ns1 namespace
    ns1_symbols = analyzer.search_symbols("View", namespace="ns1")
    assert len(ns1_symbols["classes"]) == 1
    assert ns1_symbols["classes"][0]["namespace"] == "ns1"

    # Search for Controller in ns2
    ns2_controller = analyzer.search_symbols("Controller", namespace="ns2")
    assert len(ns2_controller["classes"]) == 1
    assert ns2_controller["classes"][0]["qualified_name"] == "ns2::Controller"


def test_namespace_filter_with_empty_pattern(multi_namespace_project):
    """
    Test namespace filtering when pattern is empty (matches all)
    """
    analyzer = CppAnalyzer(str(multi_namespace_project))
    analyzer.index_project()

    # Get all classes in ns1 namespace (empty pattern)
    ns1_all_classes = analyzer.search_classes("", namespace="ns1")
    assert len(ns1_all_classes) == 2  # View and Controller in ns1
    namespaces = {c["namespace"] for c in ns1_all_classes}
    assert namespaces == {"ns1"}

    # Get all functions in global namespace
    global_functions = analyzer.search_functions("", namespace="")
    # Should only get global handleEvent, not methods
    global_standalone = [f for f in global_functions if not f["parent_class"]]
    assert all(f["namespace"] == "" for f in global_standalone)


def test_namespace_filter_with_qualified_pattern(multi_namespace_project):
    """
    Test that namespace filter works with qualified patterns
    When both are specified, they should work together
    """
    analyzer = CppAnalyzer(str(multi_namespace_project))
    analyzer.index_project()

    # Use qualified pattern AND namespace filter
    # Pattern "ns1::View" should match, namespace filter "ns1" should also match
    results = analyzer.search_classes("ns1::View", namespace="ns1")
    assert len(results) == 1
    assert results[0]["qualified_name"] == "ns1::View"

    # Pattern "View" with namespace "ns2" should find ns2::View
    results2 = analyzer.search_classes("View", namespace="ns2")
    assert len(results2) == 1
    assert results2[0]["qualified_name"] == "ns2::View"


def test_namespace_filter_no_matches(multi_namespace_project):
    """
    Test that namespace filter returns empty when no matches exist
    """
    analyzer = CppAnalyzer(str(multi_namespace_project))
    analyzer.index_project()

    # Search for View in non-existent namespace
    results = analyzer.search_classes("View", namespace="nonexistent")
    assert len(results) == 0

    # Search for non-existent class in existing namespace
    results2 = analyzer.search_classes("NonExistent", namespace="ns1")
    assert len(results2) == 0


def test_namespace_filter_case_sensitive(multi_namespace_project):
    """
    Test that namespace filtering is case-sensitive (as documented)
    """
    analyzer = CppAnalyzer(str(multi_namespace_project))
    analyzer.index_project()

    # Correct case
    results_correct = analyzer.search_classes("View", namespace="ns1")
    assert len(results_correct) == 1

    # Wrong case - should not match
    results_wrong = analyzer.search_classes("View", namespace="NS1")
    assert len(results_wrong) == 0

    results_wrong2 = analyzer.search_classes("View", namespace="Ns1")
    assert len(results_wrong2) == 0


# =============================================================================
# Partial Namespace Matching Tests (Issue: partial namespace filter support)
# =============================================================================


@pytest.fixture
def nested_namespace_project(tmp_path):
    """
    Create a C++ project with nested namespaces to test partial namespace matching.

    Namespace structure:
    - outer::builders::TextWidget (class)
    - outer::builders::HtmlWidget (class)
    - builders::XmlWidget (class) - different root namespace
    - TopLevel::outer::builders::PdfWidget (class) - deeply nested
    """
    project = tmp_path / "nested_namespace"
    project.mkdir()

    # outer::builders namespace with multiple classes
    co_builders = project / "co_builders.h"
    co_builders.write_text(
        """
namespace outer {
    namespace builders {
        class TextWidget {
        public:
            void build();
        };

        class HtmlWidget {
        public:
            void render();
        };

        void initialize();
    }
}
"""
    )

    # Standalone builders namespace (different from outer::builders)
    doc_builder = project / "doc_builder.h"
    doc_builder.write_text(
        """
namespace builders {
    class XmlWidget {
    public:
        void serialize();
    };

    void setup();
}
"""
    )

    # Deeply nested namespace
    deep_nested = project / "deep_nested.h"
    deep_nested.write_text(
        """
namespace TopLevel {
    namespace outer {
        namespace builders {
            class PdfWidget {
            public:
                void export_pdf();
            };
        }
    }
}
"""
    )

    return project


def test_partial_namespace_matching_classes(nested_namespace_project):
    """
    Test that partial namespace filter matches suffix of full namespace.

    "builders" should match:
    - outer::builders (suffix match)
    - builders (exact match)
    - TopLevel::outer::builders (suffix match)
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    # Partial namespace "builders" should find classes in all matching namespaces
    results = analyzer.search_classes("", namespace="builders")

    # Should find: TextWidget, HtmlWidget (outer::builders)
    #              XmlWidget (builders)
    #              PdfWidget (TopLevel::outer::builders)
    assert (
        len(results) == 4
    ), f"Expected 4 classes, got {len(results)}: {[r['qualified_name'] for r in results]}"

    # Verify all matched namespaces end with "builders"
    for result in results:
        ns = result["namespace"]
        assert ns == "builders" or ns.endswith(
            "::builders"
        ), f"Namespace '{ns}' doesn't match partial filter 'builders'"


def test_partial_namespace_matching_functions(nested_namespace_project):
    """
    Test that partial namespace filter works for functions/methods.
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    # Find functions in builders (partial match)
    results = analyzer.search_functions("", namespace="builders")

    # Should find: initialize (outer::builders), setup (builders)
    standalone_funcs = [f for f in results if not f["parent_class"]]
    assert len(standalone_funcs) == 2, f"Expected 2 functions, got {len(standalone_funcs)}"


def test_partial_namespace_excludes_non_suffix_matches(nested_namespace_project):
    """
    Test that partial namespace filter does NOT match substrings that aren't at :: boundary.

    "uilders" should NOT match "builders" because "uilders" is not preceded by "::".
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    # "uilders" should not match any namespace (no namespace is just "uilders" or ends with "::uilders")
    results = analyzer.search_classes("", namespace="uilders")
    assert len(results) == 0, f"Expected 0 classes for namespace='uilders', got {len(results)}"


def test_unique_namespace_exact_match(nested_namespace_project):
    """
    Test that unique full namespace only matches exactly one namespace.

    When the filter matches only one namespace (no suffix matches exist),
    it behaves like exact match.
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    # TopLevel::outer::builders is unique - no other namespace ends with it
    results = analyzer.search_classes("", namespace="TopLevel::outer::builders")
    assert (
        len(results) == 1
    ), f"Expected 1 class in TopLevel::outer::builders, got {len(results)}"
    assert results[0]["name"] == "PdfWidget"

    # Standalone "builders" namespace is also matchable exactly
    results2 = analyzer.search_classes("XmlWidget", namespace="builders")
    assert len(results2) == 1
    assert results2[0]["qualified_name"] == "builders::XmlWidget"


def test_partial_namespace_with_intermediate_component(nested_namespace_project):
    """
    Test partial namespace with intermediate component like "outer::builders".

    This should match both outer::builders and TopLevel::outer::builders.
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    results = analyzer.search_classes("", namespace="outer::builders")

    # Should find: TextWidget, HtmlWidget (outer::builders)
    #              PdfWidget (TopLevel::outer::builders)
    assert len(results) == 3, f"Expected 3 classes, got {len(results)}"

    qualified_names = {r["qualified_name"] for r in results}
    assert "outer::builders::TextWidget" in qualified_names
    assert "outer::builders::HtmlWidget" in qualified_names
    assert "TopLevel::outer::builders::PdfWidget" in qualified_names


def test_partial_namespace_case_sensitive(nested_namespace_project):
    """
    Test that partial namespace matching is still case-sensitive.
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    # Correct case should match
    results_correct = analyzer.search_classes("", namespace="builders")
    assert len(results_correct) == 4

    # Wrong case should not match
    results_wrong = analyzer.search_classes("", namespace="Builders")
    assert len(results_wrong) == 0

    results_wrong2 = analyzer.search_classes("", namespace="BUILDERS")
    assert len(results_wrong2) == 0


def test_partial_namespace_with_pattern(nested_namespace_project):
    """
    Test that partial namespace works together with pattern filtering.
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    # Search for ".*Widget" pattern in partial namespace "builders"
    results = analyzer.search_classes(".*Widget", namespace="builders")

    # Should find all 4 widget classes
    assert len(results) == 4, f"Expected 4 classes, got {len(results)}"

    # Search for specific class in partial namespace
    results2 = analyzer.search_classes("TextWidget", namespace="builders")
    assert len(results2) == 1
    assert results2[0]["qualified_name"] == "outer::builders::TextWidget"
