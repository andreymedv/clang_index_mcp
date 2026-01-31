"""
Regression tests for forward declaration + definition handling.

Prevents regression of cplusplus_mcp-2u9: get_class_info returning forward
declaration instead of definition when both exist.

The key scenario is when a forward declaration (with no base classes visible)
exists alongside the actual definition (with base classes). The query methods
must return the definition, not the forward declaration.
"""

import pytest
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.fixture
def forward_decl_project(tmp_path):
    """Create a project with forward declaration + definition scenario.

    This is the exact scenario from cplusplus_mcp-2u9:
    - BaseWidget is a base class
    - ConcreteWidget has a forward declaration (no base classes visible)
    - ConcreteWidget has a definition that inherits from BaseWidget

    The bug was that get_class_info would return the forward declaration
    (with empty base_classes) instead of the definition.
    """
    # Create header with both forward declaration and definition
    header_h = tmp_path / "widgets.h"
    header_h.write_text("""
namespace test {

struct BaseWidget {
    virtual ~BaseWidget() = default;
    virtual void render() = 0;
};

// Forward declaration (no base classes visible here)
struct ConcreteWidget;

// Actual definition (has base class)
struct ConcreteWidget : BaseWidget {
    void someMethod();
    void render() override;
};

}  // namespace test
""")

    # Create source file that uses the widgets
    source_cpp = tmp_path / "main.cpp"
    source_cpp.write_text("""
#include "widgets.h"

namespace test {

void ConcreteWidget::someMethod() {
    // Implementation
}

void ConcreteWidget::render() {
    // Implementation
}

}  // namespace test

int main() {
    test::ConcreteWidget widget;
    widget.render();
    return 0;
}
""")

    # Index the project
    analyzer = CppAnalyzer(project_root=str(tmp_path))
    analyzer.index_file(str(header_h))
    analyzer.index_file(str(source_cpp))

    return analyzer


class TestGetClassInfoReturnsDefinition:
    """Test that get_class_info returns the definition, not forward declaration."""

    def test_get_class_info_simple_name_has_base_classes(self, forward_decl_project):
        """Test 1: get_class_info with simple name returns definition with base classes."""
        analyzer = forward_decl_project

        info = analyzer.get_class_info('ConcreteWidget')

        assert info is not None, "get_class_info should find ConcreteWidget"
        assert 'error' not in info, f"get_class_info returned error: {info.get('error')}"

        # The critical assertion: base_classes must not be empty
        # If this fails, we're getting the forward declaration instead of definition
        base_classes = info.get('base_classes', [])
        assert base_classes != [], (
            "base_classes is empty - likely returning forward declaration instead of definition"
        )
        assert 'BaseWidget' in str(base_classes), (
            f"BaseWidget not found in base_classes: {base_classes}"
        )

    def test_get_class_info_qualified_name_has_base_classes(self, forward_decl_project):
        """Test 2: get_class_info with qualified name returns definition with base classes."""
        analyzer = forward_decl_project

        info = analyzer.get_class_info('test::ConcreteWidget')

        assert info is not None, "get_class_info should find test::ConcreteWidget"
        assert 'error' not in info, f"get_class_info returned error: {info.get('error')}"

        # The critical assertion: base_classes must not be empty
        base_classes = info.get('base_classes', [])
        assert base_classes != [], (
            "base_classes is empty - likely returning forward declaration instead of definition"
        )
        # Accept either qualified or simple name in base_classes
        assert 'BaseWidget' in str(base_classes), (
            f"BaseWidget not found in base_classes: {base_classes}"
        )

    def test_get_class_info_returns_correct_line_range(self, forward_decl_project):
        """Test that the returned info has correct line range (definition, not forward decl)."""
        analyzer = forward_decl_project

        info = analyzer.get_class_info('test::ConcreteWidget')

        assert info is not None
        assert 'error' not in info
        # The returned info should be the definition (multi-line), not forward decl (single line)
        start_line = info.get('start_line')
        end_line = info.get('end_line')
        assert start_line is not None and end_line is not None
        # Definition spans multiple lines (struct with methods)
        # Forward declaration would be a single line
        assert end_line > start_line, (
            f"Expected multi-line definition, got start_line={start_line}, end_line={end_line}"
        )


class TestGetClassHierarchyReturnsDefinition:
    """Test that get_class_hierarchy uses the definition."""

    def test_get_class_hierarchy_includes_base_classes(self, forward_decl_project):
        """Test 3: get_class_hierarchy includes base classes from definition."""
        analyzer = forward_decl_project

        hierarchy = analyzer.get_class_hierarchy('test::ConcreteWidget')

        assert hierarchy is not None, "get_class_hierarchy should find test::ConcreteWidget"
        assert 'error' not in hierarchy, f"get_class_hierarchy returned error: {hierarchy.get('error')}"

        # The critical assertion: base_classes must be present
        base_classes = hierarchy.get('base_classes', [])
        assert len(base_classes) > 0, (
            "base_classes is empty in hierarchy - likely using forward declaration"
        )


