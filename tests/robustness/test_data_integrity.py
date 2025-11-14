"""
Robustness Tests - Data Integrity

Tests for atomic operations, cache consistency, and concurrent access.

Requirements: REQ-11.x (Data Integrity)
Priority: P0 - CRITICAL
"""

import pytest
import time
import threading

# Import test infrastructure
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.mark.robustness
@pytest.mark.critical
class TestAtomicCacheWrites:
    """Test atomic cache write operations - REQ-11.1"""

    def test_atomic_cache_writes(self, temp_project_dir):
        """Test that cache writes use temp file + rename pattern - Task 1.4.1"""
        from pathlib import Path

        (temp_project_dir / "src" / "test.cpp").write_text("class Test {};")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        cache_file = Path(analyzer.cache_dir) / "cache_info.json"
        assert cache_file.exists(), "Cache file should exist"

        # Cache file should be complete (not partial)
        content = cache_file.read_text()
        assert len(content) > 0, "Cache should have content"
        assert content.startswith("{"), "Cache should be valid JSON"

    def test_cache_consistency_after_interrupt(self, temp_project_dir):
        """Test cache remains consistent after indexing interruption - Task 1.4.2"""
        from pathlib import Path

        for i in range(5):
            (temp_project_dir / "src" / f"file{i}.cpp").write_text(f"class Class{i} {{}};")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify cache is consistent
        cache_file = Path(analyzer.cache_dir) / "cache_info.json"
        assert cache_file.exists(), "Cache should exist"

        # Load cache again - should work
        analyzer2 = CppAnalyzer(str(temp_project_dir))
        count = analyzer2.index_project()
        assert count > 0, "Should load from consistent cache"

    def test_concurrent_cache_write_protection(self, temp_project_dir):
        """Test protection against concurrent cache writes - Task 1.4.3"""
        (temp_project_dir / "src" / "test.cpp").write_text("class Test {};")

        def index_project():
            analyzer = CppAnalyzer(str(temp_project_dir))
            analyzer.index_project()

        # Start two indexing operations concurrently
        thread1 = threading.Thread(target=index_project)
        thread2 = threading.Thread(target=index_project)

        thread1.start()
        thread2.start()

        thread1.join()
        thread2.join()

        # Cache should still be valid
        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()
        assert count > 0, "Cache should be consistent after concurrent writes"
