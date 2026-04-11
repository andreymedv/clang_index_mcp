"""Tests for hierarchy_format module."""

import json
import pytest

from mcp_server.hierarchy_format import (
    convert_hierarchy_format,
    format_hierarchy_error,
)


@pytest.fixture
def sample_hierarchy():
    """Sample hierarchy data similar to real get_class_hierarchy output."""
    return {
        "queried_class": "app::ui::Widget",
        "direction": "both",
        "classes": {
            "app::EventHandler": {
                "qualified_name": "app::EventHandler",
                "name": "EventHandler",
                "kind": "class",
                "is_project": True,
                "base_classes": [],
                "derived_classes": ["app::ui::Widget"],
            },
            "app::ui::Widget": {
                "qualified_name": "app::ui::Widget",
                "name": "Widget",
                "kind": "class",
                "is_project": True,
                "base_classes": ["app::EventHandler"],
                "derived_classes": ["app::ui::ButtonWidget", "app::ui::TextWidget"],
            },
            "app::ui::ButtonWidget": {
                "qualified_name": "app::ui::ButtonWidget",
                "name": "ButtonWidget",
                "kind": "class",
                "is_project": True,
                "base_classes": ["app::ui::Widget"],
                "derived_classes": [],
            },
            "app::ui::TextWidget": {
                "qualified_name": "app::ui::TextWidget",
                "name": "TextWidget",
                "kind": "class",
                "is_project": True,
                "base_classes": ["app::ui::Widget"],
                "derived_classes": [],
            },
        },
        "completeness": "complete",
    }


class TestConvertHierarchyFormat:
    """Tests for convert_hierarchy_format function."""

    def test_json_format(self, sample_hierarchy):
        """Test JSON format returns indented JSON."""
        result = convert_hierarchy_format(sample_hierarchy, "json")
        # Should be valid JSON
        parsed = json.loads(result)
        assert parsed["queried_class"] == "app::ui::Widget"
        assert "classes" in parsed
        # Should be indented
        assert "\n" in result

    def test_compact_format(self, sample_hierarchy):
        """Test compact format uses abbreviated keys."""
        result = convert_hierarchy_format(sample_hierarchy, "compact")
        # Should have abbreviated keys
        assert '"q":' in result  # queried_class -> q
        assert '"c":' in result  # classes -> c
        assert '"qn":' in result  # qualified_name -> qn
        assert '"bases":' in result  # base_classes -> bases
        assert '"derived":' in result  # derived_classes -> derived
        # Should be compact (no newlines)
        assert "\n" not in result

    def test_cpp_format(self, sample_hierarchy):
        """Test C++ pseudocode format."""
        result = convert_hierarchy_format(sample_hierarchy, "cpp")
        lines = result.strip().split("\n")

        # Should have header comment
        assert lines[0].startswith("// Class hierarchy for:")
        assert "app::ui::Widget" in lines[0]

        # Should have class declarations
        assert any("class app::EventHandler" in line for line in lines)
        assert any("class app::ui::Widget" in line for line in lines)
        assert any("class app::ui::ButtonWidget" in line for line in lines)
        assert any("class app::ui::TextWidget" in line for line in lines)

        # Check inheritance syntax
        widget_line = [line for line in lines if "app::ui::Widget" in line and "class" in line][0]
        assert "public app::EventHandler" in widget_line

    def test_cpp_with_meta_format(self, sample_hierarchy):
        """Test C++ format with metadata comments."""
        result = convert_hierarchy_format(sample_hierarchy, "cpp_with_meta")
        lines = result.strip().split("\n")

        # Should have header comment
        assert lines[0].startswith("// Class hierarchy for:")

        # Should have metadata comments after class declarations
        assert any("// kind:" in line for line in lines)
        assert any("project: True" in line for line in lines)

    def test_cpp_format_with_unresolved_bases(self):
        """Test C++ format handles unresolved base classes."""
        hierarchy = {
            "queried_class": "app::MyClass",
            "classes": {
                "app::MyClass": {
                    "qualified_name": "app::MyClass",
                    "name": "MyClass",
                    "kind": "class",
                    "is_project": True,
                    "base_classes": ["ExternalBase", "app::InternalBase"],
                    "derived_classes": [],
                },
                "app::InternalBase": {
                    "qualified_name": "app::InternalBase",
                    "name": "InternalBase",
                    "kind": "class",
                    "is_project": True,
                    "base_classes": [],
                    "derived_classes": ["app::MyClass"],
                },
            },
        }

        result = convert_hierarchy_format(hierarchy, "cpp")
        # Should have forward declaration for unresolved base
        assert "class ExternalBase;" in result

    def test_cpp_format_truncated(self):
        """Test C++ format includes truncation notice."""
        hierarchy = {
            "queried_class": "app::Base",
            "classes": {},
            "truncated": True,
        }

        result = convert_hierarchy_format(hierarchy, "cpp")
        assert "truncated" in result.lower() or "Note: Hierarchy was truncated" in result

    def test_empty_hierarchy(self):
        """Test handling of empty hierarchy."""
        hierarchy = {
            "queried_class": "Unknown",
            "classes": {},
        }

        result = convert_hierarchy_format(hierarchy, "cpp")
        assert "No hierarchy data" in result

    def test_unknown_format_defaults_to_json(self, sample_hierarchy):
        """Test unknown format defaults to JSON."""
        result = convert_hierarchy_format(sample_hierarchy, "unknown_format")
        # Should be valid JSON
        parsed = json.loads(result)
        assert parsed["queried_class"] == "app::ui::Widget"


