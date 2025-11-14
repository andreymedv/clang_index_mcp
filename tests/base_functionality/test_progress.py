"""
Base Functionality Tests - Progress Tracking

Tests for indexing progress tracking and reporting.

Requirements: REQ-1.8 (Progress Reporting)
Priority: P1
"""

import pytest
from pathlib import Path

# Import test infrastructure
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.mark.base_functionality
class TestProgressTracking:
    """Test progress tracking functionality - REQ-1.8"""

    def test_progress_tracking_basic(self, temp_project_dir):
        """Test indexing progress tracking through completion - Task 1.1.12"""
        # Create multiple C++ files to index
        for i in range(5):
            file_path = temp_project_dir / "src" / f"file{i}.cpp"
            file_path.write_text(f"""
class TestClass{i} {{
public:
    void method{i}();
}};

void function{i}() {{}}
""")

        # Create analyzer
        analyzer = CppAnalyzer(str(temp_project_dir))

        # Index project
        indexed_count = analyzer.index_project()

        # Verify all files were indexed
        assert indexed_count >= 5, f"Should have indexed at least 5 files, got {indexed_count}"

        # Verify statistics are tracked
        stats = analyzer.get_stats()
        assert 'class_count' in stats, "Stats should include class_count"
        assert 'function_count' in stats, "Stats should include function_count"
        assert 'file_count' in stats, "Stats should include file_count"

        # Verify counts are reasonable
        assert stats['class_count'] >= 5, "Should have at least 5 classes"
        assert stats['function_count'] >= 5, "Should have at least 5 functions"
        assert stats['file_count'] >= 5, "Should have at least 5 files"

        # Verify last_index_time is tracked
        assert analyzer.last_index_time > 0, "Should track indexing time"

        # Verify indexed_file_count matches
        assert analyzer.indexed_file_count >= 5, "Should track indexed file count"

    def test_progress_with_cache(self, temp_project_dir):
        """Test progress tracking with cache hits"""
        # Create C++ files
        (temp_project_dir / "src" / "cached.cpp").write_text("""
class CachedClass {
public:
    void method();
};
""")

        # First indexing - no cache
        analyzer1 = CppAnalyzer(str(temp_project_dir))
        count1 = analyzer1.index_project()

        assert count1 > 0, "Should index files"

        # Second indexing - should use cache
        analyzer2 = CppAnalyzer(str(temp_project_dir))
        count2 = analyzer2.index_project()

        assert count2 > 0, "Should load from cache"

        # Stats should be consistent
        stats1 = analyzer1.get_stats()
        stats2 = analyzer2.get_stats()

        assert stats1['class_count'] == stats2['class_count'], "Class count should be same"
        assert stats1['function_count'] == stats2['function_count'], "Function count should be same"
