"""Unit tests for IncrementalAnalyzer."""

import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call
from mcp_server.incremental_analyzer import IncrementalAnalyzer, AnalysisResult
from mcp_server.change_scanner import ChangeSet


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
            files_analyzed=5,
            files_removed=2,
            elapsed_seconds=1.234,
            changes=ChangeSet()
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

        # Create mock analyzer with all required components
        self.analyzer = Mock()
        self.analyzer.project_root = self.test_dir
        self.analyzer.config = Mock()
        self.analyzer.cache_manager = Mock()
        self.analyzer.file_scanner = Mock()
        self.analyzer.header_tracker = Mock()
        self.analyzer.dependency_graph = Mock()
        self.analyzer.compile_commands_manager = Mock()
        self.analyzer.compile_commands_hash = ""

        # Mock config
        self.analyzer.config.get_compile_commands_config.return_value = {
            'compile_commands_path': 'compile_commands.json'
        }

        # Mock cache backend
        backend_mock = Mock()
        backend_mock.conn = Mock()
        backend_mock.remove_file_cache = Mock()
        self.analyzer.cache_manager.backend = backend_mock

        # Mock index_file method
        self.analyzer.index_file = Mock(return_value=(True, False))

        # Create incremental analyzer
        self.incremental = IncrementalAnalyzer(self.analyzer)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir)

    def test_no_changes_detected(self):
        """Test analysis when no changes detected."""
        # Mock scanner to return empty changeset
        with patch.object(self.incremental.scanner, 'scan_for_changes') as mock_scan:
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

        with patch.object(self.incremental.scanner, 'scan_for_changes') as mock_scan:
            mock_scan.return_value = changeset

            result = self.incremental.perform_incremental_analysis()

            # Should re-analyze the modified file
            self.assertEqual(result.files_analyzed, 1)
            self.assertEqual(result.files_removed, 0)
            self.analyzer.index_file.assert_called_once_with(modified_file, force=True)

    def test_header_change_cascade(self):
        """Test header change cascades to dependents."""
        # Create changeset with modified header
        changeset = ChangeSet()
        header_file = str(self.test_dir / "utils.h")
        changeset.modified_headers = {header_file}

        # Mock dependency graph to return dependents
        dependent1 = str(self.test_dir / "main.cpp")
        dependent2 = str(self.test_dir / "test.cpp")
        self.analyzer.dependency_graph.find_transitive_dependents.return_value = {
            dependent1, dependent2
        }

        with patch.object(self.incremental.scanner, 'scan_for_changes') as mock_scan:
            mock_scan.return_value = changeset

            result = self.incremental.perform_incremental_analysis()

            # Should re-analyze both dependents
            self.assertEqual(result.files_analyzed, 2)
            self.analyzer.dependency_graph.find_transitive_dependents.assert_called_once_with(
                header_file
            )

            # Verify both files were re-indexed
            calls = self.analyzer.index_file.call_args_list
            self.assertEqual(len(calls), 2)
            analyzed_files = {call[0][0] for call in calls}
            self.assertEqual(analyzed_files, {dependent1, dependent2})

    def test_new_file_added(self):
        """Test analysis when new file added."""
        # Create changeset with added file
        changeset = ChangeSet()
        new_file = str(self.test_dir / "new.cpp")
        changeset.added_files = {new_file}

        with patch.object(self.incremental.scanner, 'scan_for_changes') as mock_scan:
            mock_scan.return_value = changeset

            result = self.incremental.perform_incremental_analysis()

            # Should analyze the new file
            self.assertEqual(result.files_analyzed, 1)
            self.analyzer.index_file.assert_called_once_with(new_file, force=True)

    def test_file_removed(self):
        """Test analysis when file removed."""
        # Create changeset with removed file
        changeset = ChangeSet()
        removed_file = str(self.test_dir / "deleted.cpp")
        changeset.removed_files = {removed_file}

        with patch.object(self.incremental.scanner, 'scan_for_changes') as mock_scan:
            mock_scan.return_value = changeset

            result = self.incremental.perform_incremental_analysis()

            # Should remove file from cache and dependencies
            self.assertEqual(result.files_removed, 1)
            self.analyzer.cache_manager.backend.remove_file_cache.assert_called_once_with(
                removed_file
            )
            self.analyzer.dependency_graph.remove_file_dependencies.assert_called_once_with(
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

        old_commands = {
            file1: ["-std=c++17", "-O2"],
            file2: ["-std=c++17"]
        }

        new_commands = {
            file1: ["-std=c++20", "-O3"],  # Changed
            file3: ["-std=c++17"]          # Added (file2 removed)
        }

        # Setup the file_to_command_map with a custom mock that tracks copy calls
        mock_command_map = Mock()
        mock_command_map.copy.return_value = old_commands
        mock_command_map.keys.return_value = new_commands.keys()
        mock_command_map.__iter__ = lambda x: iter(new_commands)
        mock_command_map.__getitem__ = lambda x, key: new_commands[key]

        self.analyzer.compile_commands_manager.file_to_command_map = mock_command_map
        self.analyzer.compile_commands_manager._load_compile_commands = Mock()

        # Mock the differ
        with patch('mcp_server.incremental_analyzer.CompileCommandsDiffer') as mock_differ_class:
            mock_differ = Mock()
            mock_differ_class.return_value = mock_differ

            # Differ returns: added={file3}, removed={file2}, changed={file1}
            mock_differ.compute_diff.return_value = ({file3}, {file2}, {file1})

            with patch.object(self.incremental.scanner, 'scan_for_changes') as mock_scan:
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
        self.analyzer.dependency_graph.find_transitive_dependents.return_value = {
            dependent1, dependent2
        }

        with patch.object(self.incremental.scanner, 'scan_for_changes') as mock_scan:
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
        self.analyzer.dependency_graph = None

        changeset = ChangeSet()
        header_file = str(self.test_dir / "utils.h")
        changeset.modified_headers = {header_file}

        with patch.object(self.incremental.scanner, 'scan_for_changes') as mock_scan:
            mock_scan.return_value = changeset

            result = self.incremental.perform_incremental_analysis()

            # Should not crash, but won't find dependents
            self.assertEqual(result.files_analyzed, 0)

    def test_reanalyze_files_handles_failures(self):
        """Test _reanalyze_files handles individual file failures gracefully."""
        import time

        # Mock index_file to fail for one file
        def index_side_effect(path, force=False):
            if "fail" in path:
                return (False, False)
            return (True, False)

        self.analyzer.index_file.side_effect = index_side_effect

        files = {
            str(self.test_dir / "success.cpp"),
            str(self.test_dir / "fail.cpp"),
            str(self.test_dir / "success2.cpp")
        }

        start_time = time.time()
        analyzed = self.incremental._reanalyze_files(files, start_time)

        # Should analyze 2 out of 3
        self.assertEqual(analyzed, 2)

    def test_remove_file_handles_exceptions(self):
        """Test _remove_file handles exceptions gracefully."""
        # Mock remove to raise exception
        self.analyzer.cache_manager.backend.remove_file_cache.side_effect = Exception("Test error")

        removed_file = str(self.test_dir / "deleted.cpp")

        # Should not crash
        self.incremental._remove_file(removed_file)

        # Verify it still tried dependency graph removal
        self.analyzer.dependency_graph.remove_file_dependencies.assert_called_once_with(
            removed_file
        )

    def test_header_tracker_invalidation(self):
        """Test header tracker is invalidated on changes."""
        changeset = ChangeSet()
        header_file = str(self.test_dir / "utils.h")
        changeset.modified_headers = {header_file}

        # Mock dependency graph to return empty set
        self.analyzer.dependency_graph.find_transitive_dependents.return_value = set()

        with patch.object(self.incremental.scanner, 'scan_for_changes') as mock_scan:
            mock_scan.return_value = changeset

            self.incremental.perform_incremental_analysis()

            # Verify header tracker was invalidated
            self.analyzer.header_tracker.invalidate_header.assert_called_once_with(
                header_file
            )

    def test_compile_commands_hash_updated(self):
        """Test compile_commands_hash is updated after change."""
        changeset = ChangeSet()
        changeset.compile_commands_changed = True

        # Create compile_commands.json
        cc_file = self.test_dir / "compile_commands.json"
        cc_file.write_text('[]')

        # Mock empty commands
        self.analyzer.compile_commands_manager.file_to_command_map = {}

        # Mock _get_file_hash
        self.analyzer._get_file_hash = Mock(return_value="new_hash")

        with patch('mcp_server.incremental_analyzer.CompileCommandsDiffer') as mock_differ_class:
            mock_differ = Mock()
            mock_differ_class.return_value = mock_differ
            mock_differ.compute_diff.return_value = (set(), set(), set())

            with patch.object(self.incremental.scanner, 'scan_for_changes') as mock_scan:
                mock_scan.return_value = changeset

                self.incremental.perform_incremental_analysis()

                # Verify hash was updated
                self.assertEqual(self.analyzer.compile_commands_hash, "new_hash")


if __name__ == '__main__':
    unittest.main()
