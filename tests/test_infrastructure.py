#!/usr/bin/env python3
"""
Infrastructure smoke tests for test framework.

These tests validate that the test infrastructure (fixtures, helpers, etc.)
is working correctly before running actual feature tests.
"""

import json
import pytest
from pathlib import Path

# Test imports work
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer
from tests.utils.test_helpers import (
    temp_project,
    temp_file,
    temp_compile_commands,
    env_var,
    temp_config_file,
    create_simple_cpp_file
)


class TestInfrastructure:
    """Test the test infrastructure itself."""

    def test_temp_dir_fixture(self, temp_dir):
        """Test that temp_dir fixture works."""
        assert temp_dir.exists()
        assert temp_dir.is_dir()

        # Create a file in temp dir
        test_file = temp_dir / "test.txt"
        test_file.write_text("test content")
        assert test_file.exists()
        assert test_file.read_text() == "test content"

    def test_temp_project_dir_fixture(self, temp_project_dir):
        """Test that temp_project_dir fixture creates proper structure."""
        assert temp_project_dir.exists()
        assert (temp_project_dir / "src").exists()
        assert (temp_project_dir / "include").exists()
        assert (temp_project_dir / "tests").exists()

    def test_cache_dir_fixture(self, cache_dir):
        """Test that cache_dir fixture works."""
        assert cache_dir.exists()
        assert cache_dir.is_dir()
        assert cache_dir.name == ".cache"

    def test_analyzer_fixture(self, analyzer):
        """Test that analyzer fixture creates a CppAnalyzer instance."""
        assert isinstance(analyzer, CppAnalyzer)
        assert Path(analyzer.project_root).exists()

    def test_indexed_analyzer_fixture(self, indexed_analyzer):
        """Test that indexed_analyzer fixture provides a working analyzer."""
        assert isinstance(indexed_analyzer, CppAnalyzer)

        # Check that it has indexed content
        classes = indexed_analyzer.search_classes("TestClass")
        assert len(classes) > 0, "Indexed analyzer should have found TestClass"

        classes2 = indexed_analyzer.search_classes("AnotherClass")
        assert len(classes2) > 0, "Indexed analyzer should have found AnotherClass"

    def test_compile_commands_file_fixture(self, compile_commands_file):
        """Test that compile_commands_file fixture creates valid JSON."""
        assert compile_commands_file.exists()

        # Verify it's valid JSON
        content = json.loads(compile_commands_file.read_text())
        assert isinstance(content, list)
        assert len(content) == 2

        # Verify structure
        assert "file" in content[0]
        assert "directory" in content[0]
        assert "arguments" in content[0]

    def test_config_file_fixture(self, config_file):
        """Test that config_file fixture creates valid config."""
        assert config_file.exists()

        # Verify it's valid JSON
        config = json.loads(config_file.read_text())
        assert "max_file_size_mb" in config
        assert "excluded_patterns" in config
        assert "include_dependencies" in config

    def test_simple_cpp_class_fixture(self, simple_cpp_class):
        """Test that simple_cpp_class fixture returns valid C++ code."""
        assert isinstance(simple_cpp_class, str)
        assert "class SimpleClass" in simple_cpp_class
        assert "public:" in simple_cpp_class

    def test_cpp_with_inheritance_fixture(self, cpp_with_inheritance):
        """Test that cpp_with_inheritance fixture returns valid C++ code."""
        assert isinstance(cpp_with_inheritance, str)
        assert "class Base" in cpp_with_inheritance
        assert "class Derived" in cpp_with_inheritance
        assert "public Base" in cpp_with_inheritance

    def test_cpp_with_templates_fixture(self, cpp_with_templates):
        """Test that cpp_with_templates fixture returns valid C++ code."""
        assert isinstance(cpp_with_templates, str)
        assert "template<typename T>" in cpp_with_templates
        assert "class Container" in cpp_with_templates