class TestFormatHierarchyError:
    """Tests for format_hierarchy_error function."""

    def test_json_error_format(self):
        """Test JSON format error."""
        result = format_hierarchy_error("Class not found", "json")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Class not found" in parsed["error"]

    def test_compact_error_format(self):
        """Test compact format error."""
        result = format_hierarchy_error("Class not found", "compact")
        parsed = json.loads(result)
        assert "err" in parsed

    def test_cpp_error_format(self):
        """Test C++ format error."""
        result = format_hierarchy_error("Class not found", "cpp")
        assert result.startswith("// Error:")
        assert "Class not found" in result


class TestTopologicalOrdering:
    """Tests for topological ordering in C++ format."""

    def test_bases_before_derived(self):
        """Test that base classes appear before derived classes."""
        hierarchy = {
            "queried_class": "C",
            "classes": {
                "C": {
                    "qualified_name": "C",
                    "name": "C",
                    "kind": "class",
                    "is_project": True,
                    "base_classes": ["B"],
                    "derived_classes": [],
                },
                "B": {
                    "qualified_name": "B",
                    "name": "B",
                    "kind": "class",
                    "is_project": True,
                    "base_classes": ["A"],
                    "derived_classes": ["C"],
                },
                "A": {
                    "qualified_name": "A",
                    "name": "A",
                    "kind": "class",
                    "is_project": True,
                    "base_classes": [],
                    "derived_classes": ["B"],
                },
            },
        }

        result = convert_hierarchy_format(hierarchy, "cpp")
        lines = [line for line in result.split("\n") if line.startswith("class ")]

        # A should come before B, B before C
        a_idx = next(i for i, line in enumerate(lines) if "class A" in line)
        b_idx = next(i for i, line in enumerate(lines) if "class B" in line)
        c_idx = next(i for i, line in enumerate(lines) if "class C" in line)

        assert a_idx < b_idx < c_idx


class TestMultipleInheritance:
    """Tests for multiple inheritance in C++ format."""

    def test_multiple_bases(self):
        """Test class with multiple base classes."""
        hierarchy = {
            "queried_class": "Derived",
            "classes": {
                "Derived": {
                    "qualified_name": "Derived",
                    "name": "Derived",
                    "kind": "class",
                    "is_project": True,
                    "base_classes": ["Base1", "Base2", "Base3"],
                    "derived_classes": [],
                },
            },
        }

        result = convert_hierarchy_format(hierarchy, "cpp")
        # Should have all base classes in inheritance list
        assert "class Derived: public Base1, public Base2, public Base3" in result
