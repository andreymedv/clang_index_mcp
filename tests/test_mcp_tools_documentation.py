#!/usr/bin/env python3
"""
Integration tests for MCP tools with documentation (Phase 2).

Tests that search_classes, search_functions, and get_class_info
return documentation fields in their JSON responses.
"""

import os
import sys
import json
from pathlib import Path
import pytest

# Add the mcp_server directory to the path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer
from tests.utils.test_helpers import temp_compile_commands


class TestSearchClassesWithDocumentation:
    """Tests for search_classes() with documentation fields."""

    def test_search_classes_returns_brief(self, temp_project_dir):
        """Test that search_classes() includes brief field."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// Main application class
class Application {
};

/// Configuration manager
class ConfigManager {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search for classes - search for Application specifically
        results = analyzer.search_classes("Application")

        # Should find Application class
        app_class = results
        assert len(app_class) == 1
        assert 'brief' in app_class[0]
        if app_class[0]['brief']:
            assert "application" in app_class[0]['brief'].lower()

    def test_search_classes_returns_doc_comment(self, temp_project_dir):
        """Test that search_classes() includes doc_comment field."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/**
 * @brief Database connection pool
 *
 * Manages a pool of database connections for efficient
 * resource usage and connection reuse.
 */
class ConnectionPool {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results = analyzer.search_classes("ConnectionPool")
        assert len(results) == 1
        assert 'doc_comment' in results[0]
        if results[0]['doc_comment']:
            assert "connection" in results[0]['doc_comment'].lower()

    def test_search_classes_json_serialization(self, temp_project_dir):
        """Test that documentation fields serialize to JSON properly."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// Test class with documentation
class TestClass {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results_json = analyzer.search_classes("TestClass")

        # results_json should be a list of dicts
        assert isinstance(results_json, list)
        assert len(results_json) == 1

        result_dict = results_json[0]
        # Should have brief and doc_comment keys
        assert 'brief' in result_dict
        assert 'doc_comment' in result_dict


class TestSearchFunctionsWithDocumentation:
    """Tests for search_functions() with documentation fields."""

    def test_search_functions_returns_brief(self, temp_project_dir):
        """Test that search_functions() includes brief field."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// Initializes the application
void initialize();

/// Processes user input
void processInput();
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results = analyzer.search_functions("initialize")
        assert len(results) == 1
        assert 'brief' in results[0]

    def test_search_functions_returns_doc_comment(self, temp_project_dir):
        """Test that search_functions() includes doc_comment field."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/**
 * @brief Validates user credentials
 *
 * Checks username and password against database.
 *
 * @param username User's login name
 * @param password User's password
 * @return true if valid, false otherwise
 */
bool validateCredentials(const char* username, const char* password);
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results = analyzer.search_functions("validateCredentials")
        assert len(results) == 1
        assert 'doc_comment' in results[0]

    def test_search_functions_json_serialization(self, temp_project_dir):
        """Test that function documentation serializes to JSON."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// Test function
void testFunction();
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results_json = analyzer.search_functions("testFunction")

        assert isinstance(results_json, list)
        assert len(results_json) >= 1

        # Find our function
        func = [f for f in results_json if f['name'] == 'testFunction']
        assert len(func) == 1
        assert 'brief' in func[0]
        assert 'doc_comment' in func[0]


class TestGetClassInfoWithDocumentation:
    """Tests for get_class_info() with documentation fields."""

    def test_get_class_info_includes_class_docs(self, temp_project_dir):
        """Test that get_class_info() includes class documentation."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/**
 * @brief Main application controller
 *
 * Coordinates all application subsystems.
 */
class Controller {
public:
    void start();
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Get class info
        class_info = analyzer.get_class_info("Controller")
        assert class_info is not None

        # Class itself should have documentation
        assert 'brief' in class_info
        assert 'doc_comment' in class_info

    def test_get_class_info_includes_method_docs(self, temp_project_dir):
        """Test that get_class_info() includes method documentation."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
class Service {
public:
    /// Starts the service
    void start();

    /**
     * @brief Stops the service gracefully
     *
     * Waits for pending operations to complete.
     */
    void stop();
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        class_info = analyzer.get_class_info("Service")
        assert class_info is not None

        # Methods should have documentation
        assert 'methods' in class_info
        methods = class_info['methods']

        # Find start method
        start_methods = [m for m in methods if m['name'] == 'start']
        if start_methods:
            assert 'brief' in start_methods[0]
            assert 'doc_comment' in start_methods[0]

        # Find stop method
        stop_methods = [m for m in methods if m['name'] == 'stop']
        if stop_methods:
            assert 'brief' in stop_methods[0]
            assert 'doc_comment' in stop_methods[0]

    def test_get_class_info_json_format(self, temp_project_dir):
        """Test that get_class_info() JSON format includes all doc fields."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// Widget class
class Widget {
public:
    /// Constructor
    Widget();

    /// Show widget
    void show();
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        class_info = analyzer.get_class_info("Widget")
        assert class_info is not None

        # Verify JSON structure
        assert isinstance(class_info, dict)
        assert 'name' in class_info
        assert 'brief' in class_info
        assert 'doc_comment' in class_info
        assert 'methods' in class_info

        # Methods should also have doc fields
        for method in class_info.get('methods', []):
            assert 'brief' in method
            assert 'doc_comment' in method


class TestDocumentationWithNullValues:
    """Test handling of NULL documentation values."""

    def test_search_classes_with_null_docs(self, temp_project_dir):
        """Test that search_classes handles NULL documentation correctly."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
class UndocumentedClass {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results_json = analyzer.search_classes("UndocumentedClass")

        assert len(results_json) == 1
        result = results_json[0]

        # Should have null values, not missing keys
        assert 'brief' in result
        assert result['brief'] is None
        assert 'doc_comment' in result
        assert result['doc_comment'] is None

    def test_get_class_info_with_null_docs(self, temp_project_dir):
        """Test that get_class_info handles NULL documentation correctly."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
class NoDocsClass {
public:
    void undocumentedMethod();
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        class_info = analyzer.get_class_info("NoDocsClass")
        assert class_info is not None

        # Class should have null docs
        assert class_info['brief'] is None
        assert class_info['doc_comment'] is None

        # Methods should have null docs
        methods = class_info.get('methods', [])
        if methods:
            assert methods[0]['brief'] is None
            assert methods[0]['doc_comment'] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
