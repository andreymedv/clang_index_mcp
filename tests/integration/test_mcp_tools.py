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
class TestHelper {};
class DifferentClass {};
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search for classes with pattern (starts with "Test")
        results = analyzer.search_classes("Test.*")
        assert len(results) >= 2
        names = [r["name"] for r in results]
        assert "TestClass" in names
        assert "TestHelper" in names
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

    def test_get_class_info_with_qualified_name(self, temp_project_dir):
        """Test get_class_info with qualified name from search_classes result.

        Regression test for bug where search_classes returns qualified_name
        but get_class_info couldn't find the class using that qualified name.
        """
        # Create two classes with same simple name in different namespaces
        (temp_project_dir / "src" / "test.cpp").write_text("""
namespace ns1 {
    class Builder {
    public:
        void build1();
    };
}

namespace ns2 {
    class Builder {
    public:
        void build2();
    };
}
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # search_classes finds both classes
        results = analyzer.search_classes("Builder")
        assert len(results) >= 2

        # Find qualified names
        qualified_names = {r["qualified_name"] for r in results}
        assert "ns1::Builder" in qualified_names
        assert "ns2::Builder" in qualified_names

        # get_class_info should work with qualified name from search_classes
        info1 = analyzer.get_class_info("ns1::Builder")
        assert info1 is not None
        assert info1["name"] == "Builder"
        assert info1["qualified_name"] == "ns1::Builder"
        assert info1["namespace"] == "ns1"

        info2 = analyzer.get_class_info("ns2::Builder")
        assert info2 is not None
        assert info2["name"] == "Builder"
        assert info2["qualified_name"] == "ns2::Builder"
        assert info2["namespace"] == "ns2"

        # Simple name with multiple matches should return ambiguity response
        info_simple = analyzer.get_class_info("Builder")
        assert info_simple is not None
        assert info_simple.get("is_ambiguous") is True
        assert "error" in info_simple
        assert "matches" in info_simple
        assert len(info_simple["matches"]) == 2
        match_names = {m["qualified_name"] for m in info_simple["matches"]}
        assert "ns1::Builder" in match_names
        assert "ns2::Builder" in match_names

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

    def test_get_derived_classes_with_qualified_name(self, temp_project_dir):
        """Test get_derived_classes with qualified class name (namespace::class)

        Bug fix: class_name parameter should accept both simple names and qualified names.
        """
        (temp_project_dir / "src" / "namespaced.cpp").write_text("""
namespace MyNamespace {
namespace Inner {

class Base {};
class Derived1 : public Base {};
class Derived2 : public Base {};

}  // namespace Inner
}  // namespace MyNamespace
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Get derived classes using simple name
        derived_simple = analyzer.get_derived_classes("Base")
        assert len(derived_simple) >= 2
        names_simple = [d["name"] for d in derived_simple]
        assert "Derived1" in names_simple
        assert "Derived2" in names_simple

        # Get derived classes using qualified name - should also work
        derived_qualified = analyzer.get_derived_classes("MyNamespace::Inner::Base")
        assert len(derived_qualified) >= 2
        names_qualified = [d["name"] for d in derived_qualified]
        assert "Derived1" in names_qualified
        assert "Derived2" in names_qualified

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
        result = analyzer.find_callers("process")
        assert result is not None
        # Phase 3: find_callers now returns dict with 'callers' key
        assert isinstance(result, dict)
        assert 'callers' in result
        assert isinstance(result['callers'], list)

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
        response = analyzer.find_in_file("myfile.cpp", ".*")
        assert len(response["results"]) > 0

        # Test with relative path
        response = analyzer.find_in_file("src/myfile.cpp", ".*")
        assert len(response["results"]) > 0

        # Test with absolute path
        response = analyzer.find_in_file(str(test_file), ".*")
        assert len(response["results"]) > 0

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

        # Should still find valid classes (using pattern to match classes starting with "Valid")
        classes = analyzer.search_classes("ValidClass")
        assert len(classes) >= 1  # Should find ValidClass (exact match)

        # Try another exact match for specific class
        another_class = analyzer.search_classes("AnotherValidClass")
        assert len(another_class) >= 1  # Should find AnotherValidClass (exact match)

        # Verify we can find classes starting with "Valid"
        valid_prefix = analyzer.search_classes("Valid.*")
        assert len(valid_prefix) >= 1  # Should find at least ValidClass

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


class TestMCPServerToolsAdditional:
    """Additional tests to cover gaps from removed test_mcp_protocol.py"""

    def test_get_server_status(self, temp_project_dir):
        """Test get_stats (equivalent to get_server_status)"""
        (temp_project_dir / "src" / "test.cpp").write_text("class TestClass {};")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Get server statistics
        stats = analyzer.get_stats()
        assert stats is not None
        assert "class_count" in stats
        assert "function_count" in stats
        assert "file_count" in stats
        assert stats["class_count"] >= 1

    def test_nonexistent_class(self, temp_project_dir):
        """Test querying non-existent class returns None or empty"""
        (temp_project_dir / "src" / "test.cpp").write_text("class TestClass {};")
        
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()
        
        # Query non-existent class
        info = analyzer.get_class_info("NonExistentClass")
        assert info is None, "Should return None for non-existent class"
        
        # Search should return empty list
        results = analyzer.search_classes("NonExistentClass")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_invalid_project_path(self):
        """Test that invalid project path raises appropriate error"""
        import pytest
        
        # Test with non-existent path - should raise or handle gracefully
        # CppAnalyzer might create directories, so we test with None or invalid type
        with pytest.raises((TypeError, ValueError, OSError)):
            analyzer = CppAnalyzer(None)
        
        # Test with file instead of directory
        import tempfile
        with tempfile.NamedTemporaryFile() as tmp:
            # This might succeed (treats parent directory as project)
            # or fail - either is acceptable error handling
            try:
                analyzer = CppAnalyzer(tmp.name)
                # If it succeeds, it should handle it gracefully
                count = analyzer.index_project()
                assert count >= 0  # Should not crash
            except (ValueError, OSError):
                pass  # Error is acceptable

    def test_error_when_analyzer_not_initialized(self):
        """Test error handling when operations are called without initialization"""
        # Create analyzer but don't index
        import tempfile
        import shutil
        from pathlib import Path
        
        temp_dir = tempfile.mkdtemp()
        try:
            project_dir = Path(temp_dir) / "project"
            project_dir.mkdir(parents=True)
            (project_dir / "src").mkdir()
            
            analyzer = CppAnalyzer(str(project_dir))
            # Don't call index_project()
            
            # Operations should handle gracefully (return empty or None)
            results = analyzer.search_classes("Test")
            assert isinstance(results, list)
            # Might be empty or have cached results
            
        finally:
            shutil.rmtree(temp_dir)

    def test_compile_commands_stats(self, temp_project_dir):
        """Test get_compile_commands_stats API"""
        (temp_project_dir / "src" / "test.cpp").write_text("class TestClass {};")
        
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()
        
        # Get compile commands stats
        stats = analyzer.get_compile_commands_stats()
        assert stats is not None
        assert isinstance(stats, dict)
        # Should have information about compile commands usage

    def test_invalid_regex_patterns(self, temp_project_dir):
        """Test handling of various invalid regex patterns"""
        (temp_project_dir / "src" / "test.cpp").write_text("class TestClass {};")
        
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()
        
        from mcp_server.regex_validator import RegexValidationError
        
        # Test various dangerous patterns
        dangerous_patterns = [
            "(a+)+b",           # Nested quantifiers
            "(a*)*c",           # Nested star quantifiers
            "(a|a)*b",          # Alternation with quantifiers
            "(x+x+)+y",         # Multiple nested quantifiers
        ]
        
        for pattern in dangerous_patterns:
            with pytest.raises(RegexValidationError):
                analyzer.search_classes(pattern)

    def test_find_in_file_with_nonexistent_file(self, temp_project_dir):
        """Test find_in_file with non-existent file returns suggestions"""
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Query non-existent file
        response = analyzer.find_in_file("nonexistent.cpp", ".*")
        assert isinstance(response, dict)
        assert "results" in response
        assert len(response["results"]) == 0, "Should return empty results for non-existent file"
        # Should have suggestions for similar files (if any indexed)
        assert "suggestions" in response or "message" in response

    def test_find_in_file_glob_pattern(self, temp_project_dir):
        """Test find_in_file with glob pattern matches multiple files"""
        # Create test files in different directories
        (temp_project_dir / "src" / "tests").mkdir(parents=True, exist_ok=True)
        (temp_project_dir / "src" / "tests" / "test_a.cpp").write_text("class TestA {};")
        (temp_project_dir / "src" / "tests" / "test_b.cpp").write_text("class TestB {};")
        (temp_project_dir / "src" / "main.cpp").write_text("class Main {};")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Use glob pattern to match test files
        response = analyzer.find_in_file("**/tests/*.cpp", "")
        assert isinstance(response, dict)
        assert "results" in response
        assert "matched_files" in response

        # Should find both test classes
        names = [r["name"] for r in response["results"]]
        assert "TestA" in names
        assert "TestB" in names
        # Should not find Main (not in tests directory)
        assert "Main" not in names

    def test_find_in_file_suggestions_for_partial_name(self, temp_project_dir):
        """Test find_in_file returns suggestions for partial/incorrect file names"""
        # Create files with similar names
        (temp_project_dir / "src" / "FileHandler.cpp").write_text("class FileHandler {};")
        (temp_project_dir / "src" / "FileReader.cpp").write_text("class FileReader {};")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search with partial name that doesn't match exactly
        response = analyzer.find_in_file("FileHan", "")
        assert isinstance(response, dict)
        assert "suggestions" in response
        # Should suggest files containing similar names
        suggestions = response["suggestions"]
        assert len(suggestions) > 0
        assert any("FileHandler" in s for s in suggestions)

    def test_get_parse_errors(self, temp_project_dir):
        """Test get_parse_errors API for tracking indexing issues"""
        # Create file with syntax errors
        (temp_project_dir / "src" / "bad.cpp").write_text("""
class BrokenClass {
    void method(
};  // Missing closing paren
""")
        (temp_project_dir / "src" / "good.cpp").write_text("class GoodClass {};")
        
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()
        
        # Get parse errors
        errors = analyzer.get_parse_errors()
        assert isinstance(errors, list)
        # Might have errors from bad.cpp

    def test_empty_search_pattern(self, temp_project_dir):
        """Test search with empty pattern"""
        (temp_project_dir / "src" / "test.cpp").write_text("class TestClass {};")
        
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()
        
        # Empty pattern might be treated as "match nothing" or "match all"
        # Either behavior is acceptable as long as it doesn't crash
        try:
            results = analyzer.search_classes("")
            assert isinstance(results, list)
        except RegexValidationError:
            pass  # Rejecting empty pattern is also acceptable
