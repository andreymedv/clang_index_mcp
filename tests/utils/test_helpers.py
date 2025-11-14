#!/usr/bin/env python3
"""
Test helper functions for Clang Index MCP test suite.

This module provides utility functions for creating temporary test projects,
files, configurations, and setting up test analyzers.
"""

import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add the mcp_server directory to the path
import sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer


@contextmanager
def temp_project(name: str = "test_project", create_subdirs: bool = True):
    """
    Create a temporary project directory with optional subdirectories.

    Args:
        name: Name of the project (used for directory name)
        create_subdirs: If True, creates src/, include/, tests/ subdirectories

    Yields:
        Path: Path to the temporary project directory

    Example:
        with temp_project() as project_root:
            (project_root / "src" / "main.cpp").write_text("int main() { return 0; }")
            analyzer = CppAnalyzer(str(project_root))
    """
    temp_dir = tempfile.mkdtemp(prefix=f"{name}_")
    project_root = Path(temp_dir)

    try:
        if create_subdirs:
            (project_root / "src").mkdir()
            (project_root / "include").mkdir()
            (project_root / "tests").mkdir()

        yield project_root
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@contextmanager
def temp_file(content: str, suffix: str = ".cpp", dir: Optional[Path] = None):
    """
    Create a temporary file with given content.

    Args:
        content: Content to write to the file
        suffix: File extension (default: .cpp)
        dir: Directory to create file in (default: system temp dir)

    Yields:
        Path: Path to the temporary file

    Example:
        with temp_file("int foo() { return 42; }", ".cpp") as cpp_file:
            # Use cpp_file
            pass
    """
    fd, temp_path = tempfile.mkstemp(suffix=suffix, dir=str(dir) if dir else None)
    file_path = Path(temp_path)

    try:
        # Close the file descriptor and write content
        os.close(fd)
        file_path.write_text(content)
        yield file_path
    finally:
        if file_path.exists():
            file_path.unlink()


def temp_compile_commands(project_root: Path, files: List[Dict[str, Any]]) -> Path:
    """
    Create a compile_commands.json file in the project root.

    Args:
        project_root: Root directory of the project
        files: List of file compilation entries

    Returns:
        Path: Path to the created compile_commands.json

    Example:
        files = [
            {
                "file": "src/main.cpp",
                "directory": str(project_root),
                "arguments": ["-std=c++17", "-I", "include"]
            }
        ]
        compile_commands_path = temp_compile_commands(project_root, files)
    """
    compile_commands_path = project_root / "compile_commands.json"

    # Ensure all file paths and directories are absolute
    processed_files = []
    for file_entry in files:
        entry = file_entry.copy()

        # Make file path absolute if relative
        if not Path(entry["file"]).is_absolute():
            entry["file"] = str(project_root / entry["file"])

        # Ensure directory is set
        if "directory" not in entry:
            entry["directory"] = str(project_root)

        # Generate command string if not provided
        if "command" not in entry and "arguments" in entry:
            entry["command"] = " ".join(entry["arguments"]) + " " + entry["file"]

        processed_files.append(entry)

    compile_commands_path.write_text(json.dumps(processed_files, indent=2))
    return compile_commands_path


@contextmanager
def env_var(name: str, value: str):
    """
    Temporarily set an environment variable.

    Args:
        name: Environment variable name
        value: Environment variable value

    Yields:
        None

    Example:
        with env_var("CPP_ANALYZER_DIAGNOSTIC_LEVEL", "DEBUG"):
            # Code that uses the environment variable
            pass
    """
    old_value = os.environ.get(name)
    os.environ[name] = value

    try:
        yield
    finally:
        if old_value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old_value


def temp_config_file(project_root: Path, config: Dict[str, Any]) -> Path:
    """
    Create a .cpp-analyzer-config.json file in the project root.

    Args:
        project_root: Root directory of the project
        config: Configuration dictionary

    Returns:
        Path: Path to the created config file

    Example:
        config = {
            "max_file_size_mb": 10,
            "excluded_patterns": ["*/test/*", "*/build/*"],
            "include_dependencies": False
        }
        config_path = temp_config_file(project_root, config)
    """
    config_path = project_root / ".cpp-analyzer-config.json"
    config_path.write_text(json.dumps(config, indent=2))
    return config_path


