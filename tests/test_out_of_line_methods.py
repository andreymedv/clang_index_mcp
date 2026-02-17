"""
Tests for out-of-line method definitions in get_class_info.

Verifies that methods declared in a header and defined outside the class body
(the standard C++ pattern) are correctly associated with their class.

Root cause being tested: out-of-line definitions like `void Foo::bar() {}`
are AST children of the namespace, not the class, so parent_class must be
resolved via semantic_parent or qualified_name prefix matching.
"""

import pytest
from pathlib import Path
import sys
import os

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer
from tests.utils.test_helpers import temp_compile_commands


# =============================================================================
# C++ fixture code
# =============================================================================

HEADER_CODE = """\
#pragma once

namespace mylib {

class Calculator {
public:
    Calculator();
    ~Calculator();
    int add(int a, int b);
    int subtract(int a, int b) const;
    static Calculator create();
private:
    void reset();
};

class Printer {
public:
    void print_value(int v);
};

// Inline methods (control group)
class InlineHelper {
public:
    int get_value() const { return value_; }
    void set_value(int v) { value_ = v; }
private:
    int value_ = 0;
};

} // namespace mylib
"""

SOURCE_CODE = """\
#include "widget.h"

namespace mylib {

Calculator::Calculator() {}

Calculator::~Calculator() {}

int Calculator::add(int a, int b) {
    return a + b;
}

int Calculator::subtract(int a, int b) const {
    return a - b;
}

Calculator Calculator::create() {
    return Calculator();
}

void Calculator::reset() {
    // private method
}

void Printer::print_value(int v) {
    // out-of-line definition
}

} // namespace mylib
"""


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def analyzer(tmp_path_factory):
    """Create analyzer with out-of-line method test project."""
    tmp_path = tmp_path_factory.mktemp("out_of_line")

    (tmp_path / "widget.h").write_text(HEADER_CODE)
    (tmp_path / "widget.cpp").write_text(SOURCE_CODE)

    temp_compile_commands(
        tmp_path,
        [
            {
                "file": "widget.cpp",
                "directory": str(tmp_path),
                "arguments": ["-std=c++17", "-I", str(tmp_path)],
            }
        ],
    )

    a = CppAnalyzer(str(tmp_path))
    a.index_project()
    yield a

    if hasattr(a, "cache_manager"):
        a.cache_manager.close()


# =============================================================================
# Tests
# =============================================================================


class TestOutOfLineMethodsInGetClassInfo:
    """get_class_info should list methods defined outside the class body."""

    def test_out_of_line_methods_appear(self, analyzer):
        """Methods defined in .cpp should appear in get_class_info."""
        info = analyzer.get_class_info("Calculator")
        assert info is not None, "Calculator not found"
        method_names = {m["name"] for m in info.get("methods", [])}
        assert "add" in method_names, f"'add' not in methods: {method_names}"
        assert "subtract" in method_names, f"'subtract' not in methods: {method_names}"

    def test_constructor_destructor_appear(self, analyzer):
        """Constructors and destructors should appear in methods."""
        info = analyzer.get_class_info("Calculator")
        assert info is not None
        method_names = {m["name"] for m in info.get("methods", [])}
        assert "Calculator" in method_names, f"Constructor not in methods: {method_names}"
        assert "~Calculator" in method_names, f"Destructor not in methods: {method_names}"

    def test_static_method_appears(self, analyzer):
        """Static out-of-line methods should appear."""
        info = analyzer.get_class_info("Calculator")
        assert info is not None
        method_names = {m["name"] for m in info.get("methods", [])}
        assert "create" in method_names, f"'create' not in methods: {method_names}"

    def test_private_method_appears(self, analyzer):
        """Private out-of-line methods should appear."""
        info = analyzer.get_class_info("Calculator")
        assert info is not None
        method_names = {m["name"] for m in info.get("methods", [])}
        assert "reset" in method_names, f"'reset' not in methods: {method_names}"

    def test_separate_class_methods(self, analyzer):
        """Printer methods should only appear in Printer, not Calculator."""
        calc_info = analyzer.get_class_info("Calculator")
        assert calc_info is not None
        calc_methods = {m["name"] for m in calc_info.get("methods", [])}
        assert "print_value" not in calc_methods

        printer_info = analyzer.get_class_info("Printer")
        assert printer_info is not None
        printer_methods = {m["name"] for m in printer_info.get("methods", [])}
        assert "print_value" in printer_methods


class TestInlineMethodsStillWork:
    """Regression: inline methods must still work correctly."""

    def test_inline_methods_appear(self, analyzer):
        """Methods defined inline in the class body should still appear."""
        info = analyzer.get_class_info("InlineHelper")
        assert info is not None
        method_names = {m["name"] for m in info.get("methods", [])}
        assert "get_value" in method_names
        assert "set_value" in method_names


class TestGetFunctionSignatureOutOfLine:
    """get_function_signature should work for out-of-line methods."""

    def test_signature_with_class_name(self, analyzer):
        """Signature lookup with class_name filter should find out-of-line methods."""
        sigs = analyzer.get_function_signature("add", class_name="Calculator")
        assert len(sigs) > 0, "No signatures found for Calculator::add"
        # Should contain the class scope in the signature
        assert any("Calculator" in s for s in sigs), f"No Calculator scope in sigs: {sigs}"


class TestParentClassPreservedInDedup:
    """Definition-wins dedup should preserve parent_class from declarations."""

    def test_parent_class_not_empty_after_dedup(self, analyzer):
        """After dedup, methods should have non-empty parent_class."""
        # Search for 'add' method and check parent_class
        results = analyzer.search_functions("add")
        add_results = [r for r in results if r["name"] == "add"]
        assert len(add_results) > 0, "No 'add' function found"
        for r in add_results:
            if r.get("qualified_name", "").startswith("mylib::Calculator"):
                assert r.get("parent_class") == "Calculator", (
                    f"parent_class should be 'Calculator', got '{r.get('parent_class')}'"
                )
                break
        else:
            pytest.fail("Could not find mylib::Calculator::add in results")