class TestHelperFunctions:
    """Test the helper functions from test_helpers.py."""

    def test_temp_project_context_manager(self):
        """Test temp_project context manager."""
        with temp_project(name="smoke_test") as project_root:
            assert project_root.exists()
            assert (project_root / "src").exists()
            assert (project_root / "include").exists()
            assert (project_root / "tests").exists()

            # Write a file
            (project_root / "src" / "test.cpp").write_text("int main() { return 0; }")
            assert (project_root / "src" / "test.cpp").exists()

        # Verify cleanup happened
        assert not project_root.exists()

    def test_temp_file_context_manager(self, temp_dir):
        """Test temp_file context manager."""
        with temp_file("int foo() { return 42; }", ".cpp", temp_dir) as cpp_file:
            assert cpp_file.exists()
            assert cpp_file.suffix == ".cpp"
            assert "int foo()" in cpp_file.read_text()

        # Verify cleanup happened
        assert not cpp_file.exists()

    def test_temp_compile_commands(self, temp_project_dir):
        """Test temp_compile_commands helper."""
        files = [
            {
                "file": "src/main.cpp",
                "arguments": ["-std=c++17", "-I", "include"]
            }
        ]

        compile_commands_path = temp_compile_commands(temp_project_dir, files)

        assert compile_commands_path.exists()
        data = json.loads(compile_commands_path.read_text())
        assert len(data) == 1
        assert "src/main.cpp" in data[0]["file"]

    def test_env_var_context_manager(self):
        """Test env_var context manager."""
        test_var = "TEST_INFRASTRUCTURE_VAR"
        original_value = os.environ.get(test_var)

        with env_var(test_var, "test_value"):
            assert os.environ[test_var] == "test_value"

        # Verify restoration
        if original_value is None:
            assert test_var not in os.environ
        else:
            assert os.environ[test_var] == original_value

    def test_temp_config_file(self, temp_project_dir):
        """Test temp_config_file helper."""
        config = {
            "max_file_size_mb": 5,
            "cache_enabled": True
        }

        config_path = temp_config_file(temp_project_dir, config)

        assert config_path.exists()
        loaded_config = json.loads(config_path.read_text())
        assert loaded_config["max_file_size_mb"] == 5
        assert loaded_config["cache_enabled"] is True

    def test_create_simple_cpp_file(self):
        """Test create_simple_cpp_file helper."""
        content = create_simple_cpp_file(
            "test.h",
            classes=["ClassA", "ClassB"],
            functions=["void foo()", "int bar()"],
            includes=["<string>", "<vector>"]
        )

        assert "#include <string>" in content
        assert "#include <vector>" in content
        assert "class ClassA" in content
        assert "class ClassB" in content
        assert "void foo();" in content
        assert "int bar();" in content


class TestTestFixtures:
    """Test that C++ fixture files exist and are valid."""

    def test_simple_class_fixture_exists(self):
        """Test simple_class.h fixture exists."""
        fixture_path = Path(__file__).parent / "fixtures" / "classes" / "simple_class.h"
        assert fixture_path.exists()

        content = fixture_path.read_text()
        assert "class SimpleClass" in content

    def test_global_functions_fixture_exists(self):
        """Test global_functions.cpp fixture exists."""
        fixture_path = Path(__file__).parent / "fixtures" / "functions" / "global_functions.cpp"
        assert fixture_path.exists()

        content = fixture_path.read_text()
        assert "void globalFunction()" in content

    def test_inheritance_fixture_exists(self):
        """Test inheritance fixture exists."""
        fixture_path = Path(__file__).parent / "fixtures" / "inheritance" / "single_inheritance.h"
        assert fixture_path.exists()

        content = fixture_path.read_text()
        assert "class Base" in content
        assert "class Derived" in content

    def test_template_fixture_exists(self):
        """Test template fixture exists."""
        fixture_path = Path(__file__).parent / "fixtures" / "templates" / "class_template.h"
        assert fixture_path.exists()

        content = fixture_path.read_text()
        assert "template<typename T>" in content

    def test_call_graph_fixture_exists(self):
        """Test call graph fixture exists."""
        fixture_path = Path(__file__).parent / "fixtures" / "call_graph" / "simple_calls.cpp"
        assert fixture_path.exists()

        content = fixture_path.read_text()
        assert "functionA()" in content
        assert "functionB()" in content


def test_pytest_markers_registered():
    """Test that custom pytest markers are registered."""
    # This test verifies that conftest.py registered custom markers
    # The markers should be available through pytest's marker system
    pass  # pytest will validate markers during collection


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