def setup_test_analyzer(
    project_root: Optional[Path] = None,
    source_files: Optional[Dict[str, str]] = None,
    compile_commands: Optional[List[Dict[str, Any]]] = None,
    config: Optional[Dict[str, Any]] = None,
    index_immediately: bool = True
) -> CppAnalyzer:
    """
    Set up a complete test analyzer with project structure, files, and configuration.

    Args:
        project_root: Existing project root (if None, creates temporary project)
        source_files: Dictionary of {relative_path: content} for source files
        compile_commands: List of compilation entries for compile_commands.json
        config: Configuration dictionary for .cpp-analyzer-config.json
        index_immediately: If True, indexes the project immediately

    Returns:
        CppAnalyzer: Configured and optionally indexed analyzer instance

    Example:
        analyzer = setup_test_analyzer(
            source_files={
                "src/main.cpp": "int main() { return 0; }",
                "include/utils.h": "#pragma once\\nint foo();"
            },
            compile_commands=[
                {
                    "file": "src/main.cpp",
                    "arguments": ["-std=c++17", "-I", "include"]
                }
            ]
        )
    """
    # Use provided project root or create a temporary one
    if project_root is None:
        # This will not be cleaned up automatically - caller must manage
        temp_dir = tempfile.mkdtemp(prefix="test_analyzer_")
        project_root = Path(temp_dir)
        (project_root / "src").mkdir()
        (project_root / "include").mkdir()

    # Create source files
    if source_files:
        for relative_path, content in source_files.items():
            file_path = project_root / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)

    # Create compile_commands.json if provided
    if compile_commands:
        temp_compile_commands(project_root, compile_commands)

    # Create config file if provided
    if config:
        temp_config_file(project_root, config)

    # Create analyzer instance
    analyzer = CppAnalyzer(str(project_root))

    # Index project if requested
    if index_immediately and source_files:
        analyzer.index_project()

    return analyzer


def create_simple_cpp_file(
    filename: str,
    classes: Optional[List[str]] = None,
    functions: Optional[List[str]] = None,
    includes: Optional[List[str]] = None
) -> str:
    """
    Generate a simple C++ file with specified elements.

    Args:
        filename: Name of the file (used in header guard)
        classes: List of class names to include
        functions: List of function signatures to include
        includes: List of headers to include

    Returns:
        str: Generated C++ source code

    Example:
        content = create_simple_cpp_file(
            "utils.h",
            classes=["Utility", "Helper"],
            functions=["int compute(int x)", "void process()"],
            includes=["<string>", "<vector>"]
        )
    """
    lines = []

    # Header guard
    guard = filename.upper().replace(".", "_").replace("/", "_")
    if filename.endswith(".h") or filename.endswith(".hpp"):
        lines.append(f"#ifndef {guard}")
        lines.append(f"#define {guard}")
        lines.append("")

    # Includes
    if includes:
        for include in includes:
            lines.append(f"#include {include}")
        lines.append("")

    # Classes
    if classes:
        for class_name in classes:
            lines.append(f"class {class_name} {{")
            lines.append("public:")
            lines.append(f"    {class_name}();")
            lines.append(f"    ~{class_name}();")
            lines.append("};")
            lines.append("")

    # Functions
    if functions:
        for function_sig in functions:
            lines.append(f"{function_sig};")
        lines.append("")

    # Close header guard
    if filename.endswith(".h") or filename.endswith(".hpp"):
        lines.append(f"#endif // {guard}")

    return "\n".join(lines)


def cleanup_temp_analyzer(analyzer: CppAnalyzer):
    """
    Clean up a test analyzer and its temporary project directory.

    Args:
        analyzer: The analyzer instance to clean up

    Example:
        analyzer = setup_test_analyzer(...)
        try:
            # Run tests
            pass
        finally:
            cleanup_temp_analyzer(analyzer)
    """
    if hasattr(analyzer, 'project_root'):
        project_path = Path(analyzer.project_root)
        if project_path.exists() and 'tmp' in str(project_path):
            shutil.rmtree(project_path, ignore_errors=True)
