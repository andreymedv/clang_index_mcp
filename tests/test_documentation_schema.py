#!/usr/bin/env python3
"""
Unit tests for documentation schema and storage (Phase 2 - UT-4).

Tests SQLite schema updates, data storage, and retrieval of documentation fields.
"""

import os
import sys
import sqlite3
from pathlib import Path
import pytest

# Add the mcp_server directory to the path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server.sqlite_cache_backend import SqliteCacheBackend
from mcp_server.symbol_info import SymbolInfo
from tests.utils.test_helpers import temp_compile_commands


# ============================================================================
# UT-4: Schema and Storage Tests
# ============================================================================

class TestDocumentationSchema:
    """Tests for schema updates to support documentation (UT-4)."""

    def test_schema_has_brief_column(self, temp_project_dir):
        """UT-4.1: Verify brief column exists in symbols table."""
        # Create a simple project and index it
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// Test class
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

        # Access the cache database directly
        cache_backend = analyzer.cache_manager.backend
        db_path = cache_backend.db_path

        # Query schema
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(symbols)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        conn.close()

        # Verify brief column exists
        assert 'brief' in columns
        assert columns['brief'] == 'TEXT'

    def test_schema_has_doc_comment_column(self, temp_project_dir):
        """UT-4.2: Verify doc_comment column exists in symbols table."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
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

        cache_backend = analyzer.cache_manager.backend
        db_path = cache_backend.db_path

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(symbols)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        conn.close()

        # Verify doc_comment column exists
        assert 'doc_comment' in columns
        assert columns['doc_comment'] == 'TEXT'

    def test_store_and_retrieve_brief(self, temp_project_dir):
        """UT-4.3: Test storing and retrieving brief from database."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// This is the brief description
class DocumentedClass {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Retrieve from analyzer
        results = analyzer.search_classes("DocumentedClass")
        assert len(results) == 1
        stored_brief = results[0].get('brief')

        # Verify it was actually stored in DB
        cache_backend = analyzer.cache_manager.backend
        db_symbols = cache_backend.search_symbols_by_kind("class", project_only=False)

        documented_symbols = [s for s in db_symbols if s.name == "DocumentedClass"]
        assert len(documented_symbols) == 1
        assert documented_symbols[0].brief == stored_brief

    def test_store_and_retrieve_doc_comment(self, temp_project_dir):
        """UT-4.4: Test storing and retrieving doc_comment from database."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/**
 * @brief Brief description
 *
 * Full documentation with details.
 * Multiple paragraphs here.
 */
class FullyDocumentedClass {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        results = analyzer.search_classes("FullyDocumentedClass")
        assert len(results) == 1
        stored_doc = results[0].get('doc_comment')

        # Verify stored in DB
        cache_backend = analyzer.cache_manager.backend
        db_symbols = cache_backend.search_symbols_by_kind("class", project_only=False)

        documented_symbols = [s for s in db_symbols if s.name == "FullyDocumentedClass"]
        assert len(documented_symbols) == 1
        assert documented_symbols[0].doc_comment == stored_doc

    def test_null_documentation_storage(self, temp_project_dir):
        """UT-4.5: Test storing NULL values for missing documentation."""
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

        results = analyzer.search_classes("UndocumentedClass")
        assert len(results) == 1
        assert results[0].get('brief') is None
        assert results[0].get('doc_comment') is None

        # Verify NULL stored in DB (not empty string)
        cache_backend = analyzer.cache_manager.backend
        db_path = cache_backend.db_path

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT brief, doc_comment
            FROM symbols
            WHERE name = 'UndocumentedClass'
        """)
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] is None  # brief is NULL
        assert row[1] is None  # doc_comment is NULL

    def test_documentation_survives_cache_reload(self, temp_project_dir):
        """UT-4.6: Test that documentation persists across analyzer restarts."""
        (temp_project_dir / "src" / "test.cpp").write_text("""
/// Persistent documentation
class PersistentClass {
};
""")

        temp_compile_commands(temp_project_dir, [{
            "file": "src/test.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }])

        # First analyzer - index project
        analyzer1 = CppAnalyzer(str(temp_project_dir))
        analyzer1.index_project()
        results1 = analyzer1.search_classes("PersistentClass")
        assert len(results1) == 1
        original_brief = results1[0].get('brief')
        original_doc = results1[0].get('doc_comment')

        # Second analyzer - should use cached data
        analyzer2 = CppAnalyzer(str(temp_project_dir))
        # Index again - should load from cache since files unchanged
        analyzer2.index_project()
        results2 = analyzer2.search_classes("PersistentClass")
        assert len(results2) == 1
        assert results2[0].get('brief') == original_brief
        assert results2[0].get('doc_comment') == original_doc


class TestCacheBackendDocumentation:
    """Tests for SqliteCacheBackend documentation handling."""

    def test_save_symbol_with_documentation(self, temp_dir):
        """UT-4.7: Test SqliteCacheBackend.save_symbol() with documentation."""
        cache_dir = temp_dir / ".cache"
        cache_dir.mkdir()
        db_path = cache_dir / "symbols.db"

        backend = SqliteCacheBackend(db_path)

        # Create symbol with documentation
        symbol = SymbolInfo(
            name="TestClass",
            kind="class",
            file="/test/test.cpp",
            line=10,
            column=1,
            usr="c:@S@TestClass",
            brief="Brief description here",
            doc_comment="Full documentation\nwith multiple lines"
        )

        backend.save_symbol(symbol)

        # Retrieve and verify
        retrieved = backend.search_symbols_by_kind("class", project_only=False)
        test_symbols = [s for s in retrieved if s.name == "TestClass"]
        assert len(test_symbols) == 1
        assert test_symbols[0].brief == "Brief description here"
        assert test_symbols[0].doc_comment == "Full documentation\nwith multiple lines"

    def test_save_symbols_batch_with_documentation(self, temp_dir):
        """UT-4.8: Test batch save with documentation fields."""
        cache_dir = temp_dir / ".cache"
        cache_dir.mkdir()
        db_path = cache_dir / "symbols.db"

        backend = SqliteCacheBackend(db_path)

        symbols = [
            SymbolInfo(
                name=f"Class{i}",
                kind="class",
                file=f"/test/test{i}.cpp",
                line=10,
                column=1,
                usr=f"c:@S@Class{i}",
                brief=f"Brief for class {i}",
                doc_comment=f"Full docs for class {i}"
            )
            for i in range(5)
        ]

        backend.save_symbols_batch(symbols)

        # Verify all saved correctly
        retrieved = backend.search_symbols_by_kind("class", project_only=False)
        assert len(retrieved) >= 5

        for i in range(5):
            class_symbols = [s for s in retrieved if s.name == f"Class{i}"]
            assert len(class_symbols) == 1
            assert class_symbols[0].brief == f"Brief for class {i}"
            assert class_symbols[0].doc_comment == f"Full docs for class {i}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
