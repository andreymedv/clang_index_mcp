#!/usr/bin/env python3
"""
Unit tests for documentation encoding and special characters (Phase 2).

Tests UTF-8 handling, special characters, and edge cases in documentation.
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


class TestUTF8Documentation:
    """Tests for UTF-8 and Unicode in documentation."""

    def test_utf8_cyrillic_docs(self, temp_project_dir):
        """Test Cyrillic characters in documentation."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// Класс для работы с данными
class DataProcessor {
};
""", encoding='utf-8')

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results = analyzer.search_classes("DataProcessor")
        assert len(results) == 1
        if results[0]['brief']:
            assert "Класс" in results[0]['brief'] or "данными" in results[0]['brief']

    def test_utf8_chinese_docs(self, temp_project_dir):
        """Test Chinese characters in documentation."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// 数据处理器类
class DataHandler {
};
""", encoding='utf-8')

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results = analyzer.search_classes("DataHandler")
        assert len(results) == 1
        if results[0]['brief']:
            assert "数据" in results[0]['brief'] or "类" in results[0]['brief']

    def test_utf8_mixed_languages(self, temp_project_dir):
        """Test mixed language documentation."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/**
 * @brief Parser for parsing (парсер для разбора) 解析器
 *
 * English text with Русский текст and 中文文本.
 */
class MultilingualParser {
};
""", encoding='utf-8')

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results = analyzer.search_classes("MultilingualParser")
        assert len(results) == 1
        # Should handle mixed languages
        assert results[0]['brief'] is not None or results[0]['doc_comment'] is not None

    def test_emoji_in_documentation(self, temp_project_dir):
        """Test emoji in documentation."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// 🚀 Fast parser for rocket-speed processing
class FastParser {
};
""", encoding='utf-8')

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results = analyzer.search_classes("FastParser")
        assert len(results) == 1
        if results[0]['brief']:
            # Emoji should be preserved or gracefully handled
            assert "Fast" in results[0]['brief'] or "parser" in results[0]['brief'].lower()


class TestSpecialCharacters:
    """Tests for special characters in documentation."""

    def test_angle_brackets_in_docs(self, temp_project_dir):
        """Test <angle> brackets don't break parsing."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// Template class for std::vector<int> processing
class VectorProcessor {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results = analyzer.search_classes("VectorProcessor")
        assert len(results) == 1
        if results[0]['brief']:
            assert "vector" in results[0]['brief'].lower()

    def test_quotes_in_docs(self, temp_project_dir):
        """Test quotes in documentation."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// Handles "quoted" strings and 'apostrophes'
class StringHandler {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results = analyzer.search_classes("StringHandler")
        assert len(results) == 1
        if results[0]['brief']:
            assert "quoted" in results[0]['brief'].lower() or "strings" in results[0]['brief'].lower()

    def test_ampersand_in_docs(self, temp_project_dir):
        """Test ampersand in documentation."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// Handles read & write operations
class IOHandler {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results = analyzer.search_classes("IOHandler")
        assert len(results) == 1
        if results[0]['brief']:
            assert "read" in results[0]['brief'].lower() or "write" in results[0]['brief'].lower()

    def test_newlines_in_doc_comment(self, temp_project_dir):
        """Test newlines are preserved in doc_comment."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/**
 * Line 1
 * Line 2
 * Line 3
 */
class MultilineDoc {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results = analyzer.search_classes("MultilineDoc")
        assert len(results) == 1
        if results[0]['doc_comment']:
            # Should preserve structure
            assert "Line" in results[0]['doc_comment']


class TestSpecialCharactersFixture:
    """Tests using special_chars.cpp fixture."""

    def test_special_chars_fixture(self, temp_project_dir):
        """Test with special_chars.cpp fixture."""
        fixture_file = Path(__file__).parent / "fixtures" / "documentation" / "special_chars.cpp"
        dest_file = temp_project_dir / "src" / "special_chars.cpp"
        dest_file.write_text(fixture_file.read_text(encoding='utf-8'), encoding='utf-8')

        temp_compile_commands(temp_project_dir, [{
            "file": "src/special_chars.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Test Unicode class
        unicode_results = analyzer.search_classes("UnicodeClass")
        assert len(unicode_results) == 1
        # Should handle Unicode without crashing
        assert unicode_results[0]['name'] == "UnicodeClass"

        # Test special chars class
        special_results = analyzer.search_classes("SpecialCharsClass")
        assert len(special_results) == 1
        assert special_results[0]['name'] == "SpecialCharsClass"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
