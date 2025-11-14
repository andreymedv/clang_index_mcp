#!/usr/bin/env python3
"""
Pytest configuration and shared fixtures for Clang Index MCP test suite.

This module provides pytest fixtures that can be used across all test modules.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Any
import pytest

# Add the mcp_server directory to the path
import sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server.compile_commands_manager import CompileCommandsManager

# Import test helpers
from tests.utils.test_helpers import (
    temp_project,
    temp_compile_commands,
    temp_config_file,
    setup_test_analyzer,
    cleanup_temp_analyzer
)


# ============================================================================
# Session-scoped Fixtures (Created once per test session)
# ============================================================================

@pytest.fixture(scope="session")
def session_temp_dir():
    """
    Create a temporary directory for the entire test session.

    Yields:
        Path: Path to session-wide temporary directory

    Cleanup: Automatically removed after all tests complete
    """
    temp_dir = tempfile.mkdtemp(prefix="test_session_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


# ============================================================================
# Function-scoped Fixtures (Created for each test function)
# ============================================================================

@pytest.fixture
def temp_dir():
    """
    Create a temporary directory for a single test.

    Yields:
        Path: Path to temporary directory

    Cleanup: Automatically removed after test completes

    Example:
        def test_something(temp_dir):
            file_path = temp_dir / "test.txt"
            file_path.write_text("test content")
    """
    temp_path = tempfile.mkdtemp(prefix="test_")
    yield Path(temp_path)
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def temp_project_dir(temp_dir):
    """
    Create a temporary project directory with standard structure.

    Yields:
        Path: Path to project root with src/, include/, tests/ subdirectories

    Example:
        def test_project(temp_project_dir):
            (temp_project_dir / "src" / "main.cpp").write_text("int main() {}")
    """
    project_root = temp_dir / "project"
    project_root.mkdir()
    (project_root / "src").mkdir()
    (project_root / "include").mkdir()
    (project_root / "tests").mkdir()
    yield project_root


@pytest.fixture
def cache_dir(temp_dir):
    """
    Create a temporary cache directory.

    Yields:
        Path: Path to cache directory

    Example:
        def test_caching(cache_dir):
            cache_file = cache_dir / "test_cache.json"
            # Use cache_file
    """
    cache_path = temp_dir / ".cache"
    cache_path.mkdir()
    yield cache_path


# ============================================================================
# Analyzer Fixtures
# ============================================================================

@pytest.fixture
def analyzer(temp_project_dir):
    """
    Create a CppAnalyzer instance with a temporary project.

    Yields:
        CppAnalyzer: Analyzer instance pointing to temp project

    Cleanup: Project directory automatically removed after test

    Example:
        def test_indexing(analyzer):
            (Path(analyzer.project_root) / "src" / "main.cpp").write_text(
                "int main() { return 0; }"
            )
            analyzer.index_project()
            assert len(analyzer.function_index) > 0
    """
    analyzer_instance = CppAnalyzer(str(temp_project_dir))
    yield analyzer_instance
    # Cleanup is handled by temp_project_dir fixture


@pytest.fixture
def indexed_analyzer(temp_project_dir):
    """
    Create a CppAnalyzer instance with pre-indexed sample code.

    Yields:
        CppAnalyzer: Analyzer instance with indexed sample project

    Example:
        def test_search(indexed_analyzer):
            results = indexed_analyzer.search_classes("TestClass")
            assert len(results) > 0
    """
    # Create sample files
    (temp_project_dir / "src" / "main.cpp").write_text("""
#include "utils.h"

int main() {
    return 0;
}
""")

    (temp_project_dir / "include" / "utils.h").write_text("""
#pragma once

class TestClass {
public:
    TestClass();
    void testMethod();
};

class AnotherClass {
public:
    AnotherClass();
};

