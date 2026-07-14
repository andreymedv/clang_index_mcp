"""Unit tests for IncrementalAnalyzer."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from clang_index_mcp._incremental.change_scanner import ChangeSet
from clang_index_mcp.cpp_analyzer_config import CompileCommandsConfig
from clang_index_mcp._incremental.incremental_analyzer import AnalysisResult, IncrementalAnalyzer


def _fake_process_file_worker(spec):
    """Fake worker that succeeds unless the file path contains 'fail'."""
    success = "fail" not in spec.file_path
    return (
        spec.file_path,
        success,
        False,
        [],
        [],
        {},
        "file-hash",
        "compile-args-hash",
        None,
        0,
    )


def _make_mock_ctx(test_dir):
    """Create a mock IncrementalContext with all required attributes."""
    ctx = Mock()
    ctx.project_root = test_dir
    ctx.config = Mock()
    ctx.config.get_compile_commands_config.return_value = CompileCommandsConfig(
        compile_commands_path="compile_commands.json"
    )
    ctx.config_file = None
    ctx.cache_manager = Mock()
    ctx.cache_orchestrator = Mock()
    ctx.cache_orchestrator.invalidate_header = Mock()
    ctx.cache_orchestrator.clear_header_tracker = Mock()
    ctx.cache_orchestrator.mark_header_completed = Mock()
    ctx.cache_orchestrator.remove_deleted_file = Mock()
    ctx.cache_orchestrator.compile_commands_hash = ""
    ctx.compilation_env = Mock()
    ctx.compilation_env.file_scanner = Mock()
    ctx.compilation_env.compile_commands_manager = Mock()
    ctx.compilation_env.compile_commands_manager.compute_commands_diff = Mock(
        return_value=(set(), set(), set())
    )
    ctx.compilation_env.compile_commands_manager.store_command_hashes = Mock(return_value=0)
    ctx.compilation_env.compile_commands_manager.get_compile_commands_hash = Mock(
        return_value=""
    )
    ctx.symbol_store = Mock()
    ctx.concurrency = Mock()
    ctx.call_graph_analyzer = Mock()
    ctx.dependency_graph = Mock()

    # Mock cache backend
    backend_mock = Mock()
    backend_mock.set_compile_args_hash = Mock(return_value=True)
    backend_mock.remove_file_cache = Mock()
    ctx.cache_manager.backend = backend_mock

    return ctx


class TestAnalysisResult(unittest.TestCase):
    """Test cases for AnalysisResult class."""

    def test_no_changes_result(self):
        """Test no_changes factory method."""
        result = AnalysisResult.no_changes()

        self.assertEqual(result.files_analyzed, 0)
        self.assertEqual(result.files_removed, 0)
        self.assertEqual(result.elapsed_seconds, 0.0)
        self.assertIsNotNone(result.changes)
        self.assertTrue(result.changes.is_empty())

    def test_result_string_representation(self):
        """Test string representation."""
        result = AnalysisResult(
            files_analyzed=5, files_removed=2, elapsed_seconds=1.234, changes=ChangeSet()
        )

        str_repr = str(result)
        self.assertIn("5 files", str_repr)
        self.assertIn("2 files", str_repr)
        self.assertIn("1.23", str_repr)


class TestIncrementalAnalyzer(unittest.TestCase):
    """Test cases for IncrementalAnalyzer class."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = Path(tempfile.mkdtemp())

        # Create mock context
        self.ctx = _make_mock_ctx(self.test_dir)

        # Create incremental analyzer
        self.incremental = IncrementalAnalyzer(self.ctx)

        # Patch process pool to use threads and worker to avoid pickling Mock objects.
        # This is a unit-testing seam: production always uses real ProcessPoolExecutor,
        # but Mock contexts cannot be pickled across processes.
        self._pool_patch = patch(
            "clang_index_mcp._incremental.worker_orchestrator.ProcessPoolExecutor",
            side_effect=lambda max_workers=None, mp_context=None, initializer=None: __import__(
                "concurrent.futures", fromlist=["ThreadPoolExecutor"]
            ).ThreadPoolExecutor(max_workers=max_workers or 2),
        )
        self._worker_patch = patch(
            "clang_index_mcp._indexing.worker_pool._process_file_worker",
            side_effect=_fake_process_file_worker,
        )
        self._pool_patch.start()
        self._worker_patch.start()

    def tearDown(self):
        """Clean up test fixtures."""
        self._worker_patch.stop()
        self._pool_patch.stop()
        shutil.rmtree(self.test_dir)

    def test_no_changes_detected(self):
        """Test analysis when no changes detected."""
        # Mock scanner to return empty changeset
        with patch.object(self.incremental.scanner, "scan_for_changes") as mock_scan:
            mock_scan.return_value = ChangeSet()

            result = self.incremental.perform_incremental_analysis()

            self.assertEqual(result.files_analyzed, 0)
            self.assertEqual(result.files_removed, 0)
            self.assertTrue(result.changes.is_empty())

    def test_single_source_file_modified(self):
        """Test analysis when single source file modified."""
        # Create changeset with one modified file
        changeset = ChangeSet()
        modified_file = str(self.test_dir / "main.cpp")
        changeset.modified_files = {modified_file}

        with patch.object(self.incremental.scanner, "scan_for_changes") as mock_scan:
            mock_scan.return_value = changeset

            result = self.incremental.perform_incremental_analysis()

            # Should re-analyze the modified file
            self.assertEqual(result.files_analyzed, 1)
            self.assertEqual(result.files_removed, 0)

    def test_header_change_cascade(self):
        """Test header change cascades to dependents."""
        # Create changeset with modified header
        changeset = ChangeSet()
        header_file = str(self.test_dir / "utils.h")
        changeset.modified_headers = {header_file}

        # Mock dependency graph to return dependents
        dependent1 = str(self.test_dir / "main.cpp")
        dependent2 = str(self.test_dir / "test.cpp")
        self.ctx.dependency_graph.find_transitive_dependents.return_value = {
            dependent1,
            dependent2,
        }

        with patch.object(self.incremental.scanner, "scan_for_changes") as mock_scan:
            mock_scan.return_value = changeset

            result = self.incremental.perform_incremental_analysis()

            # Should re-analyze both dependents
            self.assertEqual(result.files_analyzed, 2)
            self.ctx.dependency_graph.find_transitive_dependents.assert_called_once_with(
                header_file
            )

            # Verify both files ended up in the analysis set
            self.assertEqual(
                set(result.changes.modified_files) | set(result.changes.modified_headers),
                {header_file},
            )

    def test_new_file_added(self):
        """Test analysis when new file added."""
        # Create changeset with added file
        changeset = ChangeSet()
        new_file = str(self.test_dir / "new.cpp")
        changeset.added_files = {new_file}

        with patch.object(self.incremental.scanner, "scan_for_changes") as mock_scan:
            mock_scan.return_value = changeset

            result = self.incremental.perform_incremental_analysis()

            # Should analyze the new file
            self.assertEqual(result.files_analyzed, 1)

    def test_file_removed(self):
        """Test analysis when file removed."""
        # Create changeset with removed file
        changeset = ChangeSet()
        removed_file = str(self.test_dir / "deleted.cpp")
        changeset.removed_files = {removed_file}

        with patch.object(self.incremental.scanner, "scan_for_changes") as mock_scan:
            mock_scan.return_value = changeset

            result = self.incremental.perform_incremental_analysis()

            # Should remove file from cache and dependencies
            self.assertEqual(result.files_removed, 1)
            self.ctx.cache_orchestrator.remove_deleted_file.assert_called_once_with(
                removed_file
            )

    def test_compile_commands_changed(self):
        """Test analysis when compile_commands.json changed."""
        # Create changeset with compile_commands change
        changeset = ChangeSet()
        changeset.compile_commands_changed = True

        # Mock compile commands manager
        file1 = str(self.test_dir / "main.cpp")
        file2 = str(self.test_dir / "utils.cpp")
        file3 = str(self.test_dir / "new.cpp")

        old_commands = {file1: ["-std=c++17", "-O2"], file2: ["-std=c++17"]}

        new_commands = {
            file1: ["-std=c++20", "-O3"],  # Changed
            file3: ["-std=c++17"],  # Added (file2 removed)
        }

        # Setup the file_to_command_map with a custom mock that tracks copy calls
        mock_command_map = Mock()
        mock_command_map.copy.return_value = old_commands
        mock_command_map.keys.return_value = new_commands.keys()
        mock_command_map.__iter__ = lambda x: iter(new_commands)
        mock_command_map.__getitem__ = lambda x, key: new_commands[key]

        self.ctx.compilation_env.compile_commands_manager.file_to_command_map = mock_command_map
        self.ctx.compilation_env.compile_commands_manager.load_compile_commands = Mock()
        self.ctx.compilation_env.compile_commands_manager.compute_commands_diff = Mock(
            return_value=({file3}, {file2}, {file1})
        )
        self.ctx.compilation_env.compile_commands_manager.store_command_hashes = Mock()
        self.ctx.compilation_env.compile_commands_manager.get_compile_commands_hash = Mock(
            return_value=""
        )

        with patch.object(self.incremental.scanner, "scan_for_changes") as mock_scan:
            mock_scan.return_value = changeset

            result = self.incremental.perform_incremental_analysis()

        # Should re-analyze file1 (changed) and file3 (added)
        # Note: file2 is removed, not re-analyzed
        self.assertEqual(result.files_analyzed, 2)

    def test_multiple_changes_combined(self):
        """Test analysis with multiple types of changes."""
        # Create changeset with multiple changes
        changeset = ChangeSet()

        new_file = str(self.test_dir / "new.cpp")
        modified_file = str(self.test_dir / "main.cpp")
        modified_header = str(self.test_dir / "utils.h")
        removed_file = str(self.test_dir / "old.cpp")

        changeset.added_files = {new_file}
        changeset.modified_files = {modified_file}
        changeset.modified_headers = {modified_header}
        changeset.removed_files = {removed_file}

        # Mock dependency graph
        dependent1 = str(self.test_dir / "test1.cpp")
        dependent2 = str(self.test_dir / "test2.cpp")
        self.ctx.dependency_graph.find_transitive_dependents.return_value = {
            dependent1,
            dependent2,
        }

        with patch.object(self.incremental.scanner, "scan_for_changes") as mock_scan:
            mock_scan.return_value = changeset

            result = self.incremental.perform_incremental_analysis()

            # Should analyze:
            # - new_file (added)
            # - modified_file (modified)
            # - dependent1, dependent2 (header cascade)
            # Total = 4 files (may have overlap)
            self.assertGreaterEqual(result.files_analyzed, 4)
            self.assertEqual(result.files_removed, 1)

    def test_handle_header_change_without_dependency_graph(self):
        """Test header change handling when no dependency graph available."""
        # Disable dependency graph
        self.ctx.dependency_graph = None

        changeset = ChangeSet()
        header_file = str(self.test_dir / "utils.h")
        changeset.modified_headers = {header_file}

        with patch.object(self.incremental.scanner, "scan_for_changes") as mock_scan:
            mock_scan.return_value = changeset

            result = self.incremental.perform_incremental_analysis()

            # Should not crash, but won't find dependents
            self.assertEqual(result.files_analyzed, 0)

    def test_reanalyze_files_handles_failures(self):
        """Test _reanalyze_files handles individual file failures gracefully."""
        import time

        files = {
            str(self.test_dir / "success.cpp"),
            str(self.test_dir / "fail.cpp"),
            str(self.test_dir / "success2.cpp"),
        }

        start_time = time.time()
        analyzed = self.incremental._reanalyze_files(files, start_time)

        # Should analyze 2 out of 3
        self.assertEqual(analyzed, 2)

    def test_remove_file_handles_exceptions(self):
        """Test _remove_file handles exceptions gracefully."""
        # Mock orchestrator cleanup to raise exception
        self.ctx.cache_orchestrator.remove_deleted_file.side_effect = Exception(
            "Test error"
        )

        removed_file = str(self.test_dir / "deleted.cpp")

        # Should not crash
        self.incremental._remove_file(removed_file)

        # Verify the orchestrator was invoked
        self.ctx.cache_orchestrator.remove_deleted_file.assert_called_once_with(
            removed_file
        )

    def test_header_tracker_invalidation(self):
        """Test header tracker is invalidated on changes."""
        changeset = ChangeSet()
        header_file = str(self.test_dir / "utils.h")
        changeset.modified_headers = {header_file}

        # Mock dependency graph to return empty set
        self.ctx.dependency_graph.find_transitive_dependents.return_value = set()

        with patch.object(self.incremental.scanner, "scan_for_changes") as mock_scan:
            mock_scan.return_value = changeset

            self.incremental.perform_incremental_analysis()

            # Verify header tracker was invalidated
            self.ctx.cache_orchestrator.invalidate_header.assert_called_once_with(header_file)

    def test_compile_commands_hash_updated(self):
        """Test compile_commands_hash is updated after change."""
        changeset = ChangeSet()
        changeset.compile_commands_changed = True

        # Create compile_commands.json
        cc_file = self.test_dir / "compile_commands.json"
        cc_file.write_text("[]")

        # Mock empty commands
        self.ctx.compilation_env.compile_commands_manager.file_to_command_map = {}
        self.ctx.compilation_env.compile_commands_manager.compute_commands_diff = Mock(
            return_value=(set(), set(), set())
        )
        self.ctx.compilation_env.compile_commands_manager.store_command_hashes = Mock()
        self.ctx.compilation_env.compile_commands_manager.get_compile_commands_hash = Mock(
            return_value="new_hash"
        )

        with patch.object(self.incremental.scanner, "scan_for_changes") as mock_scan:
            mock_scan.return_value = changeset

            self.incremental.perform_incremental_analysis()

            # Verify hash was updated
            self.assertEqual(self.ctx.cache_orchestrator.compile_commands_hash, "new_hash")


if __name__ == "__main__":
    unittest.main()
