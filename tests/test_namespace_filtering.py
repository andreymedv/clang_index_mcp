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
    - Outer::ItemBuilder::TextComposer (class)
    - Outer::ItemBuilder::MarkupBuilder (class)
    - ItemBuilder::DataBuilder (class) - different root namespace
    - TopLevel::Outer::ItemBuilder::ReportBuilder (class) - deeply nested
    """
    project = tmp_path / "nested_namespace"
    project.mkdir()

    # Outer::ItemBuilder namespace with multiple classes
    outer_builders = project / "outer_builders.h"
    outer_builders.write_text(
        """
namespace Outer {
    namespace ItemBuilder {
        class TextComposer {
        public:
            void build();
        };

        class MarkupBuilder {
        public:
            void render();
        };

        void initialize();
    }
}
"""
    )

    # Standalone ItemBuilder namespace (different from Outer::ItemBuilder)
    item_builder = project / "item_builder.h"
    item_builder.write_text(
        """
namespace ItemBuilder {
    class DataBuilder {
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
    namespace Outer {
        namespace ItemBuilder {
            class ReportBuilder {
            public:
                void export_report();
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

    "ItemBuilder" should match:
    - Outer::ItemBuilder (suffix match)
    - ItemBuilder (exact match)
    - TopLevel::Outer::ItemBuilder (suffix match)
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    # Partial namespace "ItemBuilder" should find classes in all matching namespaces
    results = analyzer.search_classes("", namespace="ItemBuilder")

    # Should find: TextComposer, MarkupBuilder (Outer::ItemBuilder)
    #              DataBuilder (ItemBuilder)
    #              ReportBuilder (TopLevel::Outer::ItemBuilder)
    assert (
        len(results) == 4
    ), f"Expected 4 classes, got {len(results)}: {[r['qualified_name'] for r in results]}"

    # Verify all matched namespaces end with "ItemBuilder"
    for result in results:
        ns = result["namespace"]
        assert ns == "ItemBuilder" or ns.endswith(
            "::ItemBuilder"
        ), f"Namespace '{ns}' doesn't match partial filter 'ItemBuilder'"


def test_partial_namespace_matching_functions(nested_namespace_project):
    """
    Test that partial namespace filter works for functions/methods.
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    # Find functions in ItemBuilder (partial match)
    results = analyzer.search_functions("", namespace="ItemBuilder")

    # Should find: initialize (Outer::ItemBuilder), setup (ItemBuilder)
    standalone_funcs = [f for f in results if not f["parent_class"]]
    assert len(standalone_funcs) == 2, f"Expected 2 functions, got {len(standalone_funcs)}"


def test_partial_namespace_excludes_non_suffix_matches(nested_namespace_project):
    """
    Test that partial namespace filter does NOT match substrings that aren't at :: boundary.

    "Builder" should NOT match "ItemBuilder" because "Builder" is not preceded by "::".
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    # "Builder" should not match any namespace (no namespace is just "Builder" or ends with "::Builder")
    results = analyzer.search_classes("", namespace="Builder")
    assert len(results) == 0, f"Expected 0 classes for namespace='Builder', got {len(results)}"


def test_unique_namespace_exact_match(nested_namespace_project):
    """
    Test that unique full namespace only matches exactly one namespace.

    When the filter matches only one namespace (no suffix matches exist),
    it behaves like exact match.
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    # TopLevel::Outer::ItemBuilder is unique - no other namespace ends with it
    results = analyzer.search_classes("", namespace="TopLevel::Outer::ItemBuilder")
    assert (
        len(results) == 1
    ), f"Expected 1 class in TopLevel::Outer::ItemBuilder, got {len(results)}"
    assert results[0]["name"] == "ReportBuilder"

    # Standalone "ItemBuilder" namespace is also matchable exactly
    results2 = analyzer.search_classes("DataBuilder", namespace="ItemBuilder")
    assert len(results2) == 1
    assert results2[0]["qualified_name"] == "ItemBuilder::DataBuilder"


def test_partial_namespace_with_intermediate_component(nested_namespace_project):
    """
    Test partial namespace with intermediate component like "Outer::ItemBuilder".

    This should match both Outer::ItemBuilder and TopLevel::Outer::ItemBuilder.
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    results = analyzer.search_classes("", namespace="Outer::ItemBuilder")

    # Should find: TextComposer, MarkupBuilder (Outer::ItemBuilder)
    #              ReportBuilder (TopLevel::Outer::ItemBuilder)
    assert len(results) == 3, f"Expected 3 classes, got {len(results)}"

    qualified_names = {r["qualified_name"] for r in results}
    assert "Outer::ItemBuilder::TextComposer" in qualified_names
    assert "Outer::ItemBuilder::MarkupBuilder" in qualified_names
    assert "TopLevel::Outer::ItemBuilder::ReportBuilder" in qualified_names


def test_partial_namespace_case_sensitive(nested_namespace_project):
    """
    Test that partial namespace matching is still case-sensitive.
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    # Correct case should match
    results_correct = analyzer.search_classes("", namespace="ItemBuilder")
    assert len(results_correct) == 4

    # Wrong case should not match
    results_wrong = analyzer.search_classes("", namespace="documentbuilder")
    assert len(results_wrong) == 0

    results_wrong2 = analyzer.search_classes("", namespace="DOCUMENTBUILDER")
    assert len(results_wrong2) == 0


def test_partial_namespace_with_pattern(nested_namespace_project):
    """
    Test that partial namespace works together with pattern filtering.
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    # Search for ".*Builder" pattern in partial namespace "ItemBuilder"
    results = analyzer.search_classes(".*Builder", namespace="ItemBuilder")

    # Should find all 4 builder classes
    assert len(results) == 4, f"Expected 4 classes, got {len(results)}"

    # Search for specific class in partial namespace
    results2 = analyzer.search_classes("TextComposer", namespace="ItemBuilder")
    assert len(results2) == 1
    assert results2[0]["qualified_name"] == "Outer::ItemBuilder::TextComposer"
