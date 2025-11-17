"""
Base Functionality Tests - Error Handling & Recovery

Tests for error tracking, recovery mechanisms, and fallback logic.

Requirements: REQ-1.5 (Cache Management)
Priority: P1
"""

import unittest
import os
import sys
import tempfile
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import patch, Mock, MagicMock

# Import test infrastructure
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.error_tracking import ErrorTracker, RecoveryManager, ErrorRecord
from mcp_server.cache_manager import CacheManager
from mcp_server.symbol_info import SymbolInfo


class TestErrorTracker(unittest.TestCase):
    """Test error tracking functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.tracker = ErrorTracker(
            window_seconds=60.0,  # 1 minute window for faster testing
            fallback_threshold=0.05  # 5% error rate
        )

    def test_record_operation(self):
        """Test recording successful operations"""
        self.tracker.record_operation("test_op")
        self.tracker.record_operation("test_op")
        self.tracker.record_operation("another_op")

        self.assertEqual(self.tracker.operation_counts["test_op"], 2)
        self.assertEqual(self.tracker.operation_counts["another_op"], 1)

    def test_record_error(self):
        """Test recording errors"""
        # Record an error
        should_fallback = self.tracker.record_error(
            "TestError",
            "Test error message",
            "test_operation",
            recoverable=True
        )

        # Should not trigger fallback yet (need higher error rate)
        self.assertFalse(should_fallback)
        self.assertEqual(len(self.tracker.error_history), 1)

    def test_error_rate_calculation(self):
        """Test error rate calculation"""
        # Record 95 successful operations
        for i in range(95):
            self.tracker.record_operation("test_op")

        # Record 5 errors (5% error rate)
        for i in range(5):
            self.tracker.record_error(
                "TestError",
                f"Error {i}",
                "test_op",
                recoverable=True
            )

        # Error rate should be 5/100 = 5%
        error_rate = self.tracker.get_error_rate()
        self.assertAlmostEqual(error_rate, 0.05, places=2)

    def test_fallback_trigger(self):
        """Test that fallback is triggered at threshold"""
        # Record 190 successful operations
        for i in range(190):
            self.tracker.record_operation("test_op")

        # Record 9 errors (9/199 = 4.5% - not enough to trigger)
        for i in range(9):
            should_fallback = self.tracker.record_error(
                "TestError",
                f"Error {i}",
                "test_op",
                recoverable=True
            )
            self.assertFalse(should_fallback, f"Should not fallback at error {i}")

        # Record one more error (10/200 = 5% - still at threshold, may trigger)
        # Record another one (11/201 = 5.47% > 5% threshold)
        self.tracker.record_operation("test_op")  # 191 ops
        should_fallback = self.tracker.record_error(
            "TestError",
            "Error 10",
            "test_op",
            recoverable=True
        )

        # Should trigger fallback
        self.assertTrue(should_fallback)
        self.assertTrue(self.tracker.fallback_triggered)

    def test_error_summary(self):
        """Test error summary reporting"""
        # Record some operations and errors
        for i in range(10):
            self.tracker.record_operation("op1")
        for i in range(5):
            self.tracker.record_operation("op2")

        self.tracker.record_error("ErrorType1", "msg1", "op1", True)
        self.tracker.record_error("ErrorType1", "msg2", "op1", True)
        self.tracker.record_error("ErrorType2", "msg3", "op2", False)

        summary = self.tracker.get_error_summary()

        self.assertEqual(summary['total_operations'], 15)
        self.assertEqual(summary['total_errors'], 3)
        self.assertEqual(summary['errors_by_type']['ErrorType1'], 2)
        self.assertEqual(summary['errors_by_type']['ErrorType2'], 1)
        self.assertEqual(summary['errors_by_operation']['op1'], 2)
        self.assertEqual(summary['errors_by_operation']['op2'], 1)

    def test_reset(self):
        """Test resetting error tracker"""
        # Record some data
        self.tracker.record_operation("test")
        self.tracker.record_error("TestError", "msg", "test", True)

        # Reset
        self.tracker.reset()

        # Verify reset
        self.assertEqual(len(self.tracker.error_history), 0)
        self.assertEqual(len(self.tracker.operation_counts), 0)
        self.assertFalse(self.tracker.fallback_triggered)


class TestRecoveryManager(unittest.TestCase):
    """Test recovery manager functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        self.recovery = RecoveryManager()

    def tearDown(self):
        """Clean up test fixtures"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_backup_database(self):
        """Test database backup creation"""
        # Create a test database file
        self.db_path.write_text("test database content")

        # Create backup
        backup_path = self.recovery.backup_database(self.db_path)

        # Verify backup
        self.assertIsNotNone(backup_path)
        self.assertTrue(Path(backup_path).exists())
        self.assertEqual(Path(backup_path).read_text(), "test database content")

    def test_backup_nonexistent_database(self):
        """Test backing up non-existent database"""
        # Try to backup non-existent file
        backup_path = self.recovery.backup_database(self.db_path)

        # Should return None
        self.assertIsNone(backup_path)

    def test_restore_from_backup(self):
        """Test restoring database from backup"""
        # Create original and backup
        self.db_path.write_text("corrupted data")
        backup_path = Path(self.temp_dir) / "test.backup"
        backup_path.write_text("good data")

        # Restore
        success = self.recovery.restore_from_backup(self.db_path, backup_path)

        # Verify
        self.assertTrue(success)
        self.assertEqual(self.db_path.read_text(), "good data")

    def test_clear_cache(self):
        """Test clearing cache directory"""
        # Create some cache files
        (Path(self.temp_dir) / "symbols.db").write_text("db")
        (Path(self.temp_dir) / "symbols.db-wal").write_text("wal")
        (Path(self.temp_dir) / "symbols.db-shm").write_text("shm")
        (Path(self.temp_dir) / "old.backup").write_text("backup")
        (Path(self.temp_dir) / "keep.txt").write_text("keep this")

        # Clear cache
        success = self.recovery.clear_cache(self.temp_dir)

        # Verify
        self.assertTrue(success)
        self.assertFalse((Path(self.temp_dir) / "symbols.db").exists())
        self.assertFalse((Path(self.temp_dir) / "symbols.db-wal").exists())
        self.assertFalse((Path(self.temp_dir) / "symbols.db-shm").exists())
        self.assertFalse((Path(self.temp_dir) / "old.backup").exists())
        self.assertTrue((Path(self.temp_dir) / "keep.txt").exists())


class TestCacheManagerErrorHandling(unittest.TestCase):
    """Test CacheManager error handling integration"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_project_dir = Path(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_error_tracking_in_cache_manager(self):
        """Test that CacheManager tracks errors"""
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "1"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Get initial error summary
            summary = cache_manager.get_error_summary()
            self.assertEqual(summary['total_errors'], 0)
            self.assertEqual(summary['total_operations'], 0)

    def test_fallback_to_json_on_init_error(self):
        """Test fallback to JSON when SQLite init fails"""
        # Mock SqliteCacheBackend to raise an error
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "1"}):
            with patch('mcp_server.cache_manager.SqliteCacheBackend') as mock_sqlite:
                mock_sqlite.side_effect = Exception("SQLite not available")

                # Should fallback to JSON
                cache_manager = CacheManager(self.temp_project_dir)

                # Verify using JSON backend
                from mcp_server.json_cache_backend import JsonCacheBackend
                self.assertIsInstance(cache_manager.backend, JsonCacheBackend)

    def test_safe_backend_call_handles_errors(self):
        """Test that _safe_backend_call handles exceptions"""
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "1"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Record many successful operations first to avoid immediate fallback
            for i in range(100):
                cache_manager.error_tracker.record_operation("test_op")

            # Mock backend method to raise an error (but not enough to trigger fallback)
            cache_manager.backend.save_cache = Mock(side_effect=Exception("Test error"))

            # Call should handle the error gracefully
            result = cache_manager.save_cache(
                class_index={},
                function_index={},
                file_hashes={},
                indexed_file_count=0
            )

            # Should return False (error handled)
            self.assertFalse(result)

            # Error should be tracked
            summary = cache_manager.get_error_summary()
            self.assertGreater(summary['total_errors'], 0)

    def test_error_rate_triggers_fallback(self):
        """Test that high error rate triggers fallback"""
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "1"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Verify starting with SQLite
            from mcp_server.sqlite_cache_backend import SqliteCacheBackend
            self.assertIsInstance(cache_manager.backend, SqliteCacheBackend)

            # Simulate many failed operations to trigger fallback
            cache_manager.backend.save_cache = Mock(side_effect=sqlite3.DatabaseError("Simulated corruption"))

            # Make 100 save attempts (will fail with DatabaseError)
            for i in range(100):
                cache_manager.save_cache(
                    class_index={},
                    function_index={},
                    file_hashes={},
                    indexed_file_count=0
                )

                # Check if fallback triggered
                if cache_manager.fallback_active:
                    break

            # Fallback should be triggered
            self.assertTrue(cache_manager.fallback_active)

            # Should now be using JSON backend
            from mcp_server.json_cache_backend import JsonCacheBackend
            self.assertIsInstance(cache_manager.backend, JsonCacheBackend)

    def test_corruption_triggers_recovery(self):
        """Test that corruption triggers recovery attempt"""
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "1"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Record successful operations to avoid immediate fallback
            for i in range(100):
                cache_manager.error_tracker.record_operation("test_op")

            # Get DB path
            db_path = cache_manager.cache_dir / "symbols.db"

            # Mock backend to raise corruption error
            corruption_error = sqlite3.DatabaseError("database disk image is malformed")
            cache_manager.backend.save_cache = Mock(side_effect=corruption_error)

            # Mock recovery manager
            cache_manager.recovery_manager.backup_database = Mock(return_value=str(db_path) + ".backup")
            cache_manager.recovery_manager.attempt_repair = Mock(return_value=True)

            # Attempt save (will trigger error handling)
            result = cache_manager.save_cache(
                class_index={},
                function_index={},
                file_hashes={},
                indexed_file_count=0
            )

            # Verify recovery was attempted
            cache_manager.recovery_manager.backup_database.assert_called_once()
            cache_manager.recovery_manager.attempt_repair.assert_called_once()

    def test_reset_error_tracking(self):
        """Test resetting error tracking"""
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "1"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Record successful operations first
            for i in range(100):
                cache_manager.error_tracker.record_operation("test_op")

            # Generate some errors
            cache_manager.backend.load_cache = Mock(side_effect=Exception("Test error"))
            cache_manager.load_cache()

            # Verify errors tracked
            summary = cache_manager.get_error_summary()
            self.assertGreater(summary['total_errors'], 0)

            # Reset
            cache_manager.reset_error_tracking()

            # Verify reset
            summary = cache_manager.get_error_summary()
            self.assertEqual(summary['total_errors'], 0)


