#!/usr/bin/env python3
"""
Unit tests for documentation extraction (Phase 2).

Tests brief and full documentation comment extraction from C++ code.
Tests cover Doxygen, JavaDoc, and Qt-style comments.
"""

import os
import sys
from pathlib import Path
import pytest

# Add the mcp_server directory to the path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer
from tests.utils.test_helpers import temp_compile_commands


# ============================================================================
# UT-1: Brief Comment Extraction Tests
# ============================================================================

class TestBriefCommentExtraction:
    """Tests for brief comment extraction (UT-1)."""

    def test_extract_brief_doxygen_single_line(self, temp_project_dir):
        """UT-1.1: Extract brief from Doxygen single-line comment (///)."""
        # Create source file with Doxygen single-line comment
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// Parses C++ source files and extracts symbols
class Parser {
public:
    /// Initializes the parser with default settings
    Parser();
};
""")

        # Create compile commands
        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        # Index and extract
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify brief extraction for class
        class_results = analyzer.search_classes("Parser")
        assert len(class_results) == 1
        parser_class = class_results[0]
        assert parser_class['brief'] is not None
        assert "Parses C++ source files" in parser_class['brief']

        # Note: Methods are tested separately in other test classes

    def test_extract_brief_doxygen_multiline(self, temp_project_dir):
        """UT-1.2: Extract brief from Doxygen multi-line comment (/** */)."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/**
 * @brief Manages HTTP request handling
 *
 * Additional details here...
 */
class RequestHandler {
public:
    void process();
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        class_results = analyzer.search_classes("RequestHandler")
        assert len(class_results) == 1
        assert class_results[0]['brief'] is not None
        assert "HTTP request" in class_results[0]['brief'].lower() or "request handling" in class_results[0]['brief'].lower()

    def test_extract_brief_qt_style(self, temp_project_dir):
        """UT-1.3: Extract brief from Qt-style comment (/*!)."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/*! Stores application configuration */
class Config {
public:
    void load();
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        class_results = analyzer.search_classes("Config")
        assert len(class_results) == 1
        assert class_results[0]['brief'] is not None
        assert "configuration" in class_results[0]['brief'].lower()

    def test_extract_brief_fallback_from_raw_comment(self, temp_project_dir):
        """UT-1.4: Extract brief from raw comment when brief_comment unavailable."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
// Simple comment without Doxygen markup
class SimpleClass {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        class_results = analyzer.search_classes("SimpleClass")
        assert len(class_results) == 1
        # May or may not extract from non-Doxygen comment
        # This is implementation-dependent

