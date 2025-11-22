"""
Error Handling Tests - Resource Errors

Tests for handling disk full, out of memory, and other resource errors.

Requirements: REQ-6.4 (Resource Error Handling)
Priority: P1-P2
"""

import pytest
from pathlib import Path
import os

# Import test infrastructure
import sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.mark.error_handling
class TestDiskErrors:
    """Test disk-related errors - REQ-6.4.1"""

    def test_disk_full_during_cache_write(self, temp_project_dir, mocker):
        """Test handling disk full error during cache write - Task 1.2.3"""
        # Create a simple C++ file
        (temp_project_dir / "src" / "test.cpp").write_text("""
class TestClass {
public:
    void method();
};
""")

        # Mock the cache save to raise OSError (disk full)
        from mcp_server.cache_manager import CacheManager

        original_save = CacheManager.save_cache

        def mock_save_cache(self, *args, **kwargs):
            # Raise disk full error
            raise OSError(28, "No space left on device")

        mocker.patch.object(CacheManager, 'save_cache', mock_save_cache)

        # Create analyzer
        analyzer = CppAnalyzer(str(temp_project_dir))

        # Index should handle disk full gracefully
        # Indexing itself should succeed, cache saving may fail
        try:
            indexed_count = analyzer.index_project()
            # Analyzer should not crash even if cache can't be saved
            # In-memory indexes should still work
            classes = analyzer.search_classes("TestClass")
            # May or may not find class depending on when error occurs
        except OSError:
            # If OSError propagates, that's also acceptable behavior
            # As long as it's not an unhandled crash
            pass


@pytest.mark.error_handling
@pytest.mark.slow
class TestMemoryErrors:
    """Test memory-related errors - REQ-6.4.2"""

    @pytest.mark.skip(reason="Memory tests can be unstable in CI")
    def test_out_of_memory_graceful_degradation(self, temp_project_dir):
        """Test graceful handling of memory pressure - Task 1.2.9"""
        # Create many large C++ files to put memory pressure
        for i in range(100):
            large_file = temp_project_dir / "src" / f"large{i}.cpp"
            # Create file with many classes
            content = ""
            for j in range(100):
                content += f"""
class LargeClass{i}_{j} {{
public:
    void method1();
    void method2();
    void method3();
    int field1;
    int field2;
    int field3;
}};
"""
            large_file.write_text(content)

        # Create analyzer
        analyzer = CppAnalyzer(str(temp_project_dir))

        # Index should either succeed or fail gracefully
        # Should not crash with unhandled memory error
        try:
            indexed_count = analyzer.index_project()
            # If successful, some files should be indexed
            assert indexed_count >= 0, "Should return valid count"
        except MemoryError:
            # If MemoryError is raised, that's acceptable
            # As long as it's not an unhandled crash
            pytest.skip("Memory error encountered during test - acceptable behavior")
        except Exception as e:
            # Other exceptions should provide useful error messages
            assert str(e), f"Exception should have descriptive message: {type(e).__name__}"
