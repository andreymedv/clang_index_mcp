# Comprehensive Test Plan for Clang Index MCP

## Document Purpose

This document maps each requirement from REQUIREMENTS.md to specific test cases, organized by category. Each test case specifies what should be tested, expected outcomes, and test data needed.

### Recent Enhancements

The following test coverage has been added to ensure comprehensive validation of all MCP server functionality:

**Section 4 - MCP Tool Tests:**
- Added edge case tests for search_classes (empty patterns, Unicode, long patterns, special regex chars)
- Added path validation tests for find_in_file (path traversal, special characters)

**Section 5 - Compilation Configuration Tests:**
- REQ-5.1: Added command string parsing test (shlex with quotes and spaces)
- REQ-5.2: Added vcpkg auto-detection test (REQ-5.2.5)

**Section 6 - Caching and Performance Tests:**
- REQ-6.2: Added cache version mismatch invalidation test (REQ-6.2.5)
- REQ-6.4: Added indexing progress file persistence test (REQ-6.4.6)
- REQ-6.4: Added terminal detection for adaptive progress reporting (REQ-6.4.7)

**Section 7 - Project Management Tests:**
- REQ-7.3: Added platform-specific libclang path tests (macOS, Linux, Windows)
- REQ-7.5: Added environment variable test for diagnostic level (CPP_ANALYZER_DIAGNOSTIC_LEVEL)

**Section 8 - Test Fixtures:**
- Enhanced test utilities with additional helper functions (env_var implementation, temp_dir, etc.)

## Table of Contents

