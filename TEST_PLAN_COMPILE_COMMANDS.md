# Test Plan: Compilation Configuration

**Part of**: [Comprehensive Test Plan](./TEST_PLAN.md)

This document covers compile_commands.json handling, vcpkg integration, and compilation configuration tests.

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

### REQ-5.5: vcpkg Integration

#### Test-5.5.1-3: vcpkg Auto-Detection
- **Requirements**: REQ-5.5.1 through REQ-5.5.3
- **Test File**: `tests/integration/test_vcpkg_integration.py`
- **Test Cases**:

```python
def test_vcpkg_detection():
    """Test REQ-5.5.1: Automatic vcpkg detection"""
    with temp_project() as project:
        # Create vcpkg directory structure
        vcpkg_dir = project / "vcpkg_installed" / "x64-windows" / "include"
        vcpkg_dir.mkdir(parents=True)

        # Create another triplet
        vcpkg_dir2 = project / "vcpkg_installed" / "x64-linux" / "include"
        vcpkg_dir2.mkdir(parents=True)

        analyzer = CppAnalyzer(project)

        # Should detect vcpkg directory
        assert any("vcpkg_installed" in path for path in analyzer.compile_commands_manager.fallback_args)

def test_vcpkg_include_paths():
    """Test REQ-5.5.2: vcpkg include paths added to fallback"""
    with temp_project() as project:
        vcpkg_dir = project / "vcpkg_installed" / "x64-windows" / "include"
        vcpkg_dir.mkdir(parents=True)

        analyzer = CppAnalyzer(project)
        args = analyzer.compile_commands_manager.fallback_args

        # Should include vcpkg paths for all found triplets
        assert any("x64-windows/include" in arg for arg in args)

def test_vcpkg_with_compile_commands():
    """Test REQ-5.5.3: vcpkg paths added when compile_commands exists"""
    with temp_project() as project:
        # Create vcpkg directory
        vcpkg_dir = project / "vcpkg_installed" / "x64-windows" / "include"
        vcpkg_dir.mkdir(parents=True)

        # Create minimal compile_commands.json
        cc_path = project / "compile_commands.json"
        cc_path.write_text('[{"directory": "/test", "file": "test.cpp", "command": "g++ test.cpp"}]')

        analyzer = CppAnalyzer(project)

        # vcpkg paths should still be in fallback args
        assert any("vcpkg_installed" in arg for arg in analyzer.compile_commands_manager.fallback_args)

def test_no_vcpkg_directory():
    """Test graceful handling when no vcpkg directory exists"""
    with temp_project() as project:
        analyzer = CppAnalyzer(project)
        args = analyzer.compile_commands_manager.fallback_args

        # Should not have vcpkg paths
        assert not any("vcpkg_installed" in arg for arg in args)
        # But should still have other fallback args
        assert "-std=c++17" in args
```

### REQ-5.6: Compile Commands Manager Extended APIs

#### Test-5.6.1-6: Extended API Tests
- **Requirements**: REQ-5.6.1 through REQ-5.6.6
- **Test File**: `tests/unit/test_compile_commands_apis.py`
- **Test Cases**:

```python
def test_get_stats_api():
    """Test REQ-5.6.1: get_stats() API"""
    with temp_compile_commands_file() as cc_path:
        manager = CompileCommandsManager(cc_path.parent, {})
        stats = manager.get_stats()

        assert "enabled" in stats
        assert "compile_commands_count" in stats
        assert "file_mapping_count" in stats
        assert "cache_enabled" in stats
        assert "fallback_enabled" in stats
        assert "last_modified" in stats
        assert "compile_commands_path" in stats

        assert stats["enabled"] == True
        assert stats["compile_commands_count"] >= 0
        assert stats["cache_enabled"] == True

def test_is_file_supported():
    """Test REQ-5.6.2: is_file_supported() API"""
    cc_data = [{
        "directory": "/project",
        "file": "/project/test.cpp",
        "command": "g++ test.cpp"
    }]

    with temp_compile_commands(cc_data) as cc_path:
        manager = CompileCommandsManager(cc_path.parent, {})

        # File in compile commands
        assert manager.is_file_supported(Path("/project/test.cpp")) == True

        # File not in compile commands
        assert manager.is_file_supported(Path("/project/other.cpp")) == False

def test_get_all_files():
    """Test REQ-5.6.3: get_all_files() API"""
    cc_data = [
        {"directory": "/project", "file": "/project/a.cpp", "command": "g++ a.cpp"},
        {"directory": "/project", "file": "/project/b.cpp", "command": "g++ b.cpp"}
    ]

    with temp_compile_commands(cc_data) as cc_path:
        manager = CompileCommandsManager(cc_path.parent, {})
        files = manager.get_all_files()

        assert len(files) == 2
        assert "/project/a.cpp" in files
        assert "/project/b.cpp" in files

def test_should_process_file():
    """Test REQ-5.6.4: should_process_file() API"""
    cc_data = [{
        "directory": "/project",
        "file": "/project/test.cpp",
        "command": "g++ test.cpp"
    }]

    with temp_compile_commands(cc_data) as cc_path:
        manager = CompileCommandsManager(cc_path.parent, {})

        # File with compile commands
        assert manager.should_process_file(Path("/project/test.cpp")) == True

        # File without compile commands but supported extension
        assert manager.should_process_file(Path("/project/other.cpp")) == True

        # File with unsupported extension
        assert manager.should_process_file(Path("/project/file.txt")) == False

def test_is_extension_supported():
    """Test REQ-5.6.5: is_extension_supported() API"""
    manager = CompileCommandsManager(Path("/test"), {})

    # Supported extensions
    assert manager.is_extension_supported(Path("test.cpp")) == True
    assert manager.is_extension_supported(Path("test.h")) == True
    assert manager.is_extension_supported(Path("test.hpp")) == True

    # Unsupported extensions
    assert manager.is_extension_supported(Path("test.txt")) == False
    assert manager.is_extension_supported(Path("test.py")) == False

def test_clear_cache_api():
    """Test REQ-5.6.6: clear_cache() API"""
    cc_data = [{
        "directory": "/project",
        "file": "/project/test.cpp",
        "command": "g++ test.cpp"
    }]

    with temp_compile_commands(cc_data) as cc_path:
        manager = CompileCommandsManager(cc_path.parent, {})

        # Verify cache is populated
        assert len(manager.compile_commands) > 0
        assert manager.last_modified > 0

        # Clear cache
        manager.clear_cache()

        # Verify cache is cleared
        assert len(manager.compile_commands) == 0
        assert len(manager.file_to_command_map) == 0
        assert manager.last_modified == 0
```

---