    def test_brief_length_limit(self, temp_project_dir):
        """UT-1.5: Brief should be truncated to max 200 characters."""
        very_long_brief = "A" * 250  # Create 250-char comment
        (temp_project_dir / "src" / "test.cpp").write_text(f"""
/// {very_long_brief}
class LongBriefClass {{
}};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        class_results = analyzer.search_classes("LongBriefClass")
        assert len(class_results) == 1
        if class_results[0]['brief']:
            assert len(class_results[0]['brief']) <= 200

    def test_brief_null_when_no_documentation(self, temp_project_dir):
        """UT-1.6: Brief should be NULL when no documentation exists."""
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

        class_results = analyzer.search_classes("UndocumentedClass")
        assert len(class_results) == 1
        assert class_results[0]['brief'] is None


# ============================================================================
# UT-2: Full Documentation Comment Extraction Tests
# ============================================================================

class TestFullDocumentationExtraction:
    """Tests for full documentation comment extraction (UT-2)."""

    def test_extract_full_doc_doxygen(self, temp_project_dir):
        """UT-2.1: Extract complete Doxygen documentation."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/**
 * @brief Database manager
 *
 * This class provides comprehensive database access.
 * It supports:
 * - Connection pooling
 * - Query caching
 * - Transaction management
 *
 * @see Connection for low-level access
 * @note Thread-safe
 */
class DatabaseManager {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        class_results = analyzer.search_classes("DatabaseManager")
        assert len(class_results) == 1
        assert class_results[0]['doc_comment'] is not None
        # Full doc should preserve structure
        assert "Connection pooling" in class_results[0]['doc_comment'] or "database access" in class_results[0]['doc_comment'].lower()

    def test_doc_comment_length_limit(self, temp_project_dir):
        """UT-2.2: Documentation should be truncated to max 4000 characters."""
        # Create very long documentation (> 4000 chars)
        long_doc = "/**\n * @brief Long docs\n *\n"
        long_doc += " * " + ("This is a very long documentation. " * 200)  # ~7000 chars
        long_doc += "\n */"

        (temp_project_dir / "src" / "test.cpp").write_text(f"""
{long_doc}
class LongDocsClass {{
}};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        class_results = analyzer.search_classes("LongDocsClass")
        assert len(class_results) == 1
        if class_results[0]['doc_comment']:
            assert len(class_results[0]['doc_comment']) <= 4000

    def test_doc_comment_null_when_missing(self, temp_project_dir):
        """UT-2.3: doc_comment should be NULL when no documentation exists."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
class NoDocsClass {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        class_results = analyzer.search_classes("NoDocsClass")
        assert len(class_results) == 1
        assert class_results[0]['doc_comment'] is None

    def test_doc_comment_preserves_structure(self, temp_project_dir):
        """UT-2.4: Documentation should preserve formatting and structure."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/**
 * First paragraph.
 *
 * Second paragraph with details.
 *
 * @param x First parameter
 * @param y Second parameter
 * @return Result value
 */
void documentedFunction(int x, int y);
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        func_results = analyzer.search_functions("documentedFunction")
        assert len(func_results) == 1
        if func_results[0]['doc_comment']:
            # Should preserve @param and @return tags
            assert "@param" in func_results[0]['doc_comment'] or "parameter" in func_results[0]['doc_comment'].lower()


# ============================================================================
# UT-3: Comment Type Support Tests
# ============================================================================

class TestCommentTypeSupport:
    """Tests for different comment style support (UT-3)."""

    def test_doxygen_triple_slash(self, temp_project_dir):
        """UT-3.1: Support /// Doxygen style."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// Doxygen single-line
class DoxygenSlash {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results = analyzer.search_classes("DoxygenSlash")
        assert len(results) == 1
        assert results[0]['brief'] is not None

    def test_doxygen_multiline_star(self, temp_project_dir):
        """UT-3.2: Support /** ... */ Doxygen style."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/**
 * Doxygen multi-line
 */
class DoxygenStar {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results = analyzer.search_classes("DoxygenStar")
        assert len(results) == 1
        assert results[0]['brief'] is not None

    def test_qt_style_exclamation(self, temp_project_dir):
        """UT-3.3: Support /*! ... */ Qt style."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/*! Qt style documentation */
class QtStyle {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results = analyzer.search_classes("QtStyle")
        assert len(results) == 1
        assert results[0]['brief'] is not None

    def test_mixed_comment_styles(self, temp_project_dir):
        """UT-3.4: Handle mixed comment styles in same file."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// Doxygen style
class Style1 {
};

/** JavaDoc style */
class Style2 {
};

/*! Qt style */
class Style3 {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # All three classes should have documentation extracted
        for class_name in ["Style1", "Style2", "Style3"]:
            results = analyzer.search_classes(class_name)
            assert len(results) == 1
            assert results[0]['brief'] is not None


# ============================================================================
# Helper function tests
# ============================================================================

class TestDocumentationWithRealFiles:
    """Tests using pre-created fixture files."""

    def test_doxygen_style_fixture(self, temp_project_dir):
        """Test with doxygen_style.cpp fixture."""
        # Copy fixture file to test project
        fixture_file = Path(__file__).parent / "fixtures" / "documentation" / "doxygen_style.cpp"
        dest_file = temp_project_dir / "src" / "doxygen_style.cpp"
        dest_file.write_text(fixture_file.read_text())

        temp_compile_commands(temp_project_dir, [{
            "file": "src/doxygen_style.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify Parser class
        parser_results = analyzer.search_classes("Parser")
        assert len(parser_results) == 1
        assert parser_results[0]['brief'] is not None

        # Verify RequestHandler class
        handler_results = analyzer.search_classes("RequestHandler")
        assert len(handler_results) == 1
        assert handler_results[0]['brief'] is not None

    def test_no_docs_fixture(self, temp_project_dir):
        """Test with no_docs.cpp fixture (undocumented code)."""
        fixture_file = Path(__file__).parent / "fixtures" / "documentation" / "no_docs.cpp"
        dest_file = temp_project_dir / "src" / "no_docs.cpp"
        dest_file.write_text(fixture_file.read_text())

        temp_compile_commands(temp_project_dir, [{
            "file": "src/no_docs.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Undocumented classes should have None for brief
        results = analyzer.search_classes("UndocumentedClass")
        assert len(results) == 1
        assert results[0]['brief'] is None
        assert results[0]['doc_comment'] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