void globalFunction();
""")

    # Create compile_commands.json
    temp_compile_commands(temp_project_dir, [
        {
            "file": "src/main.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17", "-I", "include"]
        }
    ])

    # Create and index analyzer
    analyzer_instance = CppAnalyzer(str(temp_project_dir))
    analyzer_instance.index_project()

    yield analyzer_instance


# ============================================================================
# Compile Commands Manager Fixtures
# ============================================================================

@pytest.fixture
def compile_commands_manager(temp_project_dir):
    """
    Create a CompileCommandsManager instance.

    Yields:
        CompileCommandsManager: Manager instance for temp project

    Example:
        def test_compile_commands(compile_commands_manager):
            compile_commands_manager.load()
            assert compile_commands_manager.has_compile_commands()
    """
    manager = CompileCommandsManager(str(temp_project_dir))
    yield manager


@pytest.fixture
def compile_commands_file(temp_project_dir):
    """
    Create a compile_commands.json file with sample entries.

    Yields:
        Path: Path to compile_commands.json file

    Example:
        def test_loading(compile_commands_file):
            assert compile_commands_file.exists()
            data = json.loads(compile_commands_file.read_text())
            assert len(data) == 2
    """
    compile_commands = [
        {
            "file": str(temp_project_dir / "src" / "main.cpp"),
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17", "-I", "include"],
            "command": "clang++ -std=c++17 -I include src/main.cpp"
        },
        {
            "file": str(temp_project_dir / "src" / "utils.cpp"),
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17", "-I", "include"],
            "command": "clang++ -std=c++17 -I include src/utils.cpp"
        }
    ]

    compile_commands_path = temp_compile_commands(temp_project_dir, compile_commands)
    yield compile_commands_path


# ============================================================================
# Configuration Fixtures
# ============================================================================

@pytest.fixture
def config_file(temp_project_dir):
    """
    Create a .cpp-analyzer-config.json file with default settings.

    Yields:
        Path: Path to config file

    Example:
        def test_config(config_file):
            config = json.loads(config_file.read_text())
            assert config["max_file_size_mb"] == 10
    """
    config = {
        "max_file_size_mb": 10,
        "excluded_patterns": ["*/build/*", "*/test/*"],
        "include_dependencies": False,
        "cache_enabled": True
    }

    config_path = temp_config_file(temp_project_dir, config)
    yield config_path


# ============================================================================
# Sample C++ Code Fixtures
# ============================================================================

@pytest.fixture
def simple_cpp_class():
    """
    Return source code for a simple C++ class.

    Returns:
        str: C++ class definition

    Example:
        def test_class_extraction(temp_dir, simple_cpp_class):
            (temp_dir / "test.h").write_text(simple_cpp_class)
    """
    return """
#pragma once

class SimpleClass {
public:
    SimpleClass();
    ~SimpleClass();

    void method();
    int getValue() const;

private:
    int value_;
};
"""


@pytest.fixture
def cpp_with_inheritance():
    """
    Return source code with class inheritance.

    Returns:
        str: C++ code with base and derived classes
    """
    return """
#pragma once

class Base {
public:
    virtual ~Base() {}
    virtual void virtualMethod() = 0;
};

class Derived : public Base {
public:
    void virtualMethod() override;
    void derivedMethod();
};

class MultiDerived : public Base, public Derived {
public:
    void virtualMethod() override;
};
"""


@pytest.fixture
def cpp_with_templates():
    """
    Return source code with template classes and functions.

    Returns:
        str: C++ code with templates
    """
    return """
#pragma once

template<typename T>
class Container {
public:
    void add(const T& item);
    T get(int index) const;

private:
    T* data_;
};

template<typename T>
T max(const T& a, const T& b) {
    return (a > b) ? a : b;
}
"""


# ============================================================================
# Pytest Hooks and Configuration
# ============================================================================

def pytest_configure(config):
    """
    Pytest configuration hook.

    Registers custom markers.
    """
    config.addinivalue_line(
        "markers", "base_functionality: Tests for core MCP server features"
    )
    config.addinivalue_line(
        "markers", "error_handling: Tests for error handling and recovery"
    )
    config.addinivalue_line(
        "markers", "security: Security-related tests (path traversal, injection, etc.)"
    )
    config.addinivalue_line(
        "markers", "robustness: Data integrity and atomic operations tests"
    )
    config.addinivalue_line(
        "markers", "edge_case: Boundary conditions and edge case tests"
    )
    config.addinivalue_line(
        "markers", "platform: Platform-specific tests (Windows, Unix, macOS)"
    )
    config.addinivalue_line(
        "markers", "slow: Tests that take significant time to run"
    )
    config.addinivalue_line(
        "markers", "critical: P0 critical tests that must pass"
    )


def pytest_collection_modifyitems(config, items):
    """
    Pytest hook to modify test collection.

    Automatically marks tests based on their file path.
    """
    for item in items:
        # Get the test file path
        test_file = str(item.fspath)

        # Auto-mark tests based on directory
        if "/security/" in test_file:
            item.add_marker(pytest.mark.security)
        elif "/robustness/" in test_file:
            item.add_marker(pytest.mark.robustness)
        elif "/error_handling/" in test_file:
            item.add_marker(pytest.mark.error_handling)
        elif "/edge_cases/" in test_file:
            item.add_marker(pytest.mark.edge_case)
        elif "/platform/" in test_file:
            item.add_marker(pytest.mark.platform)
        elif "/base_functionality/" in test_file:
            item.add_marker(pytest.mark.base_functionality)