class TestSearchClassesReturnsDefinition:
    """Test that search_classes returns the definition."""

    def test_search_classes_returns_definition_with_base_classes(self, forward_decl_project):
        """Test 4: search_classes returns definition, not declaration."""
        analyzer = forward_decl_project

        results = analyzer.search_classes('ConcreteWidget')

        assert len(results) > 0, "search_classes should find ConcreteWidget"

        # Find the ConcreteWidget result
        concrete_widget = None
        for result in results:
            if result.get('name') == 'ConcreteWidget':
                concrete_widget = result
                break

        assert concrete_widget is not None, "ConcreteWidget not found in search results"

        # The critical assertion: should have base classes (definition, not declaration)
        base_classes = concrete_widget.get('base_classes', [])
        assert 'BaseWidget' in str(base_classes), (
            f"BaseWidget not in base_classes: {base_classes}. "
            "search_classes may be returning forward declaration instead of definition."
        )

    def test_search_classes_qualified_returns_definition(self, forward_decl_project):
        """Test search_classes with qualified pattern returns definition."""
        analyzer = forward_decl_project

        results = analyzer.search_classes('test::ConcreteWidget')

        assert len(results) > 0, "search_classes should find test::ConcreteWidget"

        # All results should have base classes (definition)
        for result in results:
            if result.get('name') == 'ConcreteWidget':
                base_classes = result.get('base_classes', [])
                assert 'BaseWidget' in str(base_classes), (
                    f"BaseWidget not in base_classes for qualified search: {base_classes}"
                )


class TestDefinitionWinsInVariousScenarios:
    """Additional scenarios to ensure definition-wins logic is robust."""

    def test_definition_indexed_before_declaration(self, tmp_path):
        """Test when definition is indexed before forward declaration."""
        # Definition first (Base must be defined before MyClass for C++ to work)
        definition_h = tmp_path / "definition.h"
        definition_h.write_text("""
struct Base {
    virtual ~Base() = default;
};

struct MyClass : public Base {
    void method();
};
""")

        # Forward declaration second
        forward_h = tmp_path / "forward.h"
        forward_h.write_text("""
struct MyClass;  // Forward declaration
""")

        analyzer = CppAnalyzer(project_root=str(tmp_path))
        # Index definition first
        analyzer.index_file(str(definition_h))
        # Then forward declaration
        analyzer.index_file(str(forward_h))

        info = analyzer.get_class_info('MyClass')
        assert info is not None
        # Definition should have base classes
        assert 'Base' in str(info.get('base_classes', [])), "Should have base classes"
        # Definition spans multiple lines
        assert info.get('end_line', 0) > info.get('start_line', 0), "Should be multi-line definition"

    def test_declaration_indexed_before_definition(self, tmp_path):
        """Test when forward declaration is indexed before definition."""
        # Forward declaration first
        forward_h = tmp_path / "forward.h"
        forward_h.write_text("""
struct MyClass;  // Forward declaration
""")

        # Definition second (Base must be defined before MyClass)
        definition_h = tmp_path / "definition.h"
        definition_h.write_text("""
struct Base {
    virtual ~Base() = default;
};

struct MyClass : public Base {
    void method();
};
""")

        analyzer = CppAnalyzer(project_root=str(tmp_path))
        # Index forward declaration first
        analyzer.index_file(str(forward_h))
        # Then definition
        analyzer.index_file(str(definition_h))

        info = analyzer.get_class_info('MyClass')
        assert info is not None
        # Definition should have base classes
        assert 'Base' in str(info.get('base_classes', [])), "Should have base classes"
        # Definition spans multiple lines
        assert info.get('end_line', 0) > info.get('start_line', 0), "Should be multi-line definition"

    def test_multiple_forward_declarations_one_definition(self, tmp_path):
        """Test with multiple forward declarations and one definition."""
        # Multiple forward declarations
        fwd1_h = tmp_path / "fwd1.h"
        fwd1_h.write_text("struct Widget;")

        fwd2_h = tmp_path / "fwd2.h"
        fwd2_h.write_text("struct Widget;")

        fwd3_h = tmp_path / "fwd3.h"
        fwd3_h.write_text("struct Widget;")

        # One definition (WidgetBase must be defined before Widget)
        widget_h = tmp_path / "widget.h"
        widget_h.write_text("""
struct WidgetBase {
    virtual ~WidgetBase() = default;
};

struct Widget : WidgetBase {
    int value;
};
""")

        analyzer = CppAnalyzer(project_root=str(tmp_path))
        # Index all forward declarations first
        analyzer.index_file(str(fwd1_h))
        analyzer.index_file(str(fwd2_h))
        analyzer.index_file(str(fwd3_h))
        # Then definition
        analyzer.index_file(str(widget_h))

        info = analyzer.get_class_info('Widget')
        assert info is not None
        # Definition should have base classes
        assert 'WidgetBase' in str(info.get('base_classes', []))
        # Definition spans multiple lines
        assert info.get('end_line', 0) > info.get('start_line', 0), "Should be multi-line definition"

    def test_namespaced_forward_declaration(self, tmp_path):
        """Test forward declaration in namespace."""
        header_h = tmp_path / "header.h"
        header_h.write_text("""
namespace app {
namespace ui {

struct Button;  // Forward declaration

struct ButtonBase {
    virtual void click() = 0;
};

struct Button : ButtonBase {
    void click() override;
};

}  // namespace ui
}  // namespace app
""")

        analyzer = CppAnalyzer(project_root=str(tmp_path))
        analyzer.index_file(str(header_h))

        # Test with various qualified name forms
        for name in ['Button', 'ui::Button', 'app::ui::Button']:
            info = analyzer.get_class_info(name)
            if info and 'error' not in info:
                # Definition should have base classes
                assert 'ButtonBase' in str(info.get('base_classes', [])), f"No base for {name}"
                # Definition spans multiple lines
                assert info.get('end_line', 0) > info.get('start_line', 0), (
                    f"Should be multi-line definition for {name}"
                )