class TestErrorHandlingScenarios(unittest.TestCase):
    """Test specific error scenarios"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_project_dir = Path(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_permission_error_handling(self):
        """Test handling of permission errors"""
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "1"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Record successful operations first
            for i in range(100):
                cache_manager.error_tracker.record_operation("test_op")

            # Mock permission error
            cache_manager.backend.save_cache = Mock(side_effect=PermissionError("Access denied"))

            # Mock clear cache to succeed
            cache_manager.recovery_manager.clear_cache = Mock(return_value=True)

            # Attempt operation
            result = cache_manager.save_cache(
                class_index={},
                function_index={},
                file_hashes={},
                indexed_file_count=0
            )

            # Should handle error
            self.assertFalse(result)

            # Recovery should be attempted
            cache_manager.recovery_manager.clear_cache.assert_called_once()

    def test_disk_full_error_handling(self):
        """Test handling of disk full errors"""
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "1"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Record successful operations first
            for i in range(100):
                cache_manager.error_tracker.record_operation("test_op")

            # Mock disk full error
            cache_manager.backend.save_cache = Mock(side_effect=OSError("[Errno 28] No space left on device"))

            # Mock clear cache to succeed
            cache_manager.recovery_manager.clear_cache = Mock(return_value=True)

            # Attempt operation
            result = cache_manager.save_cache(
                class_index={},
                function_index={},
                file_hashes={},
                indexed_file_count=0
            )

            # Should handle error
            self.assertFalse(result)

            # Recovery should be attempted
            cache_manager.recovery_manager.clear_cache.assert_called_once()

    def test_locked_database_retry(self):
        """Test handling of database locked errors"""
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "1"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Record successful operations first
            for i in range(100):
                cache_manager.error_tracker.record_operation("test_op")

            # Mock database locked error (considered non-recoverable in our classification)
            cache_manager.backend.save_cache = Mock(side_effect=sqlite3.OperationalError("database is locked"))

            # Attempt operation
            result = cache_manager.save_cache(
                class_index={},
                function_index={},
                file_hashes={},
                indexed_file_count=0
            )

            # Should handle error (may not succeed but won't crash)
            self.assertFalse(result)

            # Error should be tracked
            summary = cache_manager.get_error_summary()
            self.assertGreater(summary['total_errors'], 0)


if __name__ == '__main__':
    unittest.main()
