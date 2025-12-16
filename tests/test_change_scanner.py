"""Unit tests for ChangeScanner and ChangeSet."""

import os
import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, MagicMock
from mcp_server.change_scanner import ChangeScanner, ChangeSet, ChangeType


class TestChangeSet(unittest.TestCase):
    """Test cases for ChangeSet class."""

    def test_empty_changeset(self):
        """Test that new ChangeSet is empty."""
        changeset = ChangeSet()

        self.assertTrue(changeset.is_empty())
        self.assertEqual(changeset.get_total_changes(), 0)

    def test_changeset_with_added_files(self):
        """Test ChangeSet with added files."""
        changeset = ChangeSet()
        changeset.added_files = {"file1.cpp", "file2.cpp"}

        self.assertFalse(changeset.is_empty())
        self.assertEqual(changeset.get_total_changes(), 2)

    def test_changeset_with_multiple_changes(self):
        """Test ChangeSet with multiple types of changes."""
        changeset = ChangeSet()
        changeset.added_files = {"new.cpp"}
        changeset.modified_files = {"old.cpp", "other.cpp"}
        changeset.modified_headers = {"header.h"}
        changeset.removed_files = {"deleted.cpp"}
        changeset.compile_commands_changed = True

        self.assertFalse(changeset.is_empty())
        self.assertEqual(changeset.get_total_changes(), 5)

    def test_changeset_str_empty(self):
        """Test string representation of empty ChangeSet."""
        changeset = ChangeSet()
        self.assertEqual(str(changeset), "No changes")

    def test_changeset_str_with_changes(self):
        """Test string representation with changes."""
        changeset = ChangeSet()
        changeset.added_files = {"new.cpp"}
        changeset.modified_files = {"old.cpp"}

        str_repr = str(changeset)
        self.assertIn("1 added", str_repr)
        self.assertIn("1 modified", str_repr)


