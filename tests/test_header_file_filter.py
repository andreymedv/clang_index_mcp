"""
Test file_name filtering for search_classes and search_functions

Tests the file_name parameter that filters results to only
symbols defined in files matching the specified name.
Works with any file type (.h, .cpp, .cc, etc.).
"""

import pytest
from pathlib import Path

# Import test infrastructure
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.mark.base_functionality
class TestFileNameFilter:
    """Test file_name parameter filtering"""

    def test_search_classes_with_file_name_filter(self, temp_project_dir):
        """Test filtering classes by header file"""
        # Create a header file with a class
        (temp_project_dir / "src" / "MyClass.h").write_text("""
#ifndef MYCLASS_H
#define MYCLASS_H

class MyClass {
public:
    void myMethod();
    int value;
};

class AnotherClass {
public:
    void anotherMethod();
};

#endif
""")

        # Create a different header file
        (temp_project_dir / "src" / "OtherClass.h").write_text("""
#ifndef OTHERCLASS_H
#define OTHERCLASS_H

class OtherClass {
public:
    void otherMethod();
};

#endif
""")

        # Create a source file with classes (these should NOT be included when filtering by header)
        (temp_project_dir / "src" / "implementation.cpp").write_text("""
#include "MyClass.h"

void MyClass::myMethod() {}

class ImplementationClass {
public:
    void implMethod();
};
""")

        # Index the project
        analyzer = CppAnalyzer(str(temp_project_dir))
        indexed_count = analyzer.index_project()
        assert indexed_count > 0, "Should have indexed files"

        # Search for all classes (no filter)
        all_results = analyzer.search_classes(".*")
        assert len(all_results) >= 3, "Should find at least MyClass, AnotherClass, OtherClass"

        # Search for classes in MyClass.h only
        myclass_results = analyzer.search_classes(".*", file_name="MyClass.h")
        assert len(myclass_results) == 2, f"Should find exactly 2 classes in MyClass.h, found {len(myclass_results)}"

        # Verify only classes from MyClass.h are returned
        class_names = [r['qualified_name'].split('::')[-1] for r in myclass_results]
        assert "MyClass" in class_names, "MyClass should be found"
        assert "AnotherClass" in class_names, "AnotherClass should be found"
        assert "OtherClass" not in class_names, "OtherClass should NOT be found"
        assert "ImplementationClass" not in class_names, "ImplementationClass should NOT be found"

        # Verify file paths
        for result in myclass_results:
            _res_loc = result.get("definition") or result.get("declaration") or {}
            assert _res_loc['file'].endswith("MyClass.h"), f"Result file should be MyClass.h, got {_res_loc['file']}"

    def test_search_classes_with_partial_path(self, temp_project_dir):
        """Test file_name filter with partial paths"""
        # Create a nested directory structure
        (temp_project_dir / "src" / "utils").mkdir(parents=True, exist_ok=True)
        (temp_project_dir / "src" / "utils" / "Helper.h").write_text("""
class HelperClass {
public:
    void help();
};
""")

        (temp_project_dir / "src" / "Main.h").write_text("""
class MainClass {
public:
    void main();
};
""")

        # Index the project
        analyzer = CppAnalyzer(str(temp_project_dir))
        indexed_count = analyzer.index_project()
        assert indexed_count > 0

        # Filter by full filename only
        helper_results = analyzer.search_classes(".*", file_name="Helper.h")
        assert len(helper_results) == 1
        assert helper_results[0]['qualified_name'].split('::')[-1] == "HelperClass"

        # Filter by partial path
        utils_results = analyzer.search_classes(".*", file_name="utils/Helper.h")
        assert len(utils_results) == 1
        assert utils_results[0]['qualified_name'].split('::')[-1] == "HelperClass"

    def test_search_functions_with_file_name_filter(self, temp_project_dir):
        """Test filtering functions by header file"""
        # Create a header file with function declarations
        (temp_project_dir / "src" / "functions.h").write_text("""
#ifndef FUNCTIONS_H
#define FUNCTIONS_H

int add(int a, int b);
int subtract(int a, int b);

#endif
""")

        # Create another header
        (temp_project_dir / "src" / "other.h").write_text("""
#ifndef OTHER_H
#define OTHER_H

int multiply(int a, int b);

#endif
""")

        # Create source file with implementations (inline functions in .cpp should not match header filter)
        (temp_project_dir / "src" / "functions.cpp").write_text("""
#include "functions.h"

int add(int a, int b) { return a + b; }
int subtract(int a, int b) { return a - b; }

// This is defined only in .cpp, not in header
int divide(int a, int b) { return a / b; }
""")

        # Index the project
        analyzer = CppAnalyzer(str(temp_project_dir))
        indexed_count = analyzer.index_project()
        assert indexed_count > 0

        # Search for all functions
        all_results = analyzer.search_functions(".*")
        all_names = [r['qualified_name'].split('::')[-1] for r in all_results]

        # Search for functions in functions.h only
        functions_h_results = analyzer.search_functions(".*", file_name="functions.h")
        functions_h_names = [r['qualified_name'].split('::')[-1] for r in functions_h_results]

        # Verify only functions from functions.h are returned
        assert "add" in functions_h_names or "subtract" in functions_h_names, \
            "Should find functions declared in functions.h"

        # Functions defined only in .cpp should not match when filtering by .h
        # Note: This depends on whether declarations or definitions are indexed
        for result in functions_h_results:
            # The result was matched because its declaration or definition is in functions.h
            # Check that at least one location is in functions.h
            _decl_file = (result.get("declaration") or {}).get("file", "")
            _def_file = (result.get("definition") or {}).get("file", "")
            assert _decl_file.endswith("functions.h") or _def_file.endswith("functions.h"), \
                f"Result should have a location in functions.h, got decl={_decl_file}, def={_def_file}"

    def test_search_classes_no_filter_returns_all(self, temp_project_dir):
        """Test that omitting file_name returns all classes"""
        # Create multiple files
        (temp_project_dir / "src" / "A.h").write_text("class A {};")
        (temp_project_dir / "src" / "B.h").write_text("class B {};")
        (temp_project_dir / "src" / "C.cpp").write_text("class C {};")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search without filter
        all_results = analyzer.search_classes(".*")
        class_names = [r['qualified_name'].split('::')[-1] for r in all_results]

        # Should find all classes
        assert "A" in class_names
        assert "B" in class_names
        assert "C" in class_names

    def test_file_name_filter_case_sensitivity(self, temp_project_dir):
        """Test that header_file matching is case-sensitive on Linux"""
        # Create files with different cases
        (temp_project_dir / "src" / "MyClass.h").write_text("class MyClass {};")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search with correct case
        correct_results = analyzer.search_classes(".*", file_name="MyClass.h")
        assert len(correct_results) == 1

        # On case-sensitive filesystems, wrong case should not match
        # (This test may behave differently on Windows/macOS)
        import platform
        if platform.system() == "Linux":
            wrong_results = analyzer.search_classes(".*", file_name="myclass.h")
            assert len(wrong_results) == 0, "Case-sensitive match should fail on Linux"

    def test_search_functions_with_class_name_and_header_file(self, temp_project_dir):
        """Test combining class_name and file_name filters"""
        # Create header with multiple classes
        (temp_project_dir / "src" / "Multi.h").write_text("""
class ClassA {
public:
    void methodA();
    void commonMethod();
};

class ClassB {
public:
    void methodB();
    void commonMethod();
};
""")

        # Create another header
        (temp_project_dir / "src" / "Single.h").write_text("""
class ClassC {
public:
    void methodC();
    void commonMethod();
};
""")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search for commonMethod in Multi.h only
        results = analyzer.search_functions("commonMethod", file_name="Multi.h")
        assert len(results) == 2, "Should find commonMethod in both ClassA and ClassB"
        class_names = [r['parent_class'] for r in results]
        assert "ClassA" in class_names
        assert "ClassB" in class_names
        assert "ClassC" not in class_names

        # Search for commonMethod in Multi.h AND ClassA only
        results = analyzer.search_functions("commonMethod", class_name="ClassA", file_name="Multi.h")
        assert len(results) == 1, "Should find only ClassA::commonMethod"
        assert results[0]['parent_class'] == "ClassA"
        _res_loc = results[0].get("definition") or results[0].get("declaration") or {}
        assert _res_loc['file'].endswith("Multi.h")

    def test_search_functions_with_qualified_class_name(self, temp_project_dir):
        """Test that class_name filter works with qualified names (namespace::class)

        Bug fix: class_name parameter should accept both simple names (e.g., "Widget")
        and qualified names (e.g., "myapp::builders::Widget").
        parent_class is stored as simple name, so qualified names must be normalized.
        """
        # Create header with namespaced classes
        (temp_project_dir / "src" / "Namespaced.h").write_text("""
namespace OuterNS {
namespace InnerNS {

class MyClass {
public:
    void myMethod();
    void sharedMethod();
};

}  // namespace InnerNS
}  // namespace OuterNS

namespace OtherNS {

class MyClass {
public:
    void otherMethod();
    void sharedMethod();
};

}  // namespace OtherNS
""")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search with simple class name - should find both MyClass classes' methods
        results_simple = analyzer.search_functions("sharedMethod", class_name="MyClass")
        assert len(results_simple) == 2, "Should find sharedMethod in both MyClass classes"

        # Search with qualified class name - should still work (extracts simple name)
        results_qualified = analyzer.search_functions(
            "sharedMethod", class_name="OuterNS::InnerNS::MyClass"
        )
        # Note: This will still match BOTH MyClass classes because we only extract simple name
        # This is expected behavior - for true disambiguation, use namespace parameter
        assert len(results_qualified) == 2, "Qualified class_name should be normalized"

        # Search with simple name should work
        results_my_method = analyzer.search_functions("myMethod", class_name="MyClass")
        assert len(results_my_method) == 1, "Should find myMethod"
        assert results_my_method[0]['parent_class'] == "MyClass"

        # Qualified class name for unique method should also work
        results_my_method_qualified = analyzer.search_functions(
            "myMethod", class_name="OuterNS::InnerNS::MyClass"
        )
        assert len(results_my_method_qualified) == 1, "Qualified class_name should work"
        assert results_my_method_qualified[0]['parent_class'] == "MyClass"
        assert "OuterNS::InnerNS::MyClass" in results_my_method_qualified[0]['qualified_name']

    def test_file_name_filter_with_cpp_source_files(self, temp_project_dir):
        """Test that header_file parameter works with .cpp source files too"""
        # Create source file with class
        (temp_project_dir / "src" / "source.cpp").write_text("""
class SourceClass {
public:
    void sourceMethod();
};

void standaloneFunction() {}
""")

        # Create header
        (temp_project_dir / "src" / "header.h").write_text("""
class HeaderClass {
public:
    void headerMethod();
};
""")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Filter by .cpp file
        cpp_results = analyzer.search_classes(".*", file_name="source.cpp")
        assert len(cpp_results) == 1
        assert cpp_results[0]['qualified_name'].split('::')[-1] == "SourceClass"
        _cpp_loc = cpp_results[0].get("definition") or cpp_results[0].get("declaration") or {}
        assert _cpp_loc['file'].endswith("source.cpp")

        # Filter by .h file
        h_results = analyzer.search_classes(".*", file_name="header.h")
        assert len(h_results) == 1
        assert h_results[0]['qualified_name'].split('::')[-1] == "HeaderClass"
        _h_loc = h_results[0].get("definition") or h_results[0].get("declaration") or {}
        assert _h_loc['file'].endswith("header.h")

        # Verify functions work too
        func_results = analyzer.search_functions("standaloneFunction", file_name="source.cpp")
        assert len(func_results) == 1
        assert func_results[0]['qualified_name'].split('::')[-1] == "standaloneFunction"

    def test_file_name_filter_returns_empty_for_nonexistent_file(self, temp_project_dir):
        """Test that filtering by nonexistent file returns empty results"""
        (temp_project_dir / "src" / "Real.h").write_text("class RealClass {};")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search for file that doesn't exist
        results = analyzer.search_classes(".*", file_name="NonExistent.h")
        assert len(results) == 0, "Should return empty list for nonexistent file"

    def test_file_name_filter_with_pattern_matching(self, temp_project_dir):
        """Test file_name filter combined with pattern matching"""
        (temp_project_dir / "src" / "Test.h").write_text("""
class TestClassOne {};
class TestClassTwo {};
class OtherClass {};
""")

        (temp_project_dir / "src" / "Other.h").write_text("""
class TestClassThree {};
""")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search for TestClass* in Test.h only
        results = analyzer.search_classes("TestClass.*", file_name="Test.h")
        assert len(results) == 2
        names = [r['qualified_name'].split('::')[-1] for r in results]
        assert "TestClassOne" in names
        assert "TestClassTwo" in names
        assert "TestClassThree" not in names

        # Verify OtherClass is excluded by pattern
        results = analyzer.search_classes("Other.*", file_name="Test.h")
        assert len(results) == 1
        assert results[0]['qualified_name'].split('::')[-1] == "OtherClass"

    def test_file_name_filter_with_absolute_path(self, temp_project_dir):
        """Test file_name filter with absolute path"""
        (temp_project_dir / "src" / "Abs.h").write_text("class AbsClass {};")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Get absolute path
        abs_path = str(temp_project_dir / "src" / "Abs.h")

        # Search with absolute path
        results = analyzer.search_classes(".*", file_name=abs_path)
        assert len(results) == 1
        assert results[0]['qualified_name'].split('::')[-1] == "AbsClass"

    def test_file_name_filter_none_behaves_as_no_filter(self, temp_project_dir):
        """Test that file_name=None behaves same as omitting parameter"""
        (temp_project_dir / "src" / "A.h").write_text("class A {};")
        (temp_project_dir / "src" / "B.h").write_text("class B {};")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search without parameter
        results_no_param = analyzer.search_classes(".*")

        # Search with None
        results_none = analyzer.search_classes(".*", file_name=None)

        # Should return same results
        assert len(results_no_param) == len(results_none)
        names_no_param = sorted([r['qualified_name'].split('::')[-1] for r in results_no_param])
        names_none = sorted([r['qualified_name'].split('::')[-1] for r in results_none])
        assert names_no_param == names_none

    def test_file_name_filter_with_duplicate_basenames(self, temp_project_dir):
        """Test file_name filter when multiple files have same basename"""
        # Create files with same basename in different directories
        (temp_project_dir / "src" / "module1").mkdir(parents=True, exist_ok=True)
        (temp_project_dir / "src" / "module2").mkdir(parents=True, exist_ok=True)

        (temp_project_dir / "src" / "module1" / "Common.h").write_text("class Module1Class {};")
        (temp_project_dir / "src" / "module2" / "Common.h").write_text("class Module2Class {};")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search by basename only - should match both
        results = analyzer.search_classes(".*", file_name="Common.h")
        assert len(results) == 2, "Should match both Common.h files"
        names = sorted([r['qualified_name'].split('::')[-1] for r in results])
        assert names == ["Module1Class", "Module2Class"]

        # Search by partial path - should match only one
        results = analyzer.search_classes(".*", file_name="module1/Common.h")
        assert len(results) == 1
        assert results[0]['qualified_name'].split('::')[-1] == "Module1Class"

        results = analyzer.search_classes(".*", file_name="module2/Common.h")
        assert len(results) == 1
        assert results[0]['qualified_name'].split('::')[-1] == "Module2Class"

    def test_search_functions_standalone_vs_methods(self, temp_project_dir):
        """Test file_name filter with both standalone functions and methods"""
        (temp_project_dir / "src" / "Mixed.h").write_text("""
// Standalone function
void standaloneFunc();

class MyClass {
public:
    void classMethod();
};
""")

        (temp_project_dir / "src" / "Other.h").write_text("""
void otherFunc();
""")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search all functions in Mixed.h
        results = analyzer.search_functions(".*", file_name="Mixed.h")
        names = [r['qualified_name'].split('::')[-1] for r in results]

        # Should find both standalone and method
        assert "standaloneFunc" in names or "classMethod" in names
        assert "otherFunc" not in names

        # Verify all results are from Mixed.h
        for result in results:
            _res_loc = result.get("definition") or result.get("declaration") or {}
            assert _res_loc['file'].endswith("Mixed.h")

    def test_header_file_empty_string_behaves_as_no_filter(self, temp_project_dir):
        """Test that empty string for header_file returns all results"""
        (temp_project_dir / "src" / "A.h").write_text("class A {};")
        (temp_project_dir / "src" / "B.h").write_text("class B {};")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search with empty string - endswith("") always returns True
        results = analyzer.search_classes(".*", file_name="")
        assert len(results) == 2, "Empty string should match all files"

    def test_file_name_filter_with_project_only_false(self, temp_project_dir):
        """Test file_name filter combined with project_only=False"""
        # Create project file
        (temp_project_dir / "src" / "Project.h").write_text("class ProjectClass {};")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search with project_only=False and file_name filter
        # Should still filter by file even when including non-project files
        results = analyzer.search_classes(".*", project_only=False, file_name="Project.h")

        # Should only find classes from Project.h
        for result in results:
            _res_loc = result.get("definition") or result.get("declaration") or {}
            assert _res_loc['file'].endswith("Project.h")

    def test_multiple_classes_same_file_filtered_correctly(self, temp_project_dir):
        """Test that all classes from filtered file are returned"""
        (temp_project_dir / "src" / "Many.h").write_text("""
class Class1 {};
class Class2 {};
class Class3 {};
class Class4 {};
class Class5 {};
""")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search for all classes in Many.h
        results = analyzer.search_classes(".*", file_name="Many.h")
        assert len(results) == 5, "Should find all 5 classes"

        names = sorted([r['qualified_name'].split("::")[-1] for r in results])
        assert names == ["Class1", "Class2", "Class3", "Class4", "Class5"]

    def test_empty_pattern_with_file_name_returns_all_symbols_in_file(self, temp_project_dir):
        """Test that empty pattern with file_name filter returns all symbols in that file.

        This is the fix for the issue where LLMs using search_classes("", file_name="MyFile.h")
        would get empty results instead of all classes in that file.
        """
        (temp_project_dir / "src" / "Target.h").write_text("""
struct StructA {};
class ClassB {};
struct StructC {};
""")
        (temp_project_dir / "src" / "Other.h").write_text("""
class OtherClass {};
""")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search with empty pattern and file_name filter - should return all classes in Target.h
        results = analyzer.search_classes("", file_name="Target.h")
        assert len(results) == 3, f"Should find all 3 classes in Target.h, found {len(results)}"

        names = sorted([r['qualified_name'].split('::')[-1] for r in results])
        assert names == ["ClassB", "StructA", "StructC"]

        # Verify no classes from Other.h are included
        for result in results:
            _res_loc = result.get("definition") or result.get("declaration") or {}
            assert _res_loc['file'].endswith("Target.h"), f"Found unexpected file: {_res_loc['file']}"

    def test_empty_pattern_with_file_name_functions(self, temp_project_dir):
        """Test that empty pattern with file_name filter works for functions too."""
        (temp_project_dir / "src" / "functions.cpp").write_text("""
void funcA() {}
void funcB() {}
int funcC(int x) { return x; }
""")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search with empty pattern and file_name filter
        results = analyzer.search_functions("", file_name="functions.cpp")
        assert len(results) == 3, f"Should find all 3 functions, found {len(results)}"

        names = sorted([r['qualified_name'].split('::')[-1] for r in results])
        assert names == ["funcA", "funcB", "funcC"]

    def test_empty_pattern_search_symbols_all_types(self, temp_project_dir):
        """Test that empty pattern with search_symbols returns all symbol types."""
        (temp_project_dir / "src" / "mixed.h").write_text("""
class ClassA {};
struct StructB {};
void functionC();
class ClassD {
    void methodE();
};
""")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search with empty pattern - should return all classes and functions
        results = analyzer.search_symbols("", project_only=True)

        # Check we got both categories
        assert "classes" in results
        assert "functions" in results

        # Check classes
        class_names = sorted([c['qualified_name'].split('::')[-1] for c in results['classes']])
        assert "ClassA" in class_names
        assert "StructB" in class_names
        assert "ClassD" in class_names

        # Check functions (note: methodE might not be in function index depending on definition-wins)
        func_names = [f['qualified_name'].split('::')[-1] for f in results['functions']]
        assert "functionC" in func_names

    def test_empty_pattern_search_symbols_filtered_by_type(self, temp_project_dir):
        """Test that empty pattern with search_symbols and symbol_types filter works."""
        (temp_project_dir / "src" / "mixed.h").write_text("""
class ClassA {};
struct StructB {};
void functionC();
""")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search with empty pattern, only classes
        results = analyzer.search_symbols("", project_only=True, symbol_types=["class", "struct"])

        # Should have classes but empty functions
        assert len(results['classes']) >= 2
        assert len(results['functions']) == 0

        # Search with empty pattern, only functions
        results = analyzer.search_symbols("", project_only=True, symbol_types=["function"])

        # Should have functions but empty classes
        assert len(results['functions']) >= 1
        assert len(results['classes']) == 0

    def test_empty_pattern_find_in_file(self, temp_project_dir):
        """Test that empty pattern with find_in_file returns all symbols in that file."""
        test_file = temp_project_dir / "src" / "testfile.cpp"
        test_file.write_text("""
class TestClass {};
void testFunc1() {}
void testFunc2() {}
""")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Use find_in_file with empty pattern
        response = analyzer.find_in_file(str(test_file), "")
        results = response["results"]

        # Should find all symbols in that file
        assert len(results) >= 3, f"Should find at least 3 symbols, found {len(results)}"

        names = sorted([r['qualified_name'].split('::')[-1] for r in results])
        assert "TestClass" in names
        assert "testFunc1" in names
        assert "testFunc2" in names

    def test_empty_pattern_find_in_file_with_partial_path(self, temp_project_dir):
        """Test that empty pattern works with find_in_file using partial path."""
        # Create nested directory
        (temp_project_dir / "src" / "module").mkdir(parents=True, exist_ok=True)
        (temp_project_dir / "src" / "module" / "code.cpp").write_text("""
class ModuleClass {};
void moduleFunc() {}
""")

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Use partial path with empty pattern
        response = analyzer.find_in_file("module/code.cpp", "")
        results = response["results"]

        # Should find all symbols
        assert len(results) >= 2
        names = [r['qualified_name'].split('::')[-1] for r in results]
        assert "ModuleClass" in names
        assert "moduleFunc" in names
