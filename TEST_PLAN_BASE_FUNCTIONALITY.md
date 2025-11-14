# Test Plan: Base Functionality

**Part of**: [Comprehensive Test Plan](./TEST_PLAN.md)

This document covers core functional requirements, entity extraction, and entity relationships.

## Table of Contents

1. [Core Functional Requirements Tests (REQ-1.x)](#1-core-functional-requirements-tests)
2. [Entity Extraction Tests (REQ-2.x)](#2-entity-extraction-tests)
3. [Entity Relationship Tests (REQ-3.x)](#3-entity-relationship-tests)

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