1. [Core Functional Requirements Tests (REQ-1.x)](#1-core-functional-requirements-tests)
2. [Entity Extraction Tests (REQ-2.x)](#2-entity-extraction-tests)
3. [Entity Relationship Tests (REQ-3.x)](#3-entity-relationship-tests)
4. [MCP Tool Tests (REQ-4.x)](#4-mcp-tool-tests)
5. [Compilation Configuration Tests (REQ-5.x)](#5-compilation-configuration-tests)
6. [Caching and Performance Tests (REQ-6.x)](#6-caching-and-performance-tests)
7. [Project Management Tests (REQ-7.x)](#7-project-management-tests)
8. [Test Fixtures Required](#8-test-fixtures-required)

---

## 1. Core Functional Requirements Tests

### REQ-1.1: Symbol Analysis

#### Test-1.1.1: Symbol Extraction Using libclang
- **Requirements**: REQ-1.1.1
- **Test File**: `tests/unit/test_symbol_extraction.py`
- **Fixture**: `fixtures/basic/simple_symbols.cpp`
- **What to Test**:
  - Parse C++ file with libclang
  - Extract at least one class
  - Extract at least one function
  - Verify libclang cursors are used
- **Expected**: Symbols extracted without errors

#### Test-1.1.2: Separate Index Maintenance
- **Requirements**: REQ-1.1.2
- **Test File**: `tests/unit/test_indexes.py`
- **What to Test**:
  - Verify `class_index` is a Dict[str, List[SymbolInfo]]
  - Verify `function_index` is a Dict[str, List[SymbolInfo]]
  - Verify `file_index` is a Dict[str, List[SymbolInfo]]
  - Verify `usr_index` is a Dict[str, SymbolInfo]
  - Add symbol to one index, verify it doesn't appear in others inappropriately
- **Expected**: Four distinct indexes maintained correctly

#### Test-1.1.3: Regex Pattern Matching
- **Requirements**: REQ-1.1.3

- **Test File**: `tests/unit/test_search_patterns.py`
- **Fixture**: `fixtures/search/mixed_symbols.cpp`
- **Test Cases**:
  - Exact match: `^ClassName$`
  - Prefix: `^Test.*`
  - Suffix: `.*Manager$`
  - Contains: `.*Helper.*`
  - Complex pattern: `^(Test|Mock).*Manager$`
- **Expected**: Correct symbols matched for each pattern

#### Test-1.1.4: Project vs Dependency Distinction
- **Requirements**: REQ-1.1.4
- **Test File**: `tests/unit/test_project_filtering.py`
- **Fixture**: `fixtures/projects/with_dependencies/`
- **What to Test**:
  - Index project with dependency directory (vcpkg_installed)
  - Verify symbols have `is_project` field
  - Verify project files have `is_project=True`
  - Verify dependency files have `is_project=False`
  - Test `project_only=True` filtering
- **Expected**: Correct classification and filtering

### REQ-1.2: Parallel Processing

#### Test-1.2.1: Multi-threaded Indexing
- **Requirements**: REQ-1.2.1
- **Test File**: `tests/integration/test_parallel_indexing.py`
- **Fixture**: `fixtures/projects/large_project/` (50+ files)
- **What to Test**:
  - Index project with multiple workers
  - Verify `max_workers > 1`
  - Verify all files indexed correctly
  - Compare results with single-threaded indexing
- **Expected**: Correct results with parallel processing

#### Test-1.2.2: Thread-local libclang Instances
- **Requirements**: REQ-1.2.2
- **Test File**: `tests/unit/test_threading.py`
- **What to Test**:
  - Call `_get_thread_index()` from multiple threads
  - Verify each thread gets its own Index instance
  - Verify instances are reused within same thread
- **Expected**: Thread-local isolation maintained

#### Test-1.2.3: Configurable Worker Threads
- **Requirements**: REQ-1.2.3
- **Test File**: `tests/unit/test_analyzer_config.py::test_worker_count`
- **What to Test**:
  - Mock `os.cpu_count()` to return different values (1, 2, 4, 16, 32)
  - Verify `max_workers = max(1, min(16, cpu_count * 2))`
- **Expected**:
  - 1 CPU → 2 workers
  - 2 CPU → 4 workers
  - 4 CPU → 8 workers
  - 16 CPU → 16 workers (capped)
  - 32 CPU → 16 workers (capped)

#### Test-1.2.4: Thread-safe Locking
- **Requirements**: REQ-1.2.4
- **Test File**: `tests/integration/test_thread_safety.py`
- **What to Test**:
  - Index files concurrently
  - Verify no race conditions in index updates
  - Verify lock prevents concurrent modifications
  - Check for deadlocks (timeout test)
- **Expected**: No data corruption, no deadlocks

---

## 2. Entity Extraction Tests

### REQ-2.1: Classes and Structs

#### Test-2.1.1.1-3: Basic Class Extraction
- **Requirements**: REQ-2.1.1.1, REQ-2.1.1.2, REQ-2.1.1.3
- **Test File**: `tests/unit/test_class_extraction.py`
- **Fixtures**:
  - `fixtures/classes/simple_class.h`
  - `fixtures/classes/simple_struct.h`
- **Test Cases**:

```python
def test_extract_simple_class():
    """Verify CLASS_DECL extraction"""
    analyzer = index_fixture("fixtures/classes/simple_class.h")
    classes = analyzer.search_classes("SimpleClass")

    assert len(classes) == 1
    c = classes[0]
    assert c["name"] == "SimpleClass"
    assert c["kind"] == "class"
    assert c["file"].endswith("simple_class.h")
    assert c["line"] > 0
    assert c["column"] > 0
    # USR should be non-empty
    assert len(get_symbol_usr(c)) > 0
    assert c["base_classes"] == []
    assert c["is_project"] == True

def test_extract_simple_struct():
    """Verify STRUCT_DECL extraction"""
    analyzer = index_fixture("fixtures/classes/simple_struct.h")
    structs = analyzer.search_classes("SimpleStruct")

    assert len(structs) == 1
    s = structs[0]
    assert s["kind"] == "struct"
```

#### Test-2.1.2.1: Class Variants
- **Requirements**: REQ-2.1.2.1
- **Test File**: `tests/unit/test_class_variants.py`
- **Test Cases**:

| Test Case | Fixture | What to Verify |
|-----------|---------|----------------|
| Regular class | `fixtures/classes/regular_class.h` | Basic class extraction |
| Template class | `fixtures/classes/template_class.h` | Template parameters recognized |
| Nested class | `fixtures/classes/nested_class.h` | Inner class extracted with parent context |
| Forward declaration | `fixtures/classes/forward_decl.h` | Both forward and full declaration found |
| Anonymous struct | `fixtures/classes/anonymous_struct.h` | Anonymous struct extracted |
| Abstract class | `fixtures/classes/abstract_class.h` | Pure virtual methods present |

```python
@pytest.mark.parametrize("fixture,class_name,expected_kind", [
    ("fixtures/classes/regular_class.h", "RegularClass", "class"),
    ("fixtures/classes/template_class.h", "TemplateClass", "class"),
    ("fixtures/classes/nested_class.h", "Outer::Inner", "class"),
])
def test_class_variants(fixture, class_name, expected_kind):
    analyzer = index_fixture(fixture)
    classes = analyzer.search_classes(class_name)
    assert len(classes) >= 1
    assert classes[0]["kind"] == expected_kind
```

#### Test-2.1.3.1-3: Inheritance Information
- **Requirements**: REQ-2.1.3.1, REQ-2.1.3.2, REQ-2.1.3.3
- **Test File**: `tests/unit/test_inheritance.py`
- **Fixtures**:
  - `fixtures/inheritance/single_inheritance.h`
  - `fixtures/inheritance/multiple_inheritance.h`
  - `fixtures/inheritance/virtual_inheritance.h`
- **Test Cases**:

```python
def test_single_inheritance():
    analyzer = index_fixture("fixtures/inheritance/single_inheritance.h")
    classes = analyzer.search_classes("Derived")

    assert len(classes) == 1
    assert "Base" in classes[0]["base_classes"]

def test_multiple_inheritance():
    analyzer = index_fixture("fixtures/inheritance/multiple_inheritance.h")
    classes = analyzer.search_classes("Derived")

    assert len(classes) == 1
    base_classes = classes[0]["base_classes"]
    assert "Base1" in base_classes
    assert "Base2" in base_classes

def test_virtual_inheritance():
    analyzer = index_fixture("fixtures/inheritance/virtual_inheritance.h")
    classes = analyzer.search_classes("VirtualDerived")

    assert len(classes) == 1
    # Verify virtual base class is extracted
    assert "VirtualBase" in classes[0]["base_classes"]

def test_base_class_name_normalization():
    """Test REQ-2.1.3.3: Remove 'class ' prefix"""
    # libclang sometimes returns "class ClassName"
    # Verify we normalize to just "ClassName"
    analyzer = index_fixture("fixtures/inheritance/single_inheritance.h")
    classes = analyzer.search_classes("Derived")

    # Should NOT contain "class Base", just "Base"
    assert "Base" in classes[0]["base_classes"]
    assert "class Base" not in classes[0]["base_classes"]
```

### REQ-2.2: Functions and Methods

#### Test-2.2.1.1-3: Basic Function Extraction
- **Requirements**: REQ-2.2.1.1, REQ-2.2.1.2, REQ-2.2.1.3
- **Test File**: `tests/unit/test_function_extraction.py`
- **Fixtures**:
  - `fixtures/functions/global_functions.cpp`
  - `fixtures/functions/class_methods.h`
- **Test Cases**:

```python
def test_extract_global_function():
    analyzer = index_fixture("fixtures/functions/global_functions.cpp")
    functions = analyzer.search_functions("globalFunction")

    assert len(functions) >= 1
    f = functions[0]
    assert f["name"] == "globalFunction"
    assert f["kind"] == "function"
    assert f["file"].endswith("global_functions.cpp")
    assert f["line"] > 0
    assert f["signature"] != ""  # Should have type signature
    assert f["parent_class"] == ""  # Global function has no parent class

def test_extract_method():
    analyzer = index_fixture("fixtures/functions/class_methods.h")
    methods = analyzer.search_functions("memberMethod", class_name="MyClass")

    assert len(methods) >= 1
    m = methods[0]
    assert m["kind"] == "method"
    assert m["parent_class"] == "MyClass"
```

#### Test-2.2.2.1: Function Variants
- **Requirements**: REQ-2.2.2.1
- **Test File**: `tests/unit/test_function_variants.py`
- **Test Matrix**:

| Variant | Fixture | Verification |
|---------|---------|--------------|
| Global function | `fixtures/functions/global.cpp` | kind=function, parent_class="" |
| Static function | `fixtures/functions/static_func.cpp` | Extracted correctly |
| Inline function | `fixtures/functions/inline_func.h` | Found in header |
| Constexpr function | `fixtures/functions/constexpr_func.h` | Extracted |
| Template function | `fixtures/functions/template_func.h` | Template params recognized |
| Function overloads | `fixtures/functions/overloads.cpp` | Multiple entries, same name, different signatures |
| Variadic function | `fixtures/functions/variadic.cpp` | Variadic signature captured |
| Friend function | `fixtures/functions/friend_func.h` | Extracted |
| Operator overload | `fixtures/functions/operators.cpp` | operator+, operator==, etc. found |
| Header implementation | `fixtures/functions/header_impl.h` | Function in .h file |
| Cpp implementation | `fixtures/functions/cpp_impl.cpp` | Function in .cpp file |

```python
def test_function_overloads():
    """Verify multiple functions with same name are all extracted"""
    analyzer = index_fixture("fixtures/functions/overloads.cpp")
    functions = analyzer.search_functions("^overloadedFunc$")

    # Should find multiple overloads
    assert len(functions) >= 2

    # Each should have different signature
    signatures = [f["signature"] for f in functions]
    assert len(set(signatures)) == len(functions)  # All unique
```

#### Test-2.2.3.1: Method Variants
- **Requirements**: REQ-2.2.3.1
- **Test File**: `tests/unit/test_method_variants.py`
- **Test Matrix**:

| Variant | Fixture | Verification |
|---------|---------|--------------|
| Regular method | `fixtures/methods/regular.h` | Standard member method |
| Static method | `fixtures/methods/static_method.h` | Static qualifier |
| Const method | `fixtures/methods/const_method.h` | Const in signature |
| Virtual method | `fixtures/methods/virtual_method.h` | Virtual qualifier |
| Pure virtual | `fixtures/methods/pure_virtual.h` | = 0 in signature |
| Override method | `fixtures/methods/override.h` | override keyword |
| Final method | `fixtures/methods/final.h` | final keyword |
| Default constructor | `fixtures/methods/constructors.h` | Name == class name |
| Parameterized constructor | `fixtures/methods/constructors.h` | Constructor with params |
| Copy constructor | `fixtures/methods/constructors.h` | MyClass(const MyClass&) |
| Move constructor | `fixtures/methods/constructors.h` | MyClass(MyClass&&) |
| Destructor | `fixtures/methods/destructor.h` | ~ClassName |
| Virtual destructor | `fixtures/methods/virtual_destructor.h` | virtual ~ClassName |
| Operator method | `fixtures/methods/operator_methods.h` | operator+ as method |

#### Test-2.2.4.1: Template Support
- **Requirements**: REQ-2.2.4.1
- **Test File**: `tests/unit/test_templates.py`
- **Fixtures**:
  - `fixtures/templates/class_template.h`
  - `fixtures/templates/function_template.h`
  - `fixtures/templates/specialization.h`
  - `fixtures/templates/variadic_template.h`
- **Test Cases**:

```python
def test_template_class():
    analyzer = index_fixture("fixtures/templates/class_template.h")
    classes = analyzer.search_classes("Vector")
    assert len(classes) >= 1

def test_template_function():
    analyzer = index_fixture("fixtures/templates/function_template.h")
    functions = analyzer.search_functions("max")
    assert len(functions) >= 1

def test_template_specialization():
    analyzer = index_fixture("fixtures/templates/specialization.h")
    # Should find both generic and specialized versions
    classes = analyzer.search_classes("MyTemplate")
    assert len(classes) >= 2

def test_variadic_template():
    analyzer = index_fixture("fixtures/templates/variadic_template.h")
    classes = analyzer.search_classes("Tuple")
    assert len(classes) >= 1
```

### REQ-2.3: Namespaces

#### Test-2.3.1-3: Namespace Support
- **Requirements**: REQ-2.3.1, REQ-2.3.2, REQ-2.3.3
- **Test File**: `tests/unit/test_namespaces.py`
- **Fixtures**:
  - `fixtures/namespaces/named_namespace.h`
  - `fixtures/namespaces/nested_namespace.h`
  - `fixtures/namespaces/anonymous_namespace.cpp`
- **Test Cases**:

```python
def test_named_namespace():
    analyzer = index_fixture("fixtures/namespaces/named_namespace.h")
    classes = analyzer.search_classes("MyClass")

    assert len(classes) >= 1
    # Verify namespace is captured (if implemented)
    # Note: Check if namespace field is populated

def test_nested_namespace():
    analyzer = index_fixture("fixtures/namespaces/nested_namespace.h")
    classes = analyzer.search_classes("InnerClass")

    assert len(classes) >= 1
    # Namespace should be "Outer::Inner" or similar

def test_anonymous_namespace():
    analyzer = index_fixture("fixtures/namespaces/anonymous_namespace.cpp")
    functions = analyzer.search_functions("helperFunction")

    # Should find function in anonymous namespace
    assert len(functions) >= 1
```

### REQ-2.4: Call Graph Extraction

#### Test-2.4.1-4: Call Graph Construction
- **Requirements**: REQ-2.4.1, REQ-2.4.2, REQ-2.4.3, REQ-2.4.4
- **Test File**: `tests/unit/test_call_graph_extraction.py`
- **Fixtures**:
  - `fixtures/call_graph/simple_calls.cpp`
  - `fixtures/call_graph/method_calls.cpp`
  - `fixtures/call_graph/virtual_calls.cpp`
- **Test Cases**:

```python
def test_extract_function_calls():
    """Test REQ-2.4.1: Extract CALL_EXPR"""
    analyzer = index_fixture("fixtures/call_graph/simple_calls.cpp")

    # functionA calls functionB
    callees = analyzer.find_callees("functionA")
    assert any(c["name"] == "functionB" for c in callees)

def test_bidirectional_call_graph():
    """Test REQ-2.4.2: Track forward and reverse"""
    analyzer = index_fixture("fixtures/call_graph/simple_calls.cpp")

    # Forward: A -> B
    callees = analyzer.find_callees("functionA")
    assert any(c["name"] == "functionB" for c in callees)

    # Reverse: B <- A
    callers = analyzer.find_callers("functionB")
    assert any(c["name"] == "functionA" for c in callers)

def test_usr_based_call_linking():
    """Test REQ-2.4.3: USR-based linking"""
    analyzer = index_fixture("fixtures/call_graph/overloaded_calls.cpp")

    # With overloaded functions, USR ensures correct linkage
    # functionA calls overloaded(int), not overloaded(string)
    # Verify correct overload is linked
    callees = analyzer.find_callees("functionA")
    # Check signature to ensure correct overload
    assert any("int" in c["signature"] for c in callees)

def test_method_calls():
    """Test REQ-2.4.4: Method calls"""
    analyzer = index_fixture("fixtures/call_graph/method_calls.cpp")

    # Test object.method() calls
    callees = analyzer.find_callees("processData")
    assert any(c["name"] == "validate" for c in callees)

def test_static_method_calls():
    """Test REQ-2.4.4: Static method calls"""
    analyzer = index_fixture("fixtures/call_graph/static_calls.cpp")

    # Test ClassName::staticMethod() calls
    callees = analyzer.find_callees("main")
    assert any(c["parent_class"] == "Utility" for c in callees)

def test_virtual_calls():
    """Test REQ-2.4.4: Virtual function calls"""
    analyzer = index_fixture("fixtures/call_graph/virtual_calls.cpp")

    # Virtual calls may resolve to base class method
    # Verify call is tracked (even if dynamic dispatch isn't resolved)
    callees = analyzer.find_callees("process")
    assert len(callees) > 0
```

---

## 3. Entity Relationship Tests

### REQ-3.1: Inheritance Relationships

#### Test-3.1.1: Bidirectional Inheritance
- **Requirements**: REQ-3.1.1
- **Test File**: `tests/integration/test_inheritance_relationships.py`
- **Fixture**: `fixtures/relationships/inheritance_tree.h`
- **Test Cases**:

```python
def test_base_to_derived():
    """Forward: Base -> Derived classes"""
    analyzer = index_fixture("fixtures/relationships/inheritance_tree.h")

    derived = analyzer.get_derived_classes("Animal")
    derived_names = [d["name"] for d in derived]

    assert "Dog" in derived_names
    assert "Cat" in derived_names

def test_derived_to_base():
    """Backward: Derived -> Base classes"""
    analyzer = index_fixture("fixtures/relationships/inheritance_tree.h")

    hierarchy = analyzer.get_class_hierarchy("Dog")
    assert "Animal" in hierarchy["base_classes"]
```

#### Test-3.1.2: Recursive Hierarchy Queries
- **Requirements**: REQ-3.1.2
- **Test File**: `tests/integration/test_class_hierarchy.py`
- **Fixture**: `fixtures/relationships/deep_hierarchy.h`
- **Test Cases**:

```python
def test_complete_base_hierarchy():
    """Get all ancestors recursively"""
    analyzer = index_fixture("fixtures/relationships/deep_hierarchy.h")

    # GrandChild -> Child -> Parent -> GrandParent
    hierarchy = analyzer.get_class_hierarchy("GrandChild")

    # Should have recursive base hierarchy
    assert "Child" in hierarchy["base_classes"]
    assert hierarchy["base_hierarchy"]["name"] == "GrandChild"
    # Navigate to find GrandParent
    # (structure depends on implementation)

def test_complete_derived_hierarchy():
    """Get all descendants recursively"""
    analyzer = index_fixture("fixtures/relationships/deep_hierarchy.h")

    hierarchy = analyzer.get_class_hierarchy("GrandParent")
    # Should show Parent, Child, GrandChild in derived tree
```

#### Test-3.1.3: Circular Reference Detection
- **Requirements**: REQ-3.1.3
- **Test File**: `tests/integration/test_circular_references.py`
- **Fixture**: Mock circular hierarchy (if possible in C++)
- **Test Cases**:

```python
def test_circular_inheritance_handled():
    """Ensure circular references don't cause infinite loops"""
    # Note: C++ doesn't allow true circular inheritance,
    # but we can test the detection logic
    analyzer = CppAnalyzer(test_project)

    # Manually create circular reference in indexes for testing
    # Or test with forward declarations that might confuse the system

    hierarchy = analyzer.get_class_hierarchy("TestClass")
    # Should complete without hanging
    assert hierarchy is not None
    # Check for circular_reference flag if present
```

### REQ-3.2: Containment Relationships

#### Test-3.2.1-2: Class-Method Relationships
- **Requirements**: REQ-3.2.1, REQ-3.2.2
- **Test File**: `tests/unit/test_containment.py`
- **Fixture**: `fixtures/relationships/class_with_methods.h`
- **Test Cases**:

```python
def test_method_parent_class_tracking():
    """Verify parent_class field"""
    analyzer = index_fixture("fixtures/relationships/class_with_methods.h")
    methods = analyzer.search_functions("process", class_name="DataProcessor")
    assert len(methods) >= 1
    assert methods[0]["parent_class"] == "DataProcessor"

def test_get_all_class_methods():
    """Query all methods of a class"""
    analyzer = index_fixture("fixtures/relationships/class_with_methods.h")

    info = analyzer.get_class_info("DataProcessor")
    method_names = [m["name"] for m in info["methods"]]

    assert "process" in method_names
    assert "validate" in method_names
    assert len(method_names) >= 2
```

### REQ-3.3: Call Graph Relationships

#### Test-3.3.1-4: Call Graph Operations
- **Requirements**: REQ-3.3.1, REQ-3.3.2, REQ-3.3.3, REQ-3.3.4
- **Test File**: `tests/integration/test_call_graph_operations.py`
- **Fixtures**:
  - `fixtures/call_graph/call_chain.cpp`
  - `fixtures/call_graph/complex_calls.cpp`
- **Test Cases**:

```python
def test_bidirectional_call_graph():
    """Test REQ-3.3.1: Forward and reverse call graph"""
    analyzer = index_fixture("fixtures/call_graph/call_chain.cpp")

    # A calls B, B calls C

    # Forward
    b_callees = analyzer.find_callees("funcB")
    assert any(c["name"] == "funcC" for c in b_callees)

    # Reverse
    b_callers = analyzer.find_callers("funcB")
    assert any(c["name"] == "funcA" for c in b_callers)

def test_call_path_finding():
    """Test REQ-3.3.2: BFS path finding"""
    analyzer = index_fixture("fixtures/call_graph/call_chain.cpp")

    # Find path from funcA to funcC
    paths = analyzer.get_call_path("funcA", "funcC")

    assert len(paths) >= 1
    # Should be: funcA -> funcB -> funcC
    assert len(paths[0]) == 3
    assert paths[0][0] == "funcA"
    assert paths[0][1] == "funcB"
    assert paths[0][2] == "funcC"

def test_max_depth_limit():
    """Test REQ-3.3.3: Configurable max depth"""
    analyzer = index_fixture("fixtures/call_graph/long_chain.cpp")

    # Chain: A -> B -> C -> D -> E -> F
    # With max_depth=3, should only find paths up to 3 hops
    paths = analyzer.get_call_path("funcA", "funcF", max_depth=3)

    # Should not find path (too deep)
    assert len(paths) == 0

    # With max_depth=10, should find path
    paths = analyzer.get_call_path("funcA", "funcF", max_depth=10)
    assert len(paths) >= 1
```

### REQ-3.4: File Membership Relationships

#### Test-3.4.1-2: File-Symbol Relationships
- **Requirements**: REQ-3.4.1, REQ-3.4.2
- **Test File**: `tests/unit/test_file_membership.py`
- **Fixture**: `fixtures/files/multi_symbol_file.h`
- **Test Cases**:

```python
def test_file_symbol_tracking():
    """Verify file_index tracks symbols by file"""
    analyzer = index_fixture("fixtures/files/multi_symbol_file.h")

    # File contains ClassA, ClassB, functionX
    file_path = analyzer.project_root / "fixtures/files/multi_symbol_file.h"
    symbols = analyzer.file_index.get(str(file_path.resolve()), [])

    symbol_names = [s.name for s in symbols]
    assert "ClassA" in symbol_names
    assert "ClassB" in symbol_names
    assert "functionX" in symbol_names

def test_find_symbols_in_file():
    """Test find_in_file tool"""
    analyzer = index_fixture("fixtures/files/multi_symbol_file.h")

    results = analyzer.find_in_file("multi_symbol_file.h", ".*")
    assert len(results) >= 3
```

### REQ-3.5: Project vs Dependency Relationships

#### Test-3.5.1-4: Project Classification
- **Requirements**: REQ-3.5.1, REQ-3.5.2, REQ-3.5.3, REQ-3.5.4
- **Test File**: `tests/integration/test_project_classification.py`
- **Fixture**: `fixtures/projects/with_dependencies/`
- **Setup**:
```
with_dependencies/
├── src/
│   └── main.cpp              # Project file
├── vcpkg_installed/
│   └── include/
│       └── lib.h             # Dependency file
└── .cpp-analyzer-config.json
```
- **Test Cases*

```python
def test_project_file_classification():
    """Test REQ-3.5.1, REQ-3.5.3: is_project flag"""
    analyzer = CppAnalyzer("fixtures/projects/with_dependencies")
    analyzer.index_project(include_dependencies=True)

    # Project file
    project_symbols = analyzer.search_classes("MainClass")
    assert project_symbols[0]["is_project"] == True

    # Dependency file
    dep_symbols = analyzer.search_classes("LibClass")
    assert dep_symbols[0]["is_project"] == False

def test_project_only_filtering():
    """Test REQ-3.5.2: project_only filtering"""
    analyzer = CppAnalyzer("fixtures/projects/with_dependencies")
    analyzer.index_project(include_dependencies=True)

    # With project_only=True
    project_only = analyzer.search_classes(".*", project_only=True)
    assert all(c["is_project"] for c in project_only)

    # With project_only=False
    all_classes = analyzer.search_classes(".*", project_only=False)
    assert any(not c["is_project"] for c in all_classes)
```

---

## 4. MCP Tool Tests

### Tool Testing Strategy

For each of the 14 MCP tools, we need:
1. **Happy path test**: Valid inputs, successful response
2. **Input validation test**: Invalid inputs, error handling
3. **Edge case test**: Empty results, large results
4. **Integration test**: Tool works with real indexed project

### REQ-4.1: search_classes

#### Test-4.1: search_classes Tool
- **Requirements**: REQ-4.1.1, REQ-4.1.2, REQ-4.1.3, REQ-4.1.4
- **Test File**: `tests/integration/test_mcp_search_classes.py`
- **Test Cases**:

```python
def test_search_classes_happy_path():
    """Basic search with pattern and project_only"""
    analyzer = setup_test_analyzer()

    results = analyzer.search_classes(".*Manager", project_only=True)

    assert isinstance(results, list)
    for r in results:
        assert "name" in r
        assert "kind" in r
        assert "file" in r
        assert "line" in r
        assert "is_project" in r
        assert "base_classes" in r

def test_search_classes_regex_patterns():
    """Test REQ-4.1.3: Various regex patterns"""
    analyzer = setup_test_analyzer()

    # Case-insensitive (should work)
    results = analyzer.search_classes("manager", project_only=False)
    assert len(results) > 0

def test_search_classes_project_filtering():
    """Test REQ-4.1.4: project_only flag"""
    analyzer = setup_test_analyzer()

    all_classes = analyzer.search_classes(".*", project_only=False)
    project_classes = analyzer.search_classes(".*", project_only=True)

    assert len(project_classes) <= len(all_classes)
    assert all(c["is_project"] for c in project_classes)

def test_search_classes_invalid_regex():
    """Error handling for invalid regex"""
    analyzer = setup_test_analyzer()

    # Invalid regex pattern
    results = analyzer.search_classes("[invalid(")
    assert isinstance(results, list)
    assert len(results) == 0  # Should return empty, not crash

def test_search_classes_edge_cases():
    """Test edge cases for pattern matching"""
    analyzer = setup_test_analyzer()

    # Empty pattern
    results = analyzer.search_classes("")
    assert isinstance(results, list)

    # Unicode characters
    results = analyzer.search_classes(".*класс.*")
    assert isinstance(results, list)

    # Very long pattern
    long_pattern = "A" * 1000
    results = analyzer.search_classes(long_pattern)
    assert isinstance(results, list)

    # Special regex characters
    results = analyzer.search_classes(".*\\[.*\\].*")
    assert isinstance(results, list)
```

### REQ-4.2: search_functions

#### Test-4.2: search_functions Tool
- **Requirements**: REQ-4.2.1, REQ-4.2.2, REQ-4.2.3, REQ-4.2.4
- **Test File**: `tests/integration/test_mcp_search_functions.py`
- **Test Cases**:

```python
def test_search_functions_happy_path():
    analyzer = setup_test_analyzer()

    results = analyzer.search_functions("process.*", project_only=True)
    for r in results:
        assert "name" in r
        assert "kind" in r
        assert "signature" in r
        assert "parent_class" in r

def test_search_functions_class_filter():
    """Test REQ-4.2.4: Filter by class_name"""
    analyzer = setup_test_analyzer()

    # Search for 'process' only in DataProcessor class
    results = analyzer.search_functions("process", class_name="DataProcessor")

    assert all(r["parent_class"] == "DataProcessor" for r in results)
```

### REQ-4.3: get_class_info

#### Test-4.3: get_class_info Tool
- **Requirements**: REQ-4.3.1, REQ-4.3.2, REQ-4.3.3, REQ-4.3.4
- **Test File**: `tests/integration/test_mcp_get_class_info.py`
- **Test Cases**:

```python
def test_get_class_info_happy_path():
    analyzer = setup_test_analyzer()

    info = analyzer.get_class_info("MyClass")

    assert info is not None
    assert info["name"] == "MyClass"
    assert "kind" in info
    assert "base_classes" in info
    assert "methods" in info

    # Methods should be sorted by line number
    methods = info["methods"]
    lines = [m["line"] for m in methods]
    assert lines == sorted(lines)

def test_get_class_info_not_found():
    """Test REQ-4.3.4: Class not found"""
    analyzer = setup_test_analyzer()

    info = analyzer.get_class_info("NonExistentClass")
    assert info is None
```

### REQ-4.4: get_function_signature

#### Test-4.4: get_function_signature Tool
- **Requirements**: REQ-4.4.1, REQ-4.4.2, REQ-4.4.3
- **Test File**: `tests/integration/test_mcp_get_function_signature.py`
- **Test Cases**:

```python
def test_get_function_signature():
    analyzer = setup_test_analyzer()

    sigs = analyzer.get_function_signature("myFunction")

    assert isinstance(sigs, list)
    assert len(sigs) > 0
    assert "myFunction" in sigs[0]

def test_get_function_signature_with_class():
    analyzer = setup_test_analyzer()

    sigs = analyzer.get_function_signature("process", class_name="DataProcessor")

    assert all("DataProcessor::process" in sig for sig in sigs)

def test_function_overloads_all_returned():
    """Test REQ-4.4.3: All overloads returned"""
    analyzer = setup_test_analyzer()

    sigs = analyzer.get_function_signature("overloaded")

    # Should have multiple signatures for overloads
    assert len(sigs) >= 2
    assert len(set(sigs)) == len(sigs)  # All unique
```

### REQ-4.5: search_symbols

#### Test-4.5: search_symbols Tool
- **Requirements**: REQ-4.5.1, REQ-4.5.2, REQ-4.5.3
- **Test File**: `tests/integration/test_mcp_search_symbols.py`
- **Test Cases**:

```python
def test_search_symbols_all_types():
    analyzer = setup_test_analyzer()

    results = analyzer.search_symbols("Test.*", project_only=True)

    assert "classes" in results
    assert "functions" in results
    assert isinstance(results["classes"], list)
    assert isinstance(results["functions"], list)

def test_search_symbols_type_filtering():
    """Test REQ-4.5.3: Filter by symbol_types"""
    analyzer = setup_test_analyzer()

    # Only classes
    results = analyzer.search_symbols(".*", symbol_types=["class"])
    assert len(results["classes"]) > 0
    assert len(results["functions"]) == 0

    # Only functions
    results = analyzer.search_symbols(".*", symbol_types=["function", "method"])
    assert len(results["functions"]) > 0
```

### REQ-4.6: find_in_file

#### Test-4.6: find_in_file Tool
- **Requirements**: REQ-4.6.1, REQ-4.6.2, REQ-4.6.3
- **Test File**: `tests/integration/test_mcp_find_in_file.py`
- **Test Cases**:

```python
def test_find_in_file_relative_path():
    analyzer = setup_test_analyzer()

    results = analyzer.find_in_file("src/main.cpp", ".*")

    assert isinstance(results, list)
    assert all(r["file"].endswith("main.cpp") for r in results)

def test_find_in_file_absolute_path():
    """Test REQ-4.6.3: Absolute path resolution"""
    analyzer = setup_test_analyzer()

    abs_path = str(analyzer.project_root / "src/main.cpp")
    results = analyzer.find_in_file(abs_path, ".*")

    assert len(results) > 0

def test_find_in_file_path_validation():
    """Test path traversal prevention and validation"""
    analyzer = setup_test_analyzer()

    # Path traversal attempts should be handled safely
    results = analyzer.find_in_file("../../../etc/passwd", ".*")
    assert isinstance(results, list)

    # Special characters in filename
    results = analyzer.find_in_file("file name with spaces.cpp", ".*")
    assert isinstance(results, list)
```

### REQ-4.7: set_project_directory

#### Test-4.7: set_project_directory Tool
- **Requirements**: REQ-4.7.1, REQ-4.7.2, REQ-4.7.3, REQ-4.7.4, REQ-4.7.5
- **Test File**: `tests/integration/test_mcp_set_project_directory.py`
- **Test Cases**:

```python
def test_set_project_directory_happy_path():
    """Test REQ-4.7.3, REQ-4.7.4: Initialize and index"""
    project_dir = create_temp_project()

    analyzer = CppAnalyzer(str(project_dir))
    count = analyzer.index_project()

    assert count > 0
    assert analyzer.indexed_file_count == count

def test_set_project_directory_validation():
    """Test REQ-4.7.2: Input validation"""

    # Empty path
    with pytest.raises(ValueError):
        CppAnalyzer("")

    # Path with whitespace
    with pytest.raises(ValueError):
        CppAnalyzer(" /path ")

    # Relative path
    with pytest.raises(ValueError):
        CppAnalyzer("relative/path")

    # Non-existent directory
    with pytest.raises(ValueError):
        CppAnalyzer("/nonexistent/path")
```

### REQ-4.8: refresh_project

#### Test-4.8: refresh_project Tool
- **Requirements**: REQ-4.8.1, REQ-4.8.2, REQ-4.8.3, REQ-4.8.4, REQ-4.8.5
- **Test File**: `tests/integration/test_mcp_refresh_project.py`
- **Test Cases**:

```python
def test_refresh_modified_files():
    """Test REQ-4.8.2: Re-parse modified files"""
    with temp_project() as project_dir:
        analyzer = CppAnalyzer(project_dir)
        analyzer.index_project()

        # Modify a file
        test_file = project_dir / "test.cpp"
        test_file.write_text("class NewClass {};")

        # Refresh
        refreshed = analyzer.refresh_if_needed()

        assert refreshed == 1

        # Verify new class found
        classes = analyzer.search_classes("NewClass")
        assert len(classes) == 1

def test_refresh_deleted_files():
    """Test REQ-4.8.3: Remove deleted files"""
    with temp_project() as project_dir:
        test_file = project_dir / "test.cpp"
        test_file.write_text("class ToDelete {};")

        analyzer = CppAnalyzer(project_dir)
        analyzer.index_project()

        # Verify class exists
        assert len(analyzer.search_classes("ToDelete")) == 1

        # Delete file
        test_file.unlink()

        # Refresh
        analyzer.refresh_if_needed()

        # Class should be gone
        assert len(analyzer.search_classes("ToDelete")) == 0

def test_refresh_compile_commands():
    """Test REQ-4.8.5: Update compile_commands.json"""
    with temp_project_with_cc() as project_dir:
        analyzer = CppAnalyzer(project_dir)
        analyzer.index_project()

        # Modify compile_commands.json
        cc_path = project_dir / "compile_commands.json"
        modify_compile_commands(cc_path)

        # Refresh should detect change
        refreshed = analyzer.refresh_if_needed()

        # Verify compile commands reloaded
        assert analyzer.compile_commands_manager.last_modified > 0
```

### REQ-4.9: get_server_status

#### Test-4.9: get_server_status Tool
- **Requirements**: REQ-4.9.1, REQ-4.9.2
- **Test File**: `tests/integration/test_mcp_get_server_status.py`
- **Test Cases**:

```python
def test_get_server_status():
    analyzer = setup_test_analyzer()

    status = {
        "analyzer_type": "python_enhanced",
        "call_graph_enabled": True,
        "usr_tracking_enabled": True,
        "compile_commands_enabled": analyzer.compile_commands_manager.enabled,
        "compile_commands_path": analyzer.compile_commands_manager.compile_commands_path,
        "compile_commands_cache_enabled": analyzer.compile_commands_manager.cache_enabled,
        "parsed_files": len(analyzer.translation_units),
        "indexed_classes": len(analyzer.class_index),
        "indexed_functions": len(analyzer.function_index),
        "project_files": len(analyzer.translation_units)
    }

    # Verify all required fields present
    assert "analyzer_type" in status
    assert "call_graph_enabled" in status
    assert "parsed_files" in status
    assert isinstance(status["parsed_files"], int)
```

### REQ-4.10: get_class_hierarchy

#### Test-4.10: get_class_hierarchy Tool
- **Requirements**: REQ-4.10.1, REQ-4.10.2, REQ-4.10.3, REQ-4.10.4
- **Test File**: `tests/integration/test_mcp_get_class_hierarchy.py`
- **Test Cases**:

```python
def test_get_class_hierarchy():
    analyzer = setup_test_analyzer()

    hierarchy = analyzer.get_class_hierarchy("DerivedClass")

    assert "class_info" in hierarchy
    assert "base_classes" in hierarchy
    assert "derived_classes" in hierarchy
    assert "base_hierarchy" in hierarchy
    assert "derived_hierarchy" in hierarchy

    assert "BaseClass" in hierarchy["base_classes"]

def test_hierarchy_circular_reference():
    """Test REQ-4.10.3: Handle circular references"""
    analyzer = setup_test_analyzer()

    # Test with potentially circular structure
    hierarchy = analyzer.get_class_hierarchy("SomeClass")

    # Should not hang, should complete
    assert hierarchy is not None
```

### REQ-4.11: get_derived_classes

#### Test-4.11: get_derived_classes Tool
- **Requirements**: REQ-4.11.1, REQ-4.11.2, REQ-4.11.3
- **Test File**: `tests/integration/test_mcp_get_derived_classes.py`
- **Test Cases**:

```python
def test_get_derived_classes():
    analyzer = setup_test_analyzer()

    derived = analyzer.get_derived_classes("BaseClass", project_only=True)

    assert isinstance(derived, list)
    for d in derived:
        assert "name" in d
        assert "base_classes" in d
        assert "BaseClass" in d["base_classes"]
        assert d["is_project"] == True
```

### REQ-4.12: find_callers

#### Test-4.12: find_callers Tool
- **Requirements**: REQ-4.12.1, REQ-4.12.2, REQ-4.12.3, REQ-4.12.4
- **Test File**: `tests/integration/test_mcp_find_callers.py`
- **Test Cases**:

```python
def test_find_callers_function():
    analyzer = setup_test_analyzer()

    callers = analyzer.find_callers("targetFunction")

    assert isinstance(callers, list)
    for c in callers:
        assert "name" in c
        assert "signature" in c
        assert "file" in c

def test_find_callers_method():
    """Test with class_name parameter"""
    analyzer = setup_test_analyzer()

    callers = analyzer.find_callers("process", class_name="DataProcessor")

    assert isinstance(callers, list)
```
### REQ-4.13: find_callees

#### Test-4.13: find_callees Tool
- **Requirements**: REQ-4.13.1, REQ-4.13.2, REQ-4.13.3, REQ-4.13.4
- **Test File**: `tests/integration/test_mcp_find_callees.py`
- **Test Cases**:

```python
def test_find_callees():
    analyzer = setup_test_analyzer()

    callees = analyzer.find_callees("callerFunction")

    assert isinstance(callees, list)
    for c in callees:
        assert "name" in c
        assert "signature" in c
```

### REQ-4.14: get_call_path

#### Test-4.14: get_call_path Tool
- **Requirements**: REQ-4.14.1, REQ-4.14.2, REQ-4.14.3, REQ-4.14.4, REQ-4.14.5
- **Test File**: `tests/integration/test_mcp_get_call_path.py`
- **Test Cases**:

```python
def test_get_call_path():
    analyzer = setup_test_analyzer()

    paths = analyzer.get_call_path("funcA", "funcC", max_depth=10)

    assert isinstance(paths, list)
    assert len(paths) >= 1
    assert isinstance(paths[0], list)
    assert "funcA" in paths[0][0]
    assert "funcC" in paths[0][-1]

def test_call_path_max_depth():
    """Test REQ-4.14.5: Respect max_depth"""
    analyzer = setup_test_analyzer()

    # With limited depth, may not find path
    paths = analyzer.get_call_path("funcA", "funcZ", max_depth=2)
    assert len(paths) == 0 or len(paths[0]) <= 3  # max_depth+1

def test_call_path_method_formatting():
    """Test REQ-4.14.4: ClassName::methodName format"""
    analyzer = setup_test_analyzer()

    paths = analyzer.get_call_path("methodA", "methodB")

    # Methods should be formatted as Class::method
    assert any("::" in step for path in paths for step in path)
```

---

## 5. Compilation Configuration Tests

### REQ-5.1: compile_commands.json Support

#### Test-5.1.1-6: compile_commands.json Loading
- **Requirements**: REQ-5.1.1 through REQ-5.1.6
- **Test File**: `tests/unit/test_compile_commands_loading.py`
- **Test Cases**:

```python
def test_load_compile_commands():
    """Test REQ-5.1.1, REQ-5.1.2: Parse JSON format"""
    cc_data = [
        {
            "directory": "/project",
            "command": "clang++ -std=c++17 -I/usr/include file.cpp",
            "file": "file.cpp"
        },
        {
            "directory": "/project",
            "file": "other.cpp",
            "arguments": ["clang++", "-std=c++20", "other.cpp"]
        }
    ]

    with temp_compile_commands(cc_data) as cc_path:
        manager = CompileCommandsManager(cc_path.parent, {
            "compile_commands_path": "compile_commands.json"
        })

        assert manager.enabled
        assert len(manager.compile_commands) == 2

def test_normalize_file_paths():
    """Test REQ-5.1.3: Normalize to absolute paths"""
    cc_data = [{
        "directory": "/project",
        "file": "relative/path/file.cpp",
        "command": "clang++ file.cpp"
    }]

    with temp_compile_commands(cc_data) as cc_path:
        manager = CompileCommandsManager(cc_path.parent, {})

        # File path should be normalized to absolute
        assert any(os.path.isabs(path) for path in manager.compile_commands.keys())

def test_file_to_args_mapping():
    """Test REQ-5.1.4, REQ-5.1.5: Build file->args mapping"""
    cc_data = [{
        "directory": "/project",
        "file": "/project/test.cpp",
        "arguments": ["clang++", "-std=c++17", "-DTEST"]
    }]

    with temp_compile_commands(cc_data) as cc_path:
        manager = CompileCommandsManager(cc_path.parent, {})

        args = manager.get_compile_args(Path("/project/test.cpp"))

        assert args is not None
        assert "-std=c++17" in args
        assert "-DTEST" in args

def test_command_string_parsing():
    """Test REQ-5.1.2: Parse command strings with shlex (quotes, spaces)"""
    cc_data = [{
        "directory": "/project",
        "file": "/project/test.cpp",
        "command": 'clang++ -I"/path with spaces" -DSTR="hello world" test.cpp'
    }]

    with temp_compile_commands(cc_data) as cc_path:
        manager = CompileCommandsManager(cc_path.parent, {})

        args = manager.get_compile_args(Path("/project/test.cpp"))

        assert args is not None
        # Should correctly parse quoted arguments with spaces
        assert any('path with spaces' in arg for arg in args)
        assert any('hello world' in arg for arg in args)

def test_configurable_path():
    """Test REQ-5.1.6: Configurable compile_commands.json path"""
    with temp_dir() as project:
        custom_path = project / "build" / "compile_commands.json"
        custom_path.parent.mkdir()
        custom_path.write_text('[]')

        manager = CompileCommandsManager(project, {
            "compile_commands_path": "build/compile_commands.json"
        })

        assert manager.compile_commands_path == "build/compile_commands.json"
```

### REQ-5.2: Compilation Argument Fallback

#### Test-5.2.1-4: Fallback Arguments
- **Requirements**: REQ-5.2.1 through REQ-5.2.4
- **Test File**: `tests/unit/test_fallback_args.py`
- **Test Cases**:

```python
def test_fallback_args_structure():
    """Test REQ-5.2.2: Fallback arguments content"""
    manager = CompileCommandsManager(Path("/test"), {})

    args = manager.fallback_args

    assert "-std=c++17" in args
    assert any(arg.startswith("-I") for arg in args)  # Include paths
    assert "-DWIN32" in args or "-D_WIN32" in args  # Preprocessor defines
    assert "-Wno-pragma-once-outside-header" in args
    assert "-x" in args
    assert "c++" in args

@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific")
def test_windows_sdk_paths():
    """Test REQ-5.2.3: Windows SDK includes"""
    manager = CompileCommandsManager(Path("/test"), {})

    args = manager.fallback_args

    # Should include Windows SDK paths
    assert any("Windows Kits" in arg for arg in args)
    assert any("ucrt" in arg for arg in args)
    assert any("um" in arg or "shared" in arg for arg in args)

def test_disable_fallback():
    """Test REQ-5.2.4: Disable fallback via config"""
    manager = CompileCommandsManager(Path("/test"), {
        "fallback_to_hardcoded": False
    })

    args = manager.get_compile_args_with_fallback(Path("nonexistent.cpp"))

    assert len(args) == 0  # No fallback

def test_vcpkg_auto_detection():
    """Test REQ-5.2.5: Automatic vcpkg include path detection"""
    with temp_project() as project:
        # Create vcpkg directory structure
        vcpkg_dir = project / "vcpkg_installed" / "x64-windows" / "include"
        vcpkg_dir.mkdir(parents=True)

        manager = CompileCommandsManager(project, {})
        args = manager.fallback_args

        # Should automatically include vcpkg path
        assert any("vcpkg_installed" in arg for arg in args)
```

### REQ-5.3: Compile Commands Caching

#### Test-5.3.1-5: Caching Behavior
- **Requirements**: REQ-5.3.1 through REQ-5.3.5
- **Test File**: `tests/unit/test_compile_commands_cache.py`
- **Test Cases**:

```python
def test_cache_in_memory():
    """Test REQ-5.3.1: Cache in memory"""
    with temp_compile_commands_file() as cc_path:
        manager = CompileCommandsManager(cc_path.parent, {})

        # First load
        args1 = manager.get_compile_args(Path("test.cpp"))

        # Second load (should be from cache)
        args2 = manager.get_compile_args(Path("test.cpp"))

        assert args1 == args2

def test_track_mtime():
    """Test REQ-5.3.2: Track modification time"""
    with temp_compile_commands_file() as cc_path:
        manager = CompileCommandsManager(cc_path.parent, {})

        initial_mtime = manager.last_modified
        assert initial_mtime > 0

def test_refresh_on_modification():
    """Test REQ-5.3.3: Refresh when modified"""
    with temp_compile_commands_file() as cc_path:
        manager = CompileCommandsManager(cc_path.parent, {})

        initial_count = len(manager.compile_commands)

        # Modify file
        time.sleep(0.1)
        cc_path.write_text('[{"directory":"/test", "file":"new.cpp", "command":"g++ new.cpp"}]')

        # Refresh
        refreshed = manager.refresh_if_needed()

        assert refreshed == True
        assert len(manager.compile_commands) != initial_count

def test_disable_caching():
    """Test REQ-5.3.5: Disable caching"""
    manager = CompileCommandsManager(Path("/test"), {
        "compile_commands_cache_enabled": False
    })

    assert manager.cache_enabled == False
```

### REQ-5.4: File Extension Support

#### Test-5.4.1-2: Extension Handling
- **Requirements**: REQ-5.4.1, REQ-5.4.2
- **Test File**: `tests/unit/test_file_extensions.py`
- **Test Cases**:

```python
def test_supported_extensions():
    """Test REQ-5.4.1: Default supported extensions"""
    scanner = FileScanner(Path("/test"))

    expected = {".cpp", ".cc", ".cxx", ".c++", ".h", ".hpp", ".hxx", ".h++"}
    assert scanner.CPP_EXTENSIONS == expected

def test_custom_extensions():
    """Test REQ-5.4.2: Configurable extensions"""
    manager = CompileCommandsManager(Path("/test"), {
        "supported_extensions": [".cpp", ".h", ".cu"]  # Add CUDA
    })

    assert ".cu" in manager.supported_extensions
```

---

## 6. Caching and Performance Tests

### REQ-6.1: Symbol Cache

#### Test-6.1.1-4: Cache Storage
- **Requirements**: REQ-6.1.1 through REQ-6.1.4
- **Test File**: `tests/integration/test_cache_storage.py`
- **Test Cases**:

```python
def test_cache_directory_structure():
    """Test REQ-6.1.1, REQ-6.1.2: Cache location and structure"""
    with temp_project() as project:
        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        cache_dir = project / ".mcp_cache"
        assert cache_dir.exists()

        # Should have project_name_hash subdirectory
        subdirs = list(cache_dir.iterdir())
        assert len(subdirs) >= 1
        assert subdirs[0].is_dir()

def test_per_file_cache():
    """Test REQ-6.1.3: Per-file caching"""
    with temp_project() as project:
        test_file = project / "test.cpp"
        test_file.write_text("class Test {};")

        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        # Should have per-file cache
        cache_dir = analyzer.cache_manager.cache_dir
        # Check for file-specific cache (implementation-dependent)

def test_overall_index_cache():
    """Test REQ-6.1.4: Overall index saved"""
    with temp_project() as project:
        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        cache_file = analyzer.cache_manager.cache_dir / "cache_info.json"
        assert cache_file.exists()

        with open(cache_file) as f:
            cache_data = json.load(f)

        assert "class_index" in cache_data
        assert "function_index" in cache_data
        assert "file_hashes" in cache_data
        assert "indexed_file_count" in cache_data
```

### REQ-6.2: Cache Invalidation

### Test-6.2.1-4: Invalidation Triggers
- **Requirements**: REQ-6.2.1 through REQ-6.2.4
- **Test File**: `tests/integration/test_cache_invalidation.py`
- **Test Cases**:

```python
def test_invalidate_on_file_change():
    """Test REQ-6.2.1, REQ-6.2.2: File content change"""
    with temp_project() as project:
        test_file = project / "test.cpp"
        test_file.write_text("class A {};")

        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        # Modify file
        test_file.write_text("class A {}; class B {};")

        # Should detect change
        current_hash = analyzer._get_file_hash(str(test_file))
        cached_hash = analyzer.file_hashes.get(str(test_file))

        assert current_hash != cached_hash

        # Refresh should re-index
        refreshed = analyzer.refresh_if_needed()
        assert refreshed == 1

def test_invalidate_on_config_change():
    """Test REQ-6.2.2, REQ-6.2.3: Config file change"""
    with temp_project() as project:
        config_file = project / ".cpp-analyzer-config.json"
        config_file.write_text('{"max_file_size_mb": 5}')

        analyzer1 = CppAnalyzer(project)
        analyzer1.index_project()

        # Modify config
        time.sleep(0.1)
        config_file.write_text('{"max_file_size_mb": 10}')

        # New analyzer should detect change
        analyzer2 = CppAnalyzer(project)
        cache_loaded = analyzer2._load_cache()

        assert cache_loaded == False  # Cache invalidated

def test_invalidate_on_compile_commands_change():
    """Test REQ-6.2.2, REQ-6.2.3: compile_commands.json change"""
    with temp_project_with_cc() as project:
        analyzer1 = CppAnalyzer(project)
        analyzer1.index_project()

        # Modify compile_commands.json
        cc_path = project / "compile_commands.json"
        time.sleep(0.1)
        cc_path.write_text('[{"directory":"/new", "file":"new.cpp", "command":"g++ new.cpp"}]')

        # Should invalidate cache
        analyzer2 = CppAnalyzer(project)
        cache_loaded = analyzer2._load_cache()

        assert cache_loaded == False

def test_invalidate_on_dependencies_change():
    """Test REQ-6.2.2: include_dependencies setting change"""
    with temp_project() as project:
        analyzer1 = CppAnalyzer(project)
        analyzer1.index_project(include_dependencies=True)

        # Load with different dependency setting
        analyzer2 = CppAnalyzer(project)
        # Try to load cache with include_dependencies=False
        # Should invalidate

def test_invalidate_on_cache_version_mismatch():
    """Test REQ-6.2.5: Cache version mismatch invalidation"""
    with temp_project() as project:
        analyzer1 = CppAnalyzer(project)
        analyzer1.index_project()

        # Manually change cache version to simulate old cache
        cache_file = analyzer1.cache_manager.cache_dir / "cache_info.json"
        with open(cache_file, 'r+') as f:
            data = json.load(f)
            data['version'] = '1.0'  # Old version
            f.seek(0)
            json.dump(data, f)
            f.truncate()

        # Should invalidate cache due to version mismatch
        analyzer2 = CppAnalyzer(project)
        cache_loaded = analyzer2._load_cache()

        assert cache_loaded == False
        # Should successfully re-index
        count = analyzer2.index_project()
        assert count > 0
```

### REQ-6.3: Cache Loading

#### Test-6.3.1-4: Cache Load Validation
- **Requirements**: REQ-6.3.1 through REQ-6.3.4
- **Test File**: `tests/integration/test_cache_loading.py`
- **Test Cases**:

```python
def test_load_from_cache():
    """Test REQ-6.3.1: Attempt cache load first"""
    with temp_project() as project:
        # First run
        analyzer1 = CppAnalyzer(project)
        count1 = analyzer1.index_project(force=True)

        # Second run should load from cache
        analyzer2 = CppAnalyzer(project)
        cache_loaded = analyzer2._load_cache()

        assert cache_loaded == True

def test_cache_validation():
    """Test REQ-6.3.2: Validate cache compatibility"""
    # This is tested by invalidation tests
    pass

def test_fallback_on_invalid_cache():
    """Test REQ-6.3.3: Re-parse if cache invalid"""
    with temp_project() as project:
        analyzer1 = CppAnalyzer(project)
        analyzer1.index_project()

        # Corrupt cache
        cache_file = analyzer1.cache_manager.cache_dir / "cache_info.json"
        cache_file.write_text("invalid json{{{")

        # Should fall back to re-parsing
        analyzer2 = CppAnalyzer(project)
        count = analyzer2.index_project()

        assert count > 0  # Successfully re-indexed

def test_rebuild_indexes_from_cache():
    """Test REQ-6.3.4: Rebuild USR and call graph"""
    with temp_project() as project:
        analyzer1 = CppAnalyzer(project)
        analyzer1.index_project()

        # Count USRs and call graph entries
        usr_count = len(analyzer1.usr_index)
        call_count = len(analyzer1.call_graph_analyzer.call_graph)

        # Load from cache
        analyzer2 = CppAnalyzer(project)
        analyzer2._load_cache()

        # Should have same counts
        assert len(analyzer2.usr_index) == usr_count
        # Call graph may need rebuilding
```

### REQ-6.4: Performance Optimizations

#### Test-6.4.1-5: Performance Features
- **Requirements**: REQ-6.4.1 through REQ-6.4.5
- **Test File**: `tests/performance/test_performance.py`
- **Test Cases**:

```python
def test_translation_unit_caching():
    """Test REQ-6.4.1: TU caching"""
    with temp_project() as project:
        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        # Should have cached TUs
        assert len(analyzer.translation_units) > 0

def test_parse_options():
    """Test REQ-6.4.2: Parse with correct options"""
    # Verify parse options include:
    # - PARSE_INCOMPLETE
    # - PARSE_DETAILED_PROCESSING_RECORD
    pass

def test_function_bodies_parsed():
    """Test REQ-6.4.3: Don't skip function bodies"""
    # Verify call graph is built (requires parsing bodies)
    with temp_project() as project:
        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        # If function bodies are skipped, call graph would be empty
        # Verify call graph has entries
        assert len(analyzer.call_graph_analyzer.call_graph) >= 0

@pytest.mark.performance
def test_progress_reporting(capsys):
    """Test REQ-6.4.4, REQ-6.4.5: Progress reporting"""
    with temp_project(num_files=20) as project:
        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        captured = capsys.readouterr()

        # Should see progress info
        assert "files/sec" in captured.err
        assert "Progress:" in captured.err or "Indexing complete" in captured.err

def test_progress_file_persistence():
    """Test REQ-6.4.6: Indexing progress file creation and tracking"""
    with temp_project() as project:
        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        # Find progress file in cache directory
        cache_dir = project / ".mcp_cache"
        progress_files = list(cache_dir.glob("*/indexing_progress.json"))

        assert len(progress_files) >= 1
        progress_file = progress_files[0]

        # Verify file contains expected fields
        with open(progress_file) as f:
            progress = json.load(f)

        assert "total_files" in progress
        assert "indexed_files" in progress
        assert "failed_files" in progress
        assert "cache_hits" in progress
        assert "status" in progress
        assert progress["total_files"] > 0

def test_terminal_detection_for_progress():
    """Test REQ-6.4.7: Adaptive progress reporting based on terminal detection"""
    with temp_project(num_files=10) as project:
        # Mock terminal detection (isatty = True)
        with mock.patch('sys.stderr.isatty', return_value=True):
            analyzer = CppAnalyzer(project)
            # Should report more frequently for terminal
            # (Implementation detail: check reporting frequency)

        # Mock MCP session (non-terminal)
        with env_var("MCP_SESSION_ID", "test_session_123"):
            analyzer2 = CppAnalyzer(project)
            # Should report less frequently for non-terminal
            # (Implementation detail: check reporting frequency)
```

---

## 7. Project Management Tests

### REQ-7.1: Configuration File

#### Test-7.1.1-5: Configuration Loading
- **Requirements**: REQ-7.1.1 through REQ-7.1.5
- **Test File**: `tests/unit/test_configuration.py`
- **Test Cases**:

```python
def test_config_filename():
    """Test REQ-7.1.1: .cpp-analyzer-config.json"""
    assert CppAnalyzerConfig.CONFIG_FILENAME == ".cpp-analyzer-config.json"

def test_config_search_order():
    """Test REQ-7.1.2: ENV var → Project root"""
    with temp_project() as project:
        # Create project config
        project_config = project / ".cpp-analyzer-config.json"
        project_config.write_text('{"max_file_size_mb": 5}')

        # Create ENV config
        with temp_config_file('{"max_file_size_mb": 20}') as env_config:
            with env_var("CPP_ANALYZER_CONFIG", str(env_config)):
                config = CppAnalyzerConfig(project)

                # ENV should win
                assert config.get_max_file_size_mb() == 20

def test_config_structure():
    """Test REQ-7.1.3: Configuration options"""
    with temp_project() as project:
        config_data = {
            "exclude_directories": [".git", "build"],
            "dependency_directories": ["vcpkg"],
            "exclude_patterns": ["*.generated.h"],
            "include_dependencies": False,
            "max_file_size_mb": 15,
            "compile_commands": {
                "enabled": True,
                "path": "build/compile_commands.json"
            },
            "diagnostics": {
                "level": "debug",
                "enabled": True
            }
        }

        config_file = project / ".cpp-analyzer-config.json"
        config_file.write_text(json.dumps(config_data))

        config = CppAnalyzerConfig(project)

        assert config.get_exclude_directories() == [".git", "build"]
        assert config.get_max_file_size_mb() == 15

def test_config_merging():
    """Test REQ-7.1.4: User config merged with defaults"""
    with temp_project() as project:
        # Partial config
        config_file = project / ".cpp-analyzer-config.json"
        config_file.write_text('{"max_file_size_mb": 15}')

        config = CppAnalyzerConfig(project)

        # User setting
        assert config.get_max_file_size_mb() == 15

        # Default settings still present
        assert len(config.get_exclude_directories()) > 0

def test_default_config_fallback():
    """Test REQ-7.1.5: Use defaults if no config"""
    with temp_project() as project:
        # No config file
        config = CppAnalyzerConfig(project)

        # Should have defaults
        assert config.get_max_file_size_mb() == 10  # Default
        assert len(config.get_exclude_directories()) > 0
```

### REQ-7.2: File Discovery

#### Test-7.2.1-4: File Scanning
- **Requirements**: REQ-7.2.1 through REQ-7.2.4
- **Test File**: `tests/unit/test_file_discovery.py`
- **Test Cases**:

```python
def test_recursive_scan():
    """Test REQ-7.2.1: Recursive directory scan"""
    with temp_project_structure() as project:
        scanner = FileScanner(project)
        files = scanner.find_cpp_files()

        # Should find files in subdirectories
        assert any("subdir" in f for f in files)

def test_exclude_directories():
    """Test REQ-7.2.2: Filter by exclude list"""
    with temp_project() as project:
        (project / ".git").mkdir()
        (project / ".git" / "test.cpp").write_text("")
        (project / "src").mkdir()
        (project / "src" / "main.cpp").write_text("")

        scanner = FileScanner(project)
        scanner.EXCLUDE_DIRS = {".git"}
        files = scanner.find_cpp_files()

        # Should not find .git/test.cpp
        assert not any(".git" in f for f in files)
        # Should find src/main.cpp
        assert any("main.cpp" in f for f in files)

def test_skip_large_files():
    """Test REQ-7.2.3: Skip files exceeding size limit"""
    # Implementation-dependent
    pass

def test_dependency_classification():
    """Test REQ-7.2.4: Project vs dependency files"""
    with temp_project() as project:
        (project / "src").mkdir()
        (project / "src" / "main.cpp").write_text("")
        (project / "vcpkg_installed").mkdir()
        (project / "vcpkg_installed" / "lib.cpp").write_text("")

        scanner = FileScanner(project)
        scanner.DEPENDENCY_DIRS = {"vcpkg_installed"}

        # Project file
        assert scanner.is_project_file(str(project / "src" / "main.cpp"))

        # Dependency file
        assert not scanner.is_project_file(str(project / "vcpkg_installed" / "lib.cpp"))
```

### REQ-7.3: Libclang Library Loading

#### Test-7.3.1-4: Library Discovery
- **Requirements**: REQ-7.3.1 through REQ-7.3.4
- **Test File**: `tests/unit/test_libclang_loading.py`
- **Test Cases**:

```python
def test_search_order():
    """Test REQ-7.3.1: Bundled → System → LLVM"""
    # This is tested by the actual loading logic
    # Verify function find_and_configure_libclang exists
    from mcp_server.cpp_mcp_server import find_and_configure_libclang
    assert callable(find_and_configure_libclang)

def test_platform_library_names():
    """Test REQ-7.3.2: Platform-specific names"""
    # Verify correct extension for platform
    import platform
    system = platform.system()

    if system == "Windows":
        # Should look for .dll
        pass
    elif system == "Darwin":
        # Should look for .dylib
        pass
    else:
        # Should look for .so
        pass

@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific")
def test_macos_libclang_paths():
    """Test REQ-7.3.2: macOS-specific libclang search paths"""
    from mcp_server.cpp_mcp_server import find_and_configure_libclang

    # Should check in order:
    # 1. Bundled lib/macos/
    # 2. /usr/local/lib
    # 3. /opt/homebrew/lib
    # 4. Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib
    # 5. llvm-config paths
    # Verify search logic covers these paths

@pytest.mark.skipif(sys.platform != "linux", reason="Linux-specific")
def test_linux_libclang_paths():
    """Test REQ-7.3.2: Linux-specific libclang search paths"""
    from mcp_server.cpp_mcp_server import find_and_configure_libclang

    # Should check in order:
    # 1. Bundled lib/linux/
    # 2. /usr/lib/llvm-*
    # 3. /usr/lib/x86_64-linux-gnu/
    # 4. llvm-config paths
    # Verify search logic covers these paths

@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific")
def test_windows_libclang_paths():
    """Test REQ-7.3.2: Windows-specific libclang search paths"""
    from mcp_server.cpp_mcp_server import find_and_configure_libclang

    # Should check in order:
    # 1. Bundled lib/windows/
    # 2. Program Files LLVM
    # 3. vcpkg installed
    # 4. Anaconda/conda environments
    # 5. llvm-config paths
    # Verify search logic covers these paths

def test_library_reporting():
    """Test REQ-7.3.3: Report which library used"""
    # Verify diagnostic message is output
    pass

def test_missing_library_error():
    """Test REQ-7.3.4: Clear error if not found"""
    # Mock all library paths to not exist
    # Verify clear error message
    pass
```

### REQ-7.4: Error Handling

#### Test-7.4.1-3: Graceful Error Handling
- **Requirements**: REQ-7.4.1 through REQ-7.4.3
- **Test File**: `tests/integration/test_error_handling.py`
- **Test Cases**:

```python
def test_parse_errors_dont_fail_indexing():
    """Test REQ-7.4.1: Handle parse errors gracefully"""
    with temp_project() as project:
        # Create broken file
        broken = project / "broken.cpp"
        broken.write_text("class Broken { invalid syntax }")

        # Create valid file
        valid = project / "valid.cpp"
        valid.write_text("class Valid {};")

        analyzer = CppAnalyzer(project)
        count = analyzer.index_project()
        # Should index valid file despite broken file
        assert count >= 1
        classes = analyzer.search_classes("Valid")
        assert len(classes) == 1

def test_missing_files_handled():
    """Test REQ-7.4.2: Handle missing files"""
    with temp_project() as project:
        test_file = project / "test.cpp"
        test_file.write_text("class Test {};")

        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        # Delete file
        test_file.unlink()

        # Refresh should handle gracefully
        analyzer.refresh_if_needed()

        # File should be removed from indexes
        assert len(analyzer.search_classes("Test")) == 0

def test_libclang_diagnostics_handled():
    """Test REQ-7.4.3: Handle libclang diagnostics"""
    # Create file with warnings/errors
    with temp_project() as project:
        test_file = project / "test.cpp"
        test_file.write_text("""
            #warning "This is a warning"
            class Test {};
        """)

        analyzer = CppAnalyzer(project)
        count = analyzer.index_project()

        # Should index despite warning
        assert count >= 1
```

### REQ-7.5: Diagnostics and Logging

#### Test-7.5.1-4: Diagnostic System
- **Requirements**: REQ-7.5.1 through REQ-7.5.4
- **Test File**: `tests/unit/test_diagnostics.py`
- **Test Cases**:

```python
def test_diagnostic_levels():
    """Test REQ-7.5.1: Support all levels"""
    from mcp_server.diagnostics import DiagnosticLevel

    assert hasattr(DiagnosticLevel, 'DEBUG')
    assert hasattr(DiagnosticLevel, 'INFO')
    assert hasattr(DiagnosticLevel, 'WARNING')
    assert hasattr(DiagnosticLevel, 'ERROR')
    assert hasattr(DiagnosticLevel, 'FATAL')

def test_diagnostics_to_stderr():
    """Test REQ-7.5.2: Output to stderr"""
    from mcp_server import diagnostics

    # Verify logger outputs to stderr
    assert diagnostics.logger.output_stream == sys.stderr

def test_configurable_level():
    """Test REQ-7.5.3: Configurable level via config file"""
    with temp_project() as project:
        config_file = project / ".cpp-analyzer-config.json"
        config_file.write_text('{"diagnostics": {"level": "error"}}')

        config = CppAnalyzerConfig(project)
        # Verify level is set
        # (Implementation-dependent)

def test_diagnostic_level_from_env():
    """Test REQ-7.5.3: Configurable level via environment variable"""
    with env_var("CPP_ANALYZER_DIAGNOSTIC_LEVEL", "ERROR"):
        from mcp_server import diagnostics
        # Verify diagnostic level is set to ERROR
        # Environment variable should override default settings
        # (Implementation-dependent)

def test_enable_disable():
    """Test REQ-7.5.4: Enable/disable diagnostics"""
    from mcp_server import diagnostics

    diagnostics.logger.set_enabled(False)
    # Verify no output

    diagnostics.logger.set_enabled(True)
    # Verify output resumes
```

---

## 8. Test Fixtures Required

### 8.1 Minimal Fixtures (Unit Tests)

```
tests/fixtures/
├── classes/
│   ├── simple_class.h              # class MyClass {};
│   ├── simple_struct.h             # struct MyStruct {};
│   ├── template_class.h            # template<typename T> class Vector {};
│   ├── nested_class.h              # Outer::Inner
│   ├── forward_decl.h              # Forward + full declaration
│   ├── anonymous_struct.h          # struct { int x; };
│   └── abstract_class.h            # Pure virtual methods
├── inheritance/
│   ├── single_inheritance.h        # Derived : Base
│   ├── multiple_inheritance.h      # Derived : Base1, Base2
│   ├── virtual_inheritance.h       # Derived : virtual Base
│   └── deep_hierarchy.h            # GrandChild->Child->Parent->GrandParent
├── functions/
│   ├── global_functions.cpp        # Global functions
│   ├── static_func.cpp             # static void func()
│   ├── inline_func.h               # inline int func()
│   ├── constexpr_func.h            # constexpr int func()
│   ├── template_func.h             # template<typename T> T max()
│   ├── overloads.cpp               # Multiple overloaded()
│   ├── variadic.cpp                # void func(int, ...)
│   ├── operators.cpp               # operator+, operator==
│   └── class_methods.h             # Class with methods
├── methods/
│   ├── regular.h                   # void method()
│   ├── static_method.h             # static void method()
│   ├── const_method.h              # void method() const
│   ├── virtual_method.h            # virtual void method()
│   ├── pure_virtual.h              # virtual void method() = 0
│   ├── override.h                  # void method() override
│   ├── final.h                     # void method() final
│   ├── constructors.h              # Various constructors
│   ├── destructor.h                # ~MyClass()
│   ├── virtual_destructor.h        # virtual ~MyClass()
│   └── operator_methods.h          # Operator overloads as methods
├── templates/
│   ├── class_template.h            # template<typename T> class
│   ├── function_template.h         # template<typename T> T func()
│   ├── specialization.h            # Template specializations
│   └── variadic_template.h         # template<typename... Args>
├── namespaces/
│   ├── named_namespace.h           # namespace MyNamespace {}
│   ├── nested_namespace.h          # namespace Outer::Inner {}
│   └── anonymous_namespace.cpp     # namespace {}
├── call_graph/
│   ├── simple_calls.cpp            # A calls B calls C
│   ├── method_calls.cpp            # obj.method()
│   ├── static_calls.cpp            # Class::staticMethod()
│   ├── virtual_calls.cpp           # Virtual dispatch
│   ├── call_chain.cpp              # Long call chain
│   ├── overloaded_calls.cpp        # Calls to overloaded functions
│   └── complex_calls.cpp           # Multiple call patterns
├── relationships/
│   ├── inheritance_tree.h          # Animal -> Dog, Cat
│   ├── deep_hierarchy.h            # Multi-level inheritance
│   └── class_with_methods.h        # Class with multiple methods
└── files/
    └── multi_symbol_file.h         # Multiple classes/functions in one file
```

### 8.2 Integration Fixtures

```
tests/fixtures/projects/
├── minimal/                        # Minimal valid project
│   ├── main.cpp
│   └── simple.h
├── with_dependencies/              # Project + dependency separation
│   ├── src/
│   │   └── main.cpp
│   ├── vcpkg_installed/
│   │   └── include/
│   │       └── lib.h
│   └── .cpp-analyzer-config.json
├── with_compile_commands/          # Project with compile_commands.json
│   ├── src/
│   │   └── main.cpp
│   └── compile_commands.json
├── large_project/                  # 50+ files for parallel testing
│   └── src/
│       ├── file001.cpp ... file050.cpp
└── real_world/                     # Realistic project structure
    ├── include/
    ├── src/
    ├── third_party/
    └── CMakeLists.txt
```

### 8.3 Test Utilities

```python
# tests/test_utils.py
import json
from unittest import mock
from contextlib import contextmanager

def create_temp_project(num_files=5):
    """Create temporary project with N files"""
    pass

def setup_test_analyzer(fixture_path=None):
    """Setup analyzer with test fixture"""
    pass

def index_fixture(fixture_path):
    """Index a specific fixture file"""
    pass

def temp_compile_commands(data):
    """Create temporary compile_commands.json"""
    pass

@contextmanager
def env_var(name, value):
    """Context manager for environment variables"""
    import os
    old_value = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if old_value is None:
            del os.environ[name]
        else:
            os.environ[name] = old_value

def temp_dir():
    """Context manager for temporary directory"""
    pass

def temp_config_file(content):
    """Create temporary config file with content"""
    pass

def temp_project_with_cc():
    """Create temporary project with compile_commands.json"""
    pass

def modify_compile_commands(cc_path):
    """Modify compile_commands.json for testing"""
    pass

def temp_project_structure():
    """Create temp project with subdirectories"""
    pass
```

---

## Test Execution Strategy

### Phase 1: Unit Tests (Fast, ~1000 tests)
- Run on every commit
- Should complete in < 30 seconds
- Focus: Individual components

### Phase 2: Integration Tests (Medium, ~200 tests)
- Run on PR creation
- Should complete in < 5 minutes
- Focus: Component interactions

### Phase 3: End-to-End Tests (Slow, ~20 tests)
- Run nightly or on release
- May take 10-30 minutes
- Focus: Real-world scenarios

### Phase 4: Performance Tests
- Run weekly or on-demand
- Benchmark against baseline
- Track: Speed, memory, cache hit rates

---

## Coverage Goals

- **Line Coverage**: 80%+ overall
- **Branch Coverage**: 70%+ for critical paths
- **Requirement Coverage**: 100% (every REQ-X.X tested)
- **Edge Case Coverage**: Input validation, error conditions, platform-specific behavior
- **Integration Coverage**: Cross-component interactions (caching + refresh, compile_commands + parsing, etc.)

---

## Test Metrics to Track

1. **Requirement Coverage**: % of requirements with tests
2. **Code Coverage**: Line/branch coverage %
3. **Test Count**: Total tests per category
4. **Test Duration**: Time per test suite
5. **Failure Rate**: Flaky tests identified
6. **Performance**: Benchmark trends

---
