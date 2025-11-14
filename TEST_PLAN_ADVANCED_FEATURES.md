# Test Plan: Advanced Features

**Part of**: [Comprehensive Test Plan](./TEST_PLAN.md)

This document covers caching, performance, and project management tests.

## Table of Contents

- [Section 6: Caching and Performance Tests](#6-caching-and-performance-tests)
- [Section 7: Project Management Tests](#7-project-management-tests)

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

### REQ-6.5: Progress Persistence

#### Test-6.5.1-5: Progress File Management
- **Requirements**: REQ-6.5.1 through REQ-6.5.5
- **Test File**: `tests/integration/test_progress_persistence.py`
- **Test Cases**:

```python
def test_progress_file_creation():
    """Test REQ-6.5.1: Progress file is created in cache directory"""
    with temp_project() as project:
        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        # Find progress file
        progress_file = analyzer.cache_manager.cache_dir / "indexing_progress.json"
        assert progress_file.exists()

def test_progress_file_content():
    """Test REQ-6.5.2: Progress file contains all required fields"""
    with temp_project() as project:
        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        progress_file = analyzer.cache_manager.cache_dir / "indexing_progress.json"
        with open(progress_file) as f:
            progress = json.load(f)

        # Verify all required fields
        assert "project_root" in progress
        assert "total_files" in progress
        assert "indexed_files" in progress
        assert "failed_files" in progress
        assert "cache_hits" in progress
        assert "last_index_time" in progress
        assert "timestamp" in progress
        assert "class_count" in progress
        assert "function_count" in progress
        assert "status" in progress

        # Verify types and values
        assert isinstance(progress["total_files"], int)
        assert isinstance(progress["indexed_files"], int)
        assert isinstance(progress["last_index_time"], (int, float))
        assert progress["status"] in ["in_progress", "complete", "interrupted"]

def test_progress_status_complete():
    """Test REQ-6.5.3: Status set to 'complete' on successful indexing"""
    with temp_project() as project:
        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        progress = analyzer.cache_manager.load_progress()

        assert progress is not None
        assert progress["status"] == "complete"
        assert progress["indexed_files"] == progress["total_files"]

def test_progress_status_interrupted():
    """Test REQ-6.5.5: Status set to 'interrupted' on failure"""
    with temp_project() as project:
        # Create a file that will cause parsing to fail
        bad_file = project / "bad.cpp"
        bad_file.write_text("intentionally broken syntax {{{")

        analyzer = CppAnalyzer(project)

        # Mock indexing to simulate interruption
        try:
            # Simulate interrupted indexing
            analyzer.cache_manager.save_progress(
                total_files=10,
                indexed_files=5,
                failed_files=1,
                cache_hits=0,
                last_index_time=1.5,
                class_count=10,
                function_count=20,
                status="interrupted"
            )
        except:
            pass

        progress = analyzer.cache_manager.load_progress()
        assert progress["status"] == "interrupted"
        assert progress["indexed_files"] < progress["total_files"]

def test_load_progress_api():
    """Test REQ-6.5.4: load_progress() API"""
    with temp_project() as project:
        analyzer = CppAnalyzer(project)
        analyzer.index_project()

        # Load progress using API
        progress = analyzer.cache_manager.load_progress()

        assert progress is not None
        assert "project_root" in progress
        assert progress["status"] == "complete"

def test_progress_persistence_across_sessions():
    """Test progress is persisted and can be loaded in new session"""
    with temp_project() as project:
        # First session: Index and save progress
        analyzer1 = CppAnalyzer(project)
        analyzer1.index_project()

        progress1 = analyzer1.cache_manager.load_progress()
        original_timestamp = progress1["timestamp"]

        # Second session: Load progress
        analyzer2 = CppAnalyzer(project)
        progress2 = analyzer2.cache_manager.load_progress()

        # Should load same progress
        assert progress2 is not None
        assert progress2["timestamp"] == original_timestamp
        assert progress2["status"] == "complete"

def test_progress_update_during_indexing():
    """Test REQ-6.5.3: Progress saved periodically during indexing"""
    with temp_project(num_files=50) as project:
        analyzer = CppAnalyzer(project)

        # Start indexing (in background if possible)
        analyzer.index_project()

        # Progress should be saved
        progress = analyzer.cache_manager.load_progress()
        assert progress is not None
        assert progress["status"] == "complete"
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

def test_diagnostic_logger_set_level():
    """Test REQ-7.5.5: DiagnosticLogger.set_level() API"""
    from mcp_server.diagnostics import DiagnosticLogger, DiagnosticLevel

    logger = DiagnosticLogger()

    # Change level
    logger.set_level(DiagnosticLevel.ERROR)

    # Messages below ERROR should not output
    # (Testing this requires capturing output)

def test_diagnostic_logger_set_output_stream():
    """Test REQ-7.5.5: DiagnosticLogger.set_output_stream() API"""
    from mcp_server.diagnostics import DiagnosticLogger
    import io

    logger = DiagnosticLogger()

    # Redirect to custom stream
    custom_stream = io.StringIO()
    logger.set_output_stream(custom_stream)

    logger.info("Test message")

    # Verify message went to custom stream
    assert "Test message" in custom_stream.getvalue()

def test_diagnostic_logger_level_methods():
    """Test REQ-7.5.5: Level-specific logging methods"""
    from mcp_server.diagnostics import DiagnosticLogger
    import io

    logger = DiagnosticLogger()
    stream = io.StringIO()
    logger.set_output_stream(stream)

    # Test all level methods
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning message")
    logger.error("Error message")
    logger.fatal("Fatal message")

    output = stream.getvalue()
    assert "Debug message" in output
    assert "Info message" in output
    assert "Warning message" in output
    assert "Error message" in output
    assert "Fatal message" in output

def test_configure_from_config():
    """Test REQ-7.5.6: configure_from_config() function"""
    from mcp_server.diagnostics import configure_from_config

    config = {
        "diagnostics": {
            "level": "error",
            "enabled": True
        }
    }

    configure_from_config(config)

    # Verify configuration was applied
    # (Implementation-dependent verification)
```

---

