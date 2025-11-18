"""
Base Functionality Tests - Cache Persistence

Tests for cache creation, loading, and persistence.

Requirements: REQ-1.5 (Cache Management)
Priority: P1
"""

import pytest
from pathlib import Path
import time

# Import test infrastructure
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.mark.base_functionality
class TestCachePersistence:
    """Test cache persistence functionality - REQ-1.5"""

    def test_cache_persistence_basic(self, temp_project_dir):
        """Test that cache is created and loadable - Task 1.1.9"""
        # Create a simple C++ file
        (temp_project_dir / "src" / "cache_test.cpp").write_text("""
class CachedClass {
public:
    void method();
};

void cachedFunction() {}
""")

        # First indexing - should create cache
        analyzer1 = CppAnalyzer(str(temp_project_dir))
        count1 = analyzer1.index_project()

        # Verify indexing succeeded
        assert count1 > 0, "Should have indexed at least one file"

        # Verify cache directory exists (use actual cache location from analyzer)
        cache_dir = Path(analyzer1.cache_dir)
        assert cache_dir.exists(), "Cache directory should be created"

        # Verify SQLite database exists
        db_file = cache_dir / "symbols.db"
        assert db_file.exists(), "SQLite database should be created"

        # Check that symbols were indexed
        classes1 = analyzer1.search_classes("CachedClass")
        funcs1 = analyzer1.search_functions("cachedFunction")
        assert len(classes1) > 0, "Should find CachedClass"
        assert len(funcs1) > 0, "Should find cachedFunction"

        # Create new analyzer instance - should load from cache
        analyzer2 = CppAnalyzer(str(temp_project_dir))
        count2 = analyzer2.index_project()

        # Verify cache was loaded
        assert count2 > 0, "Should have loaded from cache"

        # Verify cached symbols are available
        classes2 = analyzer2.search_classes("CachedClass")
        funcs2 = analyzer2.search_functions("cachedFunction")
        assert len(classes2) > 0, "Should find CachedClass from cache"
        assert len(funcs2) > 0, "Should find cachedFunction from cache"

        # Verify results are the same
        assert classes1[0]['name'] == classes2[0]['name']
        assert funcs1[0]['name'] == funcs2[0]['name']

    def test_cache_invalidation_on_file_change(self, temp_project_dir):
        """Test that cache is invalidated when files change"""
        test_file = temp_project_dir / "src" / "changing.cpp"

        # Create initial file
        test_file.write_text("""
class OriginalClass {
public:
    void method();
};
""")

        # First indexing
        analyzer1 = CppAnalyzer(str(temp_project_dir))
        analyzer1.index_project()

        # Verify original class is found
        original = analyzer1.search_classes("OriginalClass")
        assert len(original) > 0, "Should find OriginalClass"

        # Wait a moment to ensure timestamp difference
        time.sleep(0.1)

        # Modify the file
        test_file.write_text("""
class ModifiedClass {
public:
    void newMethod();
};
""")

        # Create new analyzer - should detect file change
        analyzer2 = CppAnalyzer(str(temp_project_dir))
        analyzer2.index_project()

        # Verify modified class is found and original is not
        modified = analyzer2.search_classes("ModifiedClass")
        original2 = analyzer2.search_classes("OriginalClass")

        assert len(modified) > 0, "Should find ModifiedClass"
        assert len(original2) == 0, "Should not find OriginalClass anymore"
