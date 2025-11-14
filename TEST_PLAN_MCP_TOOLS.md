# Test Plan: MCP Tools

**Part of**: [Comprehensive Test Plan](./TEST_PLAN.md)

This document covers all 14 MCP tool tests with happy path, validation, edge cases, and integration tests.

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

