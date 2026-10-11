"""
Error Handling Tests - Resource Errors

Tests for handling disk full, out of memory, and other resource errors.

Requirements: REQ-6.4 (Resource Error Handling), REQ-6.7 (cache-write failure),
REQ-10.13.2/10.13.3 (progress tracking / ERROR state)
Priority: P1-P2
"""

import os

# Import test infrastructure
import sys

import pytest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from clang_index_mcp.cpp_analyzer import CppAnalyzer


def _write_sample_cpp(temp_project_dir):
    (temp_project_dir / "src" / "test.cpp").write_text("""
class TestClass {
public:
    void method();
};
""")


@pytest.mark.error_handling
class TestDiskErrors:
    """Test disk-related errors - REQ-6.4.1"""

    def test_disk_full_during_cache_write(self, temp_project_dir, mocker):
        """Cache write failure must not damage indexing (REQ-6.7.1).

        CacheManager.save_cache raises OSError(28). Indexing must still complete
        without propagating the OSError, report cache_persisted=false alongside a
        non-ERROR status, retry the save once, and serve queries from memory.
        """
        _write_sample_cpp(temp_project_dir)

        # Mock the cache save to raise OSError (disk full)
        from clang_index_mcp._persistence.cache_manager import CacheManager

        save_calls = []

        def mock_save_cache(self, *args, **kwargs):
            save_calls.append(1)
            raise OSError(28, "No space left on device")

        mocker.patch.object(CacheManager, "save_cache", mock_save_cache)

        # Create analyzer
        analyzer = CppAnalyzer(str(temp_project_dir))

        # Indexing completes despite the cache write failure (REQ-6.7.1).
        indexed_count = analyzer.index_project()
        assert indexed_count >= 1, "indexing should complete and report indexed files"

        # One deferred retry after the first failed attempt.
        assert len(save_calls) == 2, f"expected 2 save_cache attempts, got {len(save_calls)}"

        # Cache-only failure never flips status to ERROR (REQ-10.13.3).
        cache_orch = analyzer.cache_orchestrator
        assert cache_orch.cache_persisted is False

        progress = analyzer.cache_manager.load_progress()
        assert progress is not None
        assert progress["status"] == "complete", f"status must not be error: {progress['status']}"
        assert progress["cache_persisted"] is False

        # In-memory indexes should still work despite the cache write failure
        classes = analyzer.search_classes("TestClass")
        assert isinstance(classes, list), "search_classes should return a list even when cache write fails"
        assert any("TestClass" in str(c) for c in classes), "in-memory index should still find TestClass"

    def test_disk_full_deferred_retry_succeeds(self, temp_project_dir, mocker):
        """A single deferred retry can recover a transient first-attempt failure."""
        _write_sample_cpp(temp_project_dir)

        from clang_index_mcp._persistence.cache_manager import CacheManager

        original_save = CacheManager.save_cache
        attempts = {"n": 0}

        def flaky_save_cache(self, *args, **kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise OSError(28, "No space left on device")
            return original_save(self, *args, **kwargs)

        mocker.patch.object(CacheManager, "save_cache", flaky_save_cache)

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        assert attempts["n"] == 2, "first attempt fails, deferred retry succeeds"
        assert analyzer.cache_orchestrator.cache_persisted is True

        progress = analyzer.cache_manager.load_progress()
        assert progress is not None
        assert progress["status"] == "complete"
        assert progress["cache_persisted"] is True

    def test_successful_save_reports_cache_persisted(self, temp_project_dir):
        """Happy path: cache_persisted is true and status is complete."""
        _write_sample_cpp(temp_project_dir)

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project(force=True)

        assert analyzer.cache_orchestrator.cache_persisted is True
        progress = analyzer.cache_manager.load_progress()
        assert progress is not None
        assert progress["status"] == "complete"
        assert progress["cache_persisted"] is True

    @pytest.mark.asyncio
    async def test_check_system_status_includes_cache_persisted(self, temp_project_dir, mocker):
        """Status tool (get_indexing_status path) exposes cache_persisted additively."""
        import json as json_mod

        from clang_index_mcp._mcp import cpp_mcp_server
        from clang_index_mcp._mcp.context import ctx
        from clang_index_mcp._mcp.state_manager import AnalyzerState, AnalyzerStateManager
        from clang_index_mcp._persistence.cache_manager import CacheManager

        _write_sample_cpp(temp_project_dir)

        def mock_save_cache(self, *args, **kwargs):
            raise OSError(28, "No space left on device")

        mocker.patch.object(CacheManager, "save_cache", mock_save_cache)

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project(force=True)

        ctx.analyzer = analyzer
        ctx.state_manager = AnalyzerStateManager()
        ctx.state_manager.transition_to(AnalyzerState.INDEXED)

        result = await cpp_mcp_server._handle_tool_call("check_system_status", {})
        data = json_mod.loads(result[0].text)

        assert "cache_persisted" in data, "status must include cache_persisted (additive)"
        assert data["cache_persisted"] is False
        assert data["state"] == "indexed", "cache failure must not flip status to error"
        assert data["state"] != "error"


@pytest.mark.error_handling
class TestCacheMissFallback:
    """load_cache failure must fall back to full re-parse (REQ-6.3.3)."""

    def test_load_cache_failure_proceeds_to_full_reparse(self, temp_project_dir, mocker):
        _write_sample_cpp(temp_project_dir)

        from clang_index_mcp._persistence.cache_manager import CacheManager

        def mock_load_cache(self, *args, **kwargs):
            return None

        mocker.patch.object(CacheManager, "load_cache", mock_load_cache)

        analyzer = CppAnalyzer(str(temp_project_dir))
        # load_cache miss -> handle_cache_initial_index returns None -> full re-parse
        indexed_count = analyzer.index_project(force=False)
        assert indexed_count >= 1, "cache miss must fall back to full re-parse"

        classes = analyzer.search_classes("TestClass")
        assert any("TestClass" in str(c) for c in classes)

    def test_load_cache_exception_treated_as_miss(self, temp_project_dir, mocker):
        """CacheManager.load_cache raising is converted to a miss by the orchestrator."""
        _write_sample_cpp(temp_project_dir)

        from clang_index_mcp._persistence.cache_manager import CacheManager

        def mock_load_cache(self, *args, **kwargs):
            raise OSError("cache unreadable")

        mocker.patch.object(CacheManager, "load_cache", mock_load_cache)

        analyzer = CppAnalyzer(str(temp_project_dir))
        # CacheOrchestrator.load_cache never raises and reports a miss (False).
        assert analyzer.cache_orchestrator.load_cache() is False
        # Full re-parse path is intact.
        indexed_count = analyzer.index_project(force=False)
        assert indexed_count >= 1

        classes = analyzer.search_classes("TestClass")
        assert any("TestClass" in str(c) for c in classes)


@pytest.mark.error_handling
class TestProgressTracking:
    """Progress tracking failures remain log-only (REQ-10.13.2)."""

    def test_save_progress_failure_is_swallowed(self, temp_project_dir, capsys):
        _write_sample_cpp(temp_project_dir)
        analyzer = CppAnalyzer(str(temp_project_dir))

        # Force a write failure inside save_progress (e.g. unwritable cache dir)
        analyzer.cache_manager.cache_dir = temp_project_dir / "missing" / "nested" / "nope"
        # Must not raise
        analyzer.cache_manager.save_progress(1, 1, 0, 0, 0.1, 0, 0, "complete")

    def test_load_progress_failure_returns_none(self, temp_project_dir):
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.cache_manager.cache_dir = temp_project_dir / "does_not_exist"
        assert analyzer.cache_manager.load_progress() is None


@pytest.mark.error_handling
@pytest.mark.slow
class TestMemoryErrors:
    """Test memory-related errors - REQ-6.4.2"""

    @pytest.mark.timeout(120)
    def test_out_of_memory_graceful_degradation(self, temp_project_dir):
        """Verify that indexing many large files either completes or fails gracefully without crashing."""
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
            pytest.fail("MemoryError raised during indexing — consider reducing test data size")
        except Exception as e:
            # Other exceptions should provide useful error messages
            assert str(e), f"Exception should have descriptive message: {type(e).__name__}"
