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
    - CO::DocumentBuilder::TextBuilder (class)
    - CO::DocumentBuilder::HtmlBuilder (class)
    - DocumentBuilder::XmlBuilder (class) - different root namespace
    - TopLevel::CO::DocumentBuilder::PdfBuilder (class) - deeply nested
    """
    project = tmp_path / "nested_namespace"
    project.mkdir()

    # CO::DocumentBuilder namespace with multiple classes
    co_builders = project / "co_builders.h"
    co_builders.write_text(
        """
namespace CO {
    namespace DocumentBuilder {
        class TextBuilder {
        public:
            void build();
        };

        class HtmlBuilder {
        public:
            void render();
        };

        void initialize();
    }
}
"""
    )

    # Standalone DocumentBuilder namespace (different from CO::DocumentBuilder)
    doc_builder = project / "doc_builder.h"
    doc_builder.write_text(
        """
namespace DocumentBuilder {
    class XmlBuilder {
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
    namespace CO {
        namespace DocumentBuilder {
            class PdfBuilder {
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

    "DocumentBuilder" should match:
    - CO::DocumentBuilder (suffix match)
    - DocumentBuilder (exact match)
    - TopLevel::CO::DocumentBuilder (suffix match)
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    # Partial namespace "DocumentBuilder" should find classes in all matching namespaces
    results = analyzer.search_classes("", namespace="DocumentBuilder")

    # Should find: TextBuilder, HtmlBuilder (CO::DocumentBuilder)
    #              XmlBuilder (DocumentBuilder)
    #              PdfBuilder (TopLevel::CO::DocumentBuilder)
    assert (
        len(results) == 4
    ), f"Expected 4 classes, got {len(results)}: {[r['qualified_name'] for r in results]}"

    # Verify all matched namespaces end with "DocumentBuilder"
    for result in results:
        ns = result["namespace"]
        assert ns == "DocumentBuilder" or ns.endswith(
            "::DocumentBuilder"
        ), f"Namespace '{ns}' doesn't match partial filter 'DocumentBuilder'"


def test_partial_namespace_matching_functions(nested_namespace_project):
    """
    Test that partial namespace filter works for functions/methods.
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    # Find functions in DocumentBuilder (partial match)
    results = analyzer.search_functions("", namespace="DocumentBuilder")

    # Should find: initialize (CO::DocumentBuilder), setup (DocumentBuilder)
    standalone_funcs = [f for f in results if not f["parent_class"]]
    assert len(standalone_funcs) == 2, f"Expected 2 functions, got {len(standalone_funcs)}"


def test_partial_namespace_excludes_non_suffix_matches(nested_namespace_project):
    """
    Test that partial namespace filter does NOT match substrings that aren't at :: boundary.

    "Builder" should NOT match "DocumentBuilder" because "Builder" is not preceded by "::".
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

    # TopLevel::CO::DocumentBuilder is unique - no other namespace ends with it
    results = analyzer.search_classes("", namespace="TopLevel::CO::DocumentBuilder")
    assert (
        len(results) == 1
    ), f"Expected 1 class in TopLevel::CO::DocumentBuilder, got {len(results)}"
    assert results[0]["name"] == "PdfBuilder"

    # Standalone "DocumentBuilder" namespace is also matchable exactly
    results2 = analyzer.search_classes("XmlBuilder", namespace="DocumentBuilder")
    assert len(results2) == 1
    assert results2[0]["qualified_name"] == "DocumentBuilder::XmlBuilder"


def test_partial_namespace_with_intermediate_component(nested_namespace_project):
    """
    Test partial namespace with intermediate component like "CO::DocumentBuilder".

    This should match both CO::DocumentBuilder and TopLevel::CO::DocumentBuilder.
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    results = analyzer.search_classes("", namespace="CO::DocumentBuilder")

    # Should find: TextBuilder, HtmlBuilder (CO::DocumentBuilder)
    #              PdfBuilder (TopLevel::CO::DocumentBuilder)
    assert len(results) == 3, f"Expected 3 classes, got {len(results)}"

    qualified_names = {r["qualified_name"] for r in results}
    assert "CO::DocumentBuilder::TextBuilder" in qualified_names
    assert "CO::DocumentBuilder::HtmlBuilder" in qualified_names
    assert "TopLevel::CO::DocumentBuilder::PdfBuilder" in qualified_names


def test_partial_namespace_case_sensitive(nested_namespace_project):
    """
    Test that partial namespace matching is still case-sensitive.
    """
    analyzer = CppAnalyzer(str(nested_namespace_project))
    analyzer.index_project()

    # Correct case should match
    results_correct = analyzer.search_classes("", namespace="DocumentBuilder")
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

    # Search for ".*Builder" pattern in partial namespace "DocumentBuilder"
    results = analyzer.search_classes(".*Builder", namespace="DocumentBuilder")

    # Should find all 4 builder classes
    assert len(results) == 4, f"Expected 4 classes, got {len(results)}"

    # Search for specific class in partial namespace
    results2 = analyzer.search_classes("TextBuilder", namespace="DocumentBuilder")
    assert len(results2) == 1
    assert results2[0]["qualified_name"] == "CO::DocumentBuilder::TextBuilder"