class TestChangeScanner(unittest.TestCase):
    """Test cases for ChangeScanner class."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = Path(tempfile.mkdtemp())

        # Create mock analyzer
        self.analyzer = Mock()
        self.analyzer.project_root = self.test_dir
        self.analyzer.config = Mock()
        self.analyzer.cache_manager = Mock()
        self.analyzer.file_scanner = Mock()
        self.analyzer.header_tracker = Mock()
        self.analyzer.compile_commands_hash = ""
        self.analyzer.file_hashes = {}  # FIX: Add file_hashes for fallback checking

        # Mock config
        self.analyzer.config.get_compile_commands_config.return_value = {
            'compile_commands_path': 'compile_commands.json'
        }

        # Create scanner
        self.scanner = ChangeScanner(self.analyzer)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir)

    def test_scan_empty_project(self):
        """Test scanning a project with no files."""
        # Mock empty file list
        self.analyzer.file_scanner.find_cpp_files.return_value = []
        self.analyzer.header_tracker.get_processed_headers.return_value = {}
        self.analyzer.cache_manager.backend.get_file_metadata.return_value = None

        # Mock backend to return empty cached files
        backend_mock = Mock()
        backend_mock.conn = Mock()
        backend_mock.conn.execute.return_value.fetchall.return_value = []
        self.analyzer.cache_manager.backend = backend_mock

        changes = self.scanner.scan_for_changes()

        self.assertTrue(changes.is_empty())

    def test_detect_added_file(self):
        """Test detection of newly added file."""
        new_file = str(self.test_dir / "new.cpp")

        # Mock file scanner to return new file
        self.analyzer.file_scanner.find_cpp_files.return_value = [new_file]

        # Mock empty headers
        self.analyzer.header_tracker.get_processed_headers.return_value = {}

        # Create backend mock
        backend_mock = Mock()
        backend_mock.get_file_metadata = Mock(return_value=None)  # File not in cache
        backend_mock.conn = Mock()
        backend_mock.conn.execute.return_value.fetchall.return_value = []
        self.analyzer.cache_manager.backend = backend_mock

        changes = self.scanner.scan_for_changes()

        self.assertEqual(len(changes.added_files), 1)
        # Normalize path to handle symlinks (e.g., /var -> /private/var on macOS)
        self.assertIn(os.path.realpath(new_file), changes.added_files)

    def test_detect_modified_file(self):
        """Test detection of modified file."""
        modified_file = str(self.test_dir / "modified.cpp")

        # Mock file scanner
        self.analyzer.file_scanner.find_cpp_files.return_value = [modified_file]

        # Mock file hash to indicate change
        self.analyzer._get_file_hash.return_value = 'new_hash'

        # Mock empty headers
        self.analyzer.header_tracker.get_processed_headers.return_value = {}

        # Create backend mock with old hash
        backend_mock = Mock()
        backend_mock.get_file_metadata = Mock(return_value={'file_hash': 'old_hash'})
        backend_mock.conn = Mock()
        backend_mock.conn.execute.return_value.fetchall.return_value = []
        self.analyzer.cache_manager.backend = backend_mock

        changes = self.scanner.scan_for_changes()

        self.assertEqual(len(changes.modified_files), 1)
        # Normalize path to handle symlinks (e.g., /var -> /private/var on macOS)
        self.assertIn(os.path.realpath(modified_file), changes.modified_files)

    def test_detect_modified_header(self):
        """Test detection of modified header file."""
        header_file = str(self.test_dir / "header.h")

        # Create the header file
        Path(header_file).write_text("#pragma once\n")

        # Mock file scanner (no source files)
        self.analyzer.file_scanner.find_cpp_files.return_value = []

        # Mock header tracker with old hash
        self.analyzer.header_tracker.get_processed_headers.return_value = {
            header_file: 'old_hash'
        }

        # Mock file hash to indicate change
        self.analyzer._get_file_hash.return_value = 'new_hash'

        # Mock empty cached files
        backend_mock = Mock()
        backend_mock.conn = Mock()
        backend_mock.conn.execute.return_value.fetchall.return_value = []
        self.analyzer.cache_manager.backend = backend_mock

        changes = self.scanner.scan_for_changes()

        self.assertEqual(len(changes.modified_headers), 1)
        # Normalize path to handle symlinks (e.g., /var -> /private/var on macOS)
        self.assertIn(os.path.realpath(header_file), changes.modified_headers)

    def test_detect_deleted_file(self):
        """Test detection of deleted file."""
        deleted_file = str(self.test_dir / "deleted.cpp")

        # Mock file scanner (no files)
        self.analyzer.file_scanner.find_cpp_files.return_value = []

        # Mock cached files to include deleted file
        backend_mock = Mock()
        backend_mock.conn = Mock()
        backend_mock.conn.execute.return_value.fetchall.return_value = [
            (deleted_file,)
        ]
        self.analyzer.cache_manager.backend = backend_mock

        # Mock empty headers
        self.analyzer.header_tracker.get_processed_headers.return_value = {}

        changes = self.scanner.scan_for_changes()

        self.assertEqual(len(changes.removed_files), 1)
        # Normalize path to handle symlinks (e.g., /var -> /private/var on macOS)
        self.assertIn(os.path.realpath(deleted_file), changes.removed_files)

    def test_detect_compile_commands_changed(self):
        """Test detection of compile_commands.json change."""
        cc_file = self.test_dir / "compile_commands.json"
        cc_file.write_text('[]')

        # Mock file scanner
        self.analyzer.file_scanner.find_cpp_files.return_value = []

        # Mock compile_commands_hash to indicate change
        self.analyzer.compile_commands_hash = "old_hash"
        self.analyzer._get_file_hash.return_value = "new_hash"

        # Mock empty headers and cached files
        self.analyzer.header_tracker.get_processed_headers.return_value = {}
        backend_mock = Mock()
        backend_mock.conn = Mock()
        backend_mock.conn.execute.return_value.fetchall.return_value = []
        self.analyzer.cache_manager.backend = backend_mock

        changes = self.scanner.scan_for_changes()

        self.assertTrue(changes.compile_commands_changed)

    def test_check_file_change_unchanged(self):
        """Test _check_file_change for unchanged file."""
        file_path = str(self.test_dir / "unchanged.cpp")

        # Mock cache with matching hash
        self.analyzer.cache_manager.backend.get_file_metadata.return_value = {
            'file_hash': 'same_hash'
        }
        self.analyzer._get_file_hash.return_value = 'same_hash'

        change_type = self.scanner._check_file_change(file_path)

        self.assertEqual(change_type, ChangeType.UNCHANGED)


if __name__ == '__main__':
    unittest.main()
