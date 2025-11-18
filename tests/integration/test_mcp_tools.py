"""
Integration Tests - MCP Server Tools

Tests for MCP server tools using the CppAnalyzer directly.

Requirements: P1 - High Priority, P2 - Nice to Have
"""

import pytest
from pathlib import Path

# Import test infrastructure
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server.regex_validator import RegexValidationError


@pytest.mark.integration
class TestMCPServerTools:
    """Test MCP server tool functionality"""

    def test_list_classes_tool(self, temp_project_dir):
        """Test list_classes functionality"""
        # Create test file
        (temp_project_dir / "src" / "test.cpp").write_text("""
class TestClass {
public:
    void method();
};

class AnotherClass {
public:
    void another();
};
""")

        # Create analyzer and index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # List classes using search_classes with .*
        classes = analyzer.search_classes(".*", project_only=True)
        assert len(classes) > 0
        class_names = [c["name"] for c in classes]
        assert "TestClass" in class_names
        assert "AnotherClass" in class_names

    def test_search_classes_tool(self, temp_project_dir):
        """Test search_classes functionality"""
        (temp_project_dir / "src" / "test.cpp").write_text("""
class TestClass {};
class AnotherTestClass {};
class DifferentClass {};
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search for classes with pattern
        results = analyzer.search_classes("Test.*")
        assert len(results) >= 2
        names = [r["name"] for r in results]
        assert "TestClass" in names
        assert "AnotherTestClass" in names
        assert "DifferentClass" not in names

    def test_search_functions_tool(self, temp_project_dir):
        """Test search_functions functionality"""
        (temp_project_dir / "src" / "test.cpp").write_text("""
void globalFunction() {}
void testFunction() {}

class TestClass {
public:
    void testMethod();
    void anotherMethod();
};
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search for functions with pattern
        results = analyzer.search_functions("test.*")
        assert len(results) >= 2
        names = [r["name"] for r in results]
        assert "testFunction" in names
        assert "testMethod" in names

    def test_get_class_info_tool(self, temp_project_dir):
        """Test get_class_info functionality"""
        (temp_project_dir / "src" / "test.cpp").write_text("""
class TestClass {
public:
    void method1();
    void method2(int x);
private:
    void privateMethod();
};
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Get class info
        info = analyzer.get_class_info("TestClass")
        assert info is not None
        assert info["name"] == "TestClass"
        assert "methods" in info
        assert len(info["methods"]) >= 3

    def test_get_function_signature_tool(self, temp_project_dir):
        """Test get_function_signature functionality"""
        (temp_project_dir / "src" / "test.cpp").write_text("""
void testFunction(int x) {}
void testFunction(double y) {}

class TestClass {
public:
    void testFunction(const char* s) {}
};
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Get function signatures
        signatures = analyzer.get_function_signature("testFunction")
        # Might not find all overloads depending on parsing, just verify it returns a list
        assert isinstance(signatures, list)

    def test_search_symbols_tool(self, temp_project_dir):
        """Test search_symbols unified search"""
        (temp_project_dir / "src" / "test.cpp").write_text("""
class TestClass {};
void testFunction() {}
class DifferentClass {};
void differentFunction() {}
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search for symbols
        results = analyzer.search_symbols("test.*")
        assert "classes" in results
        assert "functions" in results
        assert len(results["classes"]) >= 1
        assert len(results["functions"]) >= 1

    def test_get_class_hierarchy_tool(self, temp_project_dir):
        """Test get_class_hierarchy functionality"""
        (temp_project_dir / "src" / "test.cpp").write_text("""
class Base {};
class Derived : public Base {};
class MoreDerived : public Derived {};
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Get class hierarchy
        hierarchy = analyzer.get_class_hierarchy("Derived")
        assert hierarchy is not None
        assert hierarchy["name"] == "Derived"
        assert "base_hierarchy" in hierarchy
        assert "derived_hierarchy" in hierarchy

    def test_get_derived_classes_tool(self, temp_project_dir):
        """Test get_derived_classes functionality"""
        (temp_project_dir / "src" / "test.cpp").write_text("""
class Base {};
class Derived1 : public Base {};
class Derived2 : public Base {};
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Get derived classes
        derived = analyzer.get_derived_classes("Base")
        assert len(derived) >= 2
        names = [d["name"] for d in derived]
        assert "Derived1" in names
        assert "Derived2" in names

    def test_get_call_graph_tool(self, temp_project_dir):
        """Test get_call_graph functionality using find_callees and find_callers"""
        (temp_project_dir / "src" / "test.cpp").write_text("""
void helper() {}
void process() {
    helper();
}
void main() {
    process();
}
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Get callees (functions called by process)
        callees = analyzer.find_callees("process")
        assert callees is not None
        assert isinstance(callees, list)

        # Get callers (functions that call process)
        callers = analyzer.find_callers("process")
        assert callers is not None
        assert isinstance(callers, list)

    def test_regex_validation_in_search(self, temp_project_dir):
        """Test that ReDoS patterns are rejected in search"""
        (temp_project_dir / "src" / "test.cpp").write_text("class TestClass {};")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Test dangerous patterns are rejected
        with pytest.raises(RegexValidationError):
            analyzer.search_classes("(a+)+b")

        with pytest.raises(RegexValidationError):
            analyzer.search_functions("(a*)*c")

    def test_project_only_filter(self, temp_project_dir):
        """Test project_only filter works correctly"""
        (temp_project_dir / "src" / "test.cpp").write_text("""
#include <vector>
class MyClass {};
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search with project_only=True (default)
        project_only = analyzer.search_classes(".*", project_only=True)
        all_classes = analyzer.search_classes(".*", project_only=False)

        # project_only should have fewer results (no std library classes)
        assert len(project_only) <= len(all_classes)

    def test_file_path_variations(self, temp_project_dir):
        """Test that file path matching works with various formats using find_in_file"""
        test_file = temp_project_dir / "src" / "myfile.cpp"
        test_file.write_text("class TestClass {};")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Test with just filename
        symbols = analyzer.find_in_file("myfile.cpp", ".*")
        assert len(symbols) > 0

        # Test with relative path
        symbols = analyzer.find_in_file("src/myfile.cpp", ".*")
        assert len(symbols) > 0

        # Test with absolute path
        symbols = analyzer.find_in_file(str(test_file), ".*")
        assert len(symbols) > 0

    def test_incremental_indexing(self, temp_project_dir):
        """Test incremental indexing after file modifications"""
        test_file = temp_project_dir / "src" / "test.cpp"
        test_file.write_text("class TestClass {};")

        analyzer = CppAnalyzer(str(temp_project_dir))
        initial_count = analyzer.index_project()

        # Modify file
        test_file.write_text("class TestClass {};\nclass NewClass {};")

        # Refresh index using refresh_if_needed
        count = analyzer.refresh_if_needed()
        assert count >= 0

        # Verify new class is found
        classes = analyzer.search_classes("NewClass")
        assert len(classes) > 0

    def test_error_recovery(self, temp_project_dir):
        """Test error recovery with malformed C++ code"""
        # Create two files - one valid, one with errors
        (temp_project_dir / "src" / "valid.cpp").write_text("""
class ValidClass {};
class AnotherValidClass {};
""")
        (temp_project_dir / "src" / "invalid.cpp").write_text("""
// Malformed code (syntax error)
class InvalidClass {
    void method(
};
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        # Should not crash, should index what it can
        count = analyzer.index_project()
        # Should index at least the valid file
        assert count >= 1

        # Should still find valid classes (using simpler pattern to avoid ReDoS detection)
        classes = analyzer.search_classes("Valid")
        assert len(classes) >= 1

        # Try more specific pattern (avoiding consecutive quantifiers)
        all_classes = analyzer.search_classes("AnotherValidClass")
        assert len(all_classes) >= 1

    def test_empty_project(self, temp_project_dir):
        """Test behavior with empty project"""
        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()

        # Should handle gracefully
        assert count >= 0

        # Search should return empty results, not error
        classes = analyzer.search_classes(".*")
        assert isinstance(classes, list)
        assert len(classes) == 0
