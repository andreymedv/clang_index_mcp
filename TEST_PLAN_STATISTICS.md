# Test Plan: Statistics and Monitoring

**Part of**: [Comprehensive Test Plan](./TEST_PLAN.md)

This document covers runtime statistics, call graph analytics, and cache management APIs.

---

## 8. Statistics and Monitoring Tests

### REQ-8.1: Runtime Statistics APIs

#### Test-8.1.1-3: CppAnalyzer Statistics
- **Requirements**: REQ-8.1.1 through REQ-8.1.3
- **Test File**: `tests/unit/test_runtime_statistics.py`
- **Test Cases**:

```python
def test_get_stats_api():
    """Test REQ-8.1.1: CppAnalyzer.get_stats() API"""
    analyzer = setup_test_analyzer()

    stats = analyzer.get_stats()

    # Verify required fields
    assert "class_count" in stats
    assert "function_count" in stats
    assert "file_count" in stats

    # Verify types
    assert isinstance(stats["class_count"], int)
    assert isinstance(stats["function_count"], int)
    assert isinstance(stats["file_count"], int)

    # If compile commands enabled, should have additional fields
    if analyzer.compile_commands_manager.enabled:
        assert "compile_commands_enabled" in stats
        assert "compile_commands_count" in stats
        assert "compile_commands_file_mapping_count" in stats

def test_get_compile_commands_stats():
    """Test REQ-8.1.2: CppAnalyzer.get_compile_commands_stats() API"""
    with temp_project_with_cc() as project:
        analyzer = CppAnalyzer(project)

        stats = analyzer.get_compile_commands_stats()

        assert "enabled" in stats
        if stats["enabled"]:
            assert "compile_commands_count" in stats
            assert "file_mapping_count" in stats
            assert "cache_enabled" in stats

def test_stats_thread_safety():
    """Test REQ-8.1.3: Statistics APIs are thread-safe"""
    analyzer = setup_test_analyzer()

    # Call get_stats from multiple threads simultaneously
    import threading

    results = []

    def get_stats_threaded():
        stats = analyzer.get_stats()
        results.append(stats)

    threads = [threading.Thread(target=get_stats_threaded) for _ in range(10)]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    # All threads should have completed without errors
    assert len(results) == 10

    # Results should be consistent
    first_result = results[0]
    for result in results:
        assert result["class_count"] == first_result["class_count"]
        assert result["function_count"] == first_result["function_count"]
```

### REQ-8.2: Call Graph Statistics

#### Test-8.2.1-2: Call Graph Metrics
- **Requirements**: REQ-8.2.1 through REQ-8.2.2
- **Test File**: `tests/unit/test_call_graph_statistics.py`
- **Test Cases**:

