"""
Base Functionality Tests - Core Features

Tests for basic MCP server functionality including:
- Class and function indexing
- Symbol search operations
- Class hierarchy traversal
- Call graph analysis

Requirements: REQ-1.x, REQ-2.x, REQ-3.x
Priority: P1
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


@pytest.mark.base_functionality
class TestBasicIndexing:
    """Test basic indexing functionality - REQ-1.1, REQ-2.1"""

    def test_basic_class_indexing(self, temp_project_dir):
        """Test indexing simple class definitions - Task 1.1.1"""
        # Create a simple C++ file with a class
        (temp_project_dir / "src" / "test_class.cpp").write_text("""
class SimpleClass {
public:
    void method();
    int value;
};
""")

        # Index the project
        analyzer = CppAnalyzer(str(temp_project_dir))
        indexed_count = analyzer.index_project()

        # Verify indexing succeeded
        assert indexed_count > 0, "Should have indexed at least one file"

        # Search for the class
        results = analyzer.search_classes("SimpleClass")

        # Verify class was found
        assert len(results) > 0, "SimpleClass should be found"
        assert results[0]['name'] == "SimpleClass"
        assert results[0]['kind'] == "class"
        _loc = results[0].get("definition") or results[0].get("declaration") or {}
        assert "test_class.cpp" in _loc['file']

    def test_basic_function_indexing(self, temp_project_dir):
        """Test indexing simple function definitions - Task 1.1.2"""
        # Create a simple C++ file with functions
        (temp_project_dir / "src" / "functions.cpp").write_text("""
int add(int a, int b) {
    return a + b;
}

void printHello() {
    // print
}
""")

        # Index the project
        analyzer = CppAnalyzer(str(temp_project_dir))
        indexed_count = analyzer.index_project()

        # Verify indexing succeeded
        assert indexed_count > 0, "Should have indexed at least one file"

        # Search for functions
        add_results = analyzer.search_functions("add")
        hello_results = analyzer.search_functions("printHello")

        # Verify functions were found
        assert len(add_results) > 0, "add function should be found"
        assert add_results[0]['name'] == "add"
        assert add_results[0]['kind'] == "function"

        assert len(hello_results) > 0, "printHello function should be found"
        assert hello_results[0]['name'] == "printHello"


@pytest.mark.base_functionality
class TestSearchOperations:
    """Test search operations - REQ-2.x"""

    def test_search_classes_basic(self, temp_project_dir):
        """Test basic class search with patterns - Task 1.1.3"""
        # Create multiple classes
        (temp_project_dir / "src" / "classes.cpp").write_text("""
class TestClass1 {
public:
    void method1();
};

class TestClass2 {
public:
    void method2();
};

class OtherClass {
public:
    void method3();
};
""")

        # Index the project
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search with pattern matching
        test_classes = analyzer.search_classes("Test.*")
        all_classes = analyzer.search_classes(".*")

        # Verify pattern matching works
        assert len(test_classes) >= 2, "Should find at least TestClass1 and TestClass2"
        assert len(all_classes) >= 3, "Should find all three classes"

        # Verify search found correct classes
        test_class_names = [c['name'] for c in test_classes]
        assert "TestClass1" in test_class_names
        assert "TestClass2" in test_class_names

    def test_search_functions_basic(self, temp_project_dir):
        """Test basic function search with patterns - Task 1.1.4"""
        # Create multiple functions
        (temp_project_dir / "src" / "functions.cpp").write_text("""
void processData() {}
void processList() {}
void handleEvent() {}
int calculate() { return 0; }
""")

        # Index the project
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search with pattern matching
        process_funcs = analyzer.search_functions("process.*")
        all_funcs = analyzer.search_functions(".*")

        # Verify pattern matching works
        assert len(process_funcs) >= 2, "Should find processData and processList"
        assert len(all_funcs) >= 4, "Should find all four functions"

        # Verify search found correct functions
        process_names = [f['name'] for f in process_funcs]
        assert "processData" in process_names
        assert "processList" in process_names

    def test_find_in_file_basic(self, temp_project_dir):
        """Test finding symbols in specific file - Task 1.1.5"""
        # Create multiple files
        file1 = temp_project_dir / "src" / "file1.cpp"
        file2 = temp_project_dir / "src" / "file2.cpp"

        file1.write_text("""