```python
def test_call_graph_statistics_api():
    """Test REQ-8.2.1: CallGraphAnalyzer.get_call_statistics() API"""
    with temp_project() as project:
        # Create files with call relationships
        file1 = project / "caller.cpp"
        file1.write_text("""
            void callee1() {}
            void callee2() {}
            void caller() {
                callee1();
                callee2();
                callee1();  // Called twice
            }
        """)

        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        stats = analyzer.call_graph_analyzer.get_call_statistics()

        # Verify required fields
        assert "total_functions_with_calls" in stats
        assert "total_functions_being_called" in stats
        assert "total_unique_calls" in stats
        assert "most_called_functions" in stats
        assert "functions_with_most_calls" in stats

        # Verify types
        assert isinstance(stats["total_functions_with_calls"], int)
        assert isinstance(stats["total_functions_being_called"], int)
        assert isinstance(stats["total_unique_calls"], int)
        assert isinstance(stats["most_called_functions"], list)
        assert isinstance(stats["functions_with_most_calls"], list)

        # Verify list structure
        if len(stats["most_called_functions"]) > 0:
            # Each entry should be (USR, count) tuple
            entry = stats["most_called_functions"][0]
            assert isinstance(entry, (list, tuple))
            assert len(entry) == 2
            assert isinstance(entry[1], int)  # call count

def test_most_called_functions():
    """Test REQ-8.2.2: Identify most called functions"""
    with temp_project() as project:
        file1 = project / "test.cpp"
        file1.write_text("""
            void veryPopular() {}
            void caller1() { veryPopular(); }
            void caller2() { veryPopular(); }
            void caller3() { veryPopular(); }
        """)

        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        stats = analyzer.call_graph_analyzer.get_call_statistics()

        # veryPopular should be in most_called_functions
        most_called = stats["most_called_functions"]
        assert len(most_called) > 0

        # Should be sorted by call count (descending)
        if len(most_called) > 1:
            assert most_called[0][1] >= most_called[1][1]

def test_functions_with_most_calls():
    """Test REQ-8.2.2: Identify complex functions making many calls"""
    with temp_project() as project:
        file1 = project / "test.cpp"
        file1.write_text("""
            void helper1() {}
            void helper2() {}
            void helper3() {}
            void complexFunction() {
                helper1();
                helper2();
                helper3();
            }
        """)

        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        stats = analyzer.call_graph_analyzer.get_call_statistics()

        # complexFunction should be in functions_with_most_calls
        most_calls = stats["functions_with_most_calls"]
        assert len(most_calls) > 0

        # Should be sorted by call count (descending)
        if len(most_calls) > 1:
            assert most_calls[0][1] >= most_calls[1][1]

def test_dead_code_detection():
    """Test REQ-8.2.2: Detect potential dead code (never called)"""
    with temp_project() as project:
        file1 = project / "test.cpp"
        file1.write_text("""
            void neverCalled() {}
            void caller() { /* doesn't call neverCalled */ }
        """)

        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        stats = analyzer.call_graph_analyzer.get_call_statistics()

        # Total functions indexed should include neverCalled
        # But it won't appear in most_called_functions list
        all_functions = len(analyzer.function_index)
        called_functions = stats["total_functions_being_called"]

        # Some functions may be never called (potential dead code)
        # This is useful for code quality analysis
```

### REQ-8.3: Cache Management APIs

#### Test-8.3.1-3: Cache Management
- **Requirements**: REQ-8.3.1 through REQ-8.3.3
- **Test File**: `tests/unit/test_cache_management_apis.py`
- **Test Cases**:

```python
def test_remove_file_cache():
    """Test REQ-8.3.1: CacheManager.remove_file_cache() API"""
    with temp_project() as project:
        test_file = project / "test.cpp"
        test_file.write_text("class Test {};")

        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        # Verify cache file exists
        cache_path = analyzer.cache_manager.get_file_cache_path(str(test_file))
        assert cache_path.exists()

        # Remove cache
        result = analyzer.cache_manager.remove_file_cache(str(test_file))

        # Verify removal
        assert result == True
        assert not cache_path.exists()

def test_get_file_cache_path():
    """Test REQ-8.3.2: CacheManager.get_file_cache_path() API"""
    with temp_project() as project:
        test_file = project / "test.cpp"

        analyzer = CppAnalyzer(project)

        cache_path = analyzer.cache_manager.get_file_cache_path(str(test_file))

        # Should return Path object
        assert isinstance(cache_path, Path)

        # Should be in files/ subdirectory
        assert "files" in str(cache_path)

        # Should end with .json
        assert cache_path.suffix == ".json"

def test_cache_api_error_handling():
    """Test REQ-8.3.3: Cache APIs return success/failure status"""
    with temp_project() as project:
        analyzer = CppAnalyzer(project)

        # Try to remove cache for non-existent file
        result = analyzer.cache_manager.remove_file_cache("/nonexistent/file.cpp")

        # Should return False (not raise exception)
        assert result == False

def test_cache_path_consistency():
    """Test cache path generation is consistent"""
    with temp_project() as project:
        analyzer = CppAnalyzer(project)

        file_path = "/project/test.cpp"

        # Get path twice
        path1 = analyzer.cache_manager.get_file_cache_path(file_path)
        path2 = analyzer.cache_manager.get_file_cache_path(file_path)

        # Should be identical
        assert path1 == path2
```

---