class ClassInFile1 {
public:
    void method1();
};

void functionInFile1() {}
""")

        file2.write_text("""
class ClassInFile2 {
public:
    void method2();
};

void functionInFile2() {}
""")

        # Index the project
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search in specific file
        file1_response = analyzer.find_in_file(str(file1), ".*")
        file2_response = analyzer.find_in_file(str(file2), ".*")
        file1_symbols = file1_response["results"]
        file2_symbols = file2_response["results"]

        # Verify file-specific search works
        assert len(file1_symbols) >= 2, "Should find class and function in file1"
        assert len(file2_symbols) >= 2, "Should find class and function in file2"

        # Verify correct symbols found in each file
        file1_names = [s['name'] for s in file1_symbols]
        file2_names = [s['name'] for s in file2_symbols]

        assert "ClassInFile1" in file1_names
        assert "functionInFile1" in file1_names
        assert "ClassInFile2" in file2_names
        assert "functionInFile2" in file2_names


@pytest.mark.base_functionality
class TestHierarchyAnalysis:
    """Test class hierarchy analysis - REQ-3.1"""

    def test_get_class_hierarchy_basic(self, temp_project_dir):
        """Test getting inheritance hierarchy for a class - Task 1.1.6"""
        # Create inheritance hierarchy
        (temp_project_dir / "src" / "hierarchy.cpp").write_text("""
class BaseClass {
public:
    virtual void baseMethod();
};

class DerivedClass : public BaseClass {
public:
    void derivedMethod();
};

class FurtherDerived : public DerivedClass {
public:
    void furtherMethod();
};
""")

        # Index the project
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Get hierarchy for DerivedClass
        hierarchy = analyzer.get_class_hierarchy("DerivedClass")

        # Verify hierarchy was retrieved
        assert "class_info" in hierarchy, "Should have class_info"
        assert hierarchy['class_info']['name'] == "DerivedClass"

        # Verify base classes
        assert "base_classes" in hierarchy
        assert "BaseClass" in hierarchy['base_classes'], "Should show BaseClass as base"

        # Verify derived classes
        assert "derived_classes" in hierarchy
        derived_names = [d['name'] for d in hierarchy['derived_classes']]
        assert "FurtherDerived" in derived_names, "Should show FurtherDerived as derived"


@pytest.mark.base_functionality
class TestCallGraphAnalysis:
    """Test call graph analysis - REQ-3.2"""

    def test_find_callers_basic(self, temp_project_dir):
        """Test finding callers of a function - Task 1.1.7"""
        # Create function call relationships
        (temp_project_dir / "src" / "calls.cpp").write_text("""
void helperFunction() {
    // does something
}

void caller1() {
    helperFunction();
}

void caller2() {
    helperFunction();
}

void unrelatedFunction() {
    // does not call helperFunction
}
""")

        # Index the project
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Find callers of helperFunction
        result = analyzer.find_callers("helperFunction")

        # Phase 3: find_callers now returns dict with 'callers' key
        assert isinstance(result, dict), "find_callers should return dict (Phase 3)"
        callers = result['callers']

        # Verify callers were found
        caller_names = [c['name'] for c in callers]
        assert "caller1" in caller_names, "caller1 should be in callers list"
        assert "caller2" in caller_names, "caller2 should be in callers list"
        assert "unrelatedFunction" not in caller_names, "unrelatedFunction should not be in callers"

    def test_find_callees_basic(self, temp_project_dir):
        """Test finding callees of a function - Task 1.1.8"""
        # Create function call relationships
        (temp_project_dir / "src" / "callees.cpp").write_text("""
void function1() {}
void function2() {}
void function3() {}

void mainFunction() {
    function1();
    function2();
    // function3 is not called
}
""")

        # Index the project
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Find callees of mainFunction
        result = analyzer.find_callees("mainFunction")

        # Verify result format (should be dict with "callees" key)
        assert isinstance(result, dict), "find_callees should return a dict"
        assert "callees" in result, "Result should have 'callees' key"
        callees_list = result["callees"]

        # Verify callees were found
        callee_names = [c['name'] for c in callees_list]
        assert "function1" in callee_names, "function1 should be in callees list"
        assert "function2" in callee_names, "function2 should be in callees list"
        # Note: function3 might or might not be in the list since it's not called
