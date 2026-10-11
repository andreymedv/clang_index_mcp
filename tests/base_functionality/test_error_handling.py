"""
Base Functionality Tests - Error Handling & Recovery

Tests for error tracking, recovery mechanisms, and fallback logic.

Requirements: REQ-1.5 (Cache Management)
Priority: P1
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# Import test infrastructure
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from clang_index_mcp._persistence.cache_manager import CacheManager
from clang_index_mcp._core.error_tracking import ErrorRecord, ErrorTracker
from clang_index_mcp._persistence.error_tracking_adapter import ErrorTrackingAdapter
from clang_index_mcp._persistence.recovery import RecoveryManager
from clang_index_mcp._symbols.model import SymbolInfo


class TestErrorTracker(unittest.TestCase):
    """Test error tracking functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.tracker = ErrorTracker(
            window_seconds=60.0,  # 1 minute window for faster testing
            fallback_threshold=0.05,  # 5% error rate
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
            "TestError", "Test error message", "test_operation", recoverable=True
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
            self.tracker.record_error("TestError", f"Error {i}", "test_op", recoverable=True)

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
                "TestError", f"Error {i}", "test_op", recoverable=True
            )
            self.assertFalse(should_fallback, f"Should not fallback at error {i}")

        # Record one more error (10/200 = 5% - still at threshold, may trigger)
        # Record another one (11/201 = 5.47% > 5% threshold)
        self.tracker.record_operation("test_op")  # 191 ops
        should_fallback = self.tracker.record_error(
            "TestError", "Error 10", "test_op", recoverable=True
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

        self.assertEqual(summary["total_operations"], 15)
        self.assertEqual(summary["total_errors"], 3)
        self.assertEqual(summary["errors_by_type"]["ErrorType1"], 2)
        self.assertEqual(summary["errors_by_type"]["ErrorType2"], 1)
        self.assertEqual(summary["errors_by_operation"]["op1"], 2)
        self.assertEqual(summary["errors_by_operation"]["op2"], 1)

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
        self.cache_managers = []  # Track cache managers for cleanup

        # Create real error-tracking collaborators and inject them into CacheManager
        self.error_tracker = ErrorTracker(
            window_seconds=60.0, fallback_threshold=0.05
        )
        self.recovery_manager = RecoveryManager()
        self.recovery_adapter = ErrorTrackingAdapter(
            error_tracker=self.error_tracker,
            recovery_manager=self.recovery_manager,
        )

    def tearDown(self):
        """Clean up test fixtures"""
        # Close all cache managers to avoid resource leaks
        for cm in self.cache_managers:
            try:
                cm.close()
            except Exception:
                pass
        self.cache_managers.clear()

        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_cache_manager(self):
        """Create a CacheManager and track it for cleanup."""
        cm = CacheManager(self.temp_project_dir, recovery=self.recovery_adapter)
        self.cache_managers.append(cm)
        return cm

    def test_error_tracking_in_cache_manager(self):
        """Test that CacheManager tracks errors"""
        cache_manager = self._create_cache_manager()

        # Get initial error summary
        summary = cache_manager.get_error_summary()
        self.assertEqual(summary["total_errors"], 0)
        self.assertEqual(summary["total_operations"], 0)

    def test_fallback_to_json_on_init_error(self):
        """Verify that a backend failure is handled gracefully (not swallowed) and the error is tracked."""
        # Simulate backend failure by injecting a mock that raises on save
        broken_backend = Mock()
        broken_backend.save_cache.side_effect = OSError("disk I/O error")
        broken_backend.load_cache.side_effect = OSError("disk I/O error")
        broken_backend.close = Mock()

        cm = CacheManager(self.temp_project_dir, backend=broken_backend, recovery=self.recovery_adapter)
        self.cache_managers.append(cm)

        # save_cache should return False (error handled), not raise
        result = cm.save_cache(
            class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
        )
        self.assertFalse(result, "save_cache should return False when backend fails")

        # Error should be tracked in the error summary
        summary = cm.get_error_summary()
        self.assertGreater(summary["total_errors"], 0, "Backend error should be tracked")

    def test_safe_backend_call_handles_errors(self):
        """Test that _safe_backend_call handles exceptions"""
        cache_manager = self._create_cache_manager()

        # Mock backend method to raise an error
        cache_manager.backend.save_cache = Mock(side_effect=Exception("Test error"))

        # Call should handle the error gracefully
        result = cache_manager.save_cache(
            class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
        )

        # Should return False (error handled)
        self.assertFalse(result, "Should return False on error")

        # Error should be tracked
        summary = cache_manager.get_error_summary()
        self.assertGreater(summary["total_errors"], 0, "Should have tracked the error")
        self.assertGreater(summary["total_operations"], 0, "Should have tracked the operation")

    def test_error_rate_triggers_fallback(self):
        """Test that high error rate triggers fallback"""
        cache_manager = self._create_cache_manager()

        # Verify starting with SQLite
        from clang_index_mcp._persistence.sqlite_cache_backend import SqliteCacheBackend

        self.assertIsInstance(cache_manager.backend, SqliteCacheBackend)

        # Simulate many failed operations to trigger fallback
        cache_manager.backend.save_cache = Mock(
            side_effect=sqlite3.DatabaseError("Simulated corruption")
        )

        # Make 100 save attempts (will fail with DatabaseError)
        for i in range(100):
            cache_manager.save_cache(
                class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
            )

            # Check if fallback triggered
            if self.error_tracker.fallback_triggered:
                break

        # Fallback should be triggered
        self.assertTrue(self.error_tracker.fallback_triggered)

        # Should now be using JSON backend

    def test_corruption_triggers_recovery(self):
        """Corruption: backup + repair + retry once (REQ-6.7.3 / REQ-9.3.4)."""
        cache_manager = self._create_cache_manager()

        # Record successful operations to avoid immediate fallback
        for i in range(100):
            self.error_tracker.record_operation("test_op")

        # Get DB path
        db_path = cache_manager.cache_dir / "symbols.db"

        # Mock backend to raise corruption error once, then succeed on retry
        corruption_error = sqlite3.DatabaseError("database disk image is malformed")
        save_mock = Mock(side_effect=[corruption_error, True])
        cache_manager.backend.save_cache = save_mock

        # Mock recovery manager (keep the fault-injected backend in place)
        self.recovery_manager.backup_database = Mock(return_value=str(db_path) + ".backup")
        self.recovery_manager.attempt_repair = Mock(return_value=True)
        self.recovery_manager.clear_cache = Mock(return_value=True)
        cache_manager._reconnect_backend = Mock(return_value=True)

        # Attempt save (will trigger error handling)
        result = cache_manager.save_cache(
            class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
        )

        # Verify recovery was attempted and the operation was retried once
        self.recovery_manager.backup_database.assert_called_once()
        self.recovery_manager.attempt_repair.assert_called_once()
        self.assertEqual(
            save_mock.call_count,
            2,
            "Corruption path must retry the operation exactly once after recovery",
        )
        self.assertTrue(result, "Retry after successful repair should succeed")
        # Last resort clear is NOT reached when repair succeeds
        self.recovery_manager.clear_cache.assert_not_called()

    def test_corruption_last_resort_clear_only_when_unrepairable(self):
        """Clearing happens only after backup + failed repair (unreadable)."""
        cache_manager = self._create_cache_manager()
        db_path = cache_manager.cache_dir / "symbols.db"

        corruption_error = sqlite3.DatabaseError("database disk image is malformed")
        save_mock = Mock(side_effect=corruption_error)
        cache_manager.backend.save_cache = save_mock
        self.recovery_manager.backup_database = Mock(return_value=str(db_path) + ".backup")
        self.recovery_manager.attempt_repair = Mock(return_value=False)
        self.recovery_manager.clear_cache = Mock(return_value=True)
        cache_manager._reconnect_backend = Mock(return_value=True)

        result = cache_manager.save_cache(
            class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
        )

        self.assertFalse(result)
        self.recovery_manager.backup_database.assert_called_once()
        self.recovery_manager.attempt_repair.assert_called_once()
        # Repair failed and DB is unreadable beyond repair -> last-resort clear
        self.recovery_manager.clear_cache.assert_called_once()
        # Retry after last-resort rebuild still uses the original callable
        self.assertEqual(save_mock.call_count, 2)

    def test_corruption_backup_failure_never_clears(self):
        """If the forensic backup fails, the cache must not be cleared."""
        cache_manager = self._create_cache_manager()

        corruption_error = sqlite3.DatabaseError("database disk image is malformed")
        cache_manager.backend.save_cache = Mock(side_effect=corruption_error)
        self.recovery_manager.backup_database = Mock(return_value=None)
        self.recovery_manager.attempt_repair = Mock(return_value=True)
        self.recovery_manager.clear_cache = Mock(return_value=True)

        cache_manager.save_cache(
            class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
        )

        self.recovery_manager.backup_database.assert_called_once()
        self.recovery_manager.attempt_repair.assert_not_called()
        self.recovery_manager.clear_cache.assert_not_called()

    def test_reset_error_tracking(self):
        """Test resetting error tracking"""
        cache_manager = self._create_cache_manager()

        # Generate some errors by calling save_cache with a mocked failing backend
        cache_manager.backend.save_cache = Mock(side_effect=Exception("Test error"))

        # Try to save cache multiple times to generate errors
        for i in range(5):
            cache_manager.save_cache(
                class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
            )

        # Verify errors tracked
        summary = cache_manager.get_error_summary()
        self.assertGreater(summary["total_errors"], 0, "Should have recorded errors")

        # Reset
        cache_manager.reset_error_tracking()

        # Verify reset
        summary = cache_manager.get_error_summary()
        self.assertEqual(summary["total_errors"], 0, "Errors should be reset")


class TestErrorHandlingScenarios(unittest.TestCase):
    """Test specific error scenarios"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_project_dir = Path(self.temp_dir)
        self.cache_managers = []  # Track cache managers for cleanup

        # Create a real recovery adapter so CacheManager does not build its own
        self.recovery_manager = RecoveryManager()
        self.recovery_adapter = ErrorTrackingAdapter(
            recovery_manager=self.recovery_manager,
        )

    def tearDown(self):
        """Clean up test fixtures"""
        # Close all cache managers to avoid resource leaks
        for cm in self.cache_managers:
            try:
                cm.close()
            except Exception:
                pass
        self.cache_managers.clear()

        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_cache_manager(self):
        """Create a CacheManager and track it for cleanup."""
        cm = CacheManager(self.temp_project_dir, recovery=self.recovery_adapter)
        self.cache_managers.append(cm)
        return cm

    def test_permission_error_handling(self):
        """Permission errors fail fast and NEVER clear the cache (REQ-6.7.2/9.4.1)."""
        cache_manager = self._create_cache_manager()

        # Mock permission error
        cache_manager.backend.save_cache = Mock(side_effect=PermissionError("Access denied"))

        # Mock clear cache — must not be called for resource errors
        self.recovery_manager.clear_cache = Mock(return_value=True)
        self.recovery_manager.backup_database = Mock(return_value="x.backup")
        self.recovery_manager.attempt_repair = Mock(return_value=True)

        # Attempt operation
        result = cache_manager.save_cache(
            class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
        )

        # Should handle error
        self.assertFalse(result, "Should return False on permission error")

        # Cache is preserved: no clearing, no recovery, no retry
        self.recovery_manager.clear_cache.assert_not_called()
        self.recovery_manager.backup_database.assert_not_called()
        self.recovery_manager.attempt_repair.assert_not_called()
        self.assertEqual(
            cache_manager.backend.save_cache.call_count,
            1,
            "Resource errors must not be retried",
        )

    def test_disk_full_error_handling(self):
        """Disk-full errors fail fast, preserve cache, and log clearly (REQ-9.4.1)."""
        from clang_index_mcp._core import diagnostics

        cache_manager = self._create_cache_manager()

        # Mock disk full error
        cache_manager.backend.save_cache = Mock(
            side_effect=OSError("[Errno 28] No space left on device")
        )

        # Mock clear cache — must not be called for resource errors
        self.recovery_manager.clear_cache = Mock(return_value=True)
        self.recovery_manager.backup_database = Mock(return_value="x.backup")
        self.recovery_manager.attempt_repair = Mock(return_value=True)

        # Attempt operation
        with patch.object(diagnostics, "error") as mock_error:
            result = cache_manager.save_cache(
                class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
            )

        # Should handle error
        self.assertFalse(result, "Should return False on disk full error")

        # Cache preserved, no destructive recovery, no retry
        self.recovery_manager.clear_cache.assert_not_called()
        self.recovery_manager.backup_database.assert_not_called()
        self.recovery_manager.attempt_repair.assert_not_called()
        self.assertEqual(cache_manager.backend.save_cache.call_count, 1)

        # Clear diagnostic message mentioning cache preservation
        messages = " ".join(str(call.args[0]) for call in mock_error.call_args_list)
        self.assertIn("cache preserved", messages)
        self.assertIn("save_cache", messages)

    def test_permission_error_preserves_existing_cache_files(self):
        """Resource errors must leave cache files on disk (REQ-6.7.2)."""
        cache_manager = self._create_cache_manager()
        db_path = cache_manager.cache_dir / "symbols.db"
        db_path.write_text("existing cache")

        cache_manager.backend.save_cache = Mock(side_effect=PermissionError("Access denied"))
        self.recovery_manager.clear_cache = Mock(
            side_effect=self.recovery_manager.clear_cache
        )

        cache_manager.save_cache(
            class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
        )

        self.assertTrue(db_path.exists(), "Cache file must survive a permission error")
        self.recovery_manager.clear_cache.assert_not_called()

    def test_locked_database_retry(self):
        """Transient locked errors are retried with backoff then reported (REQ-6.7.3)."""
        cache_manager = self._create_cache_manager()
        cache_manager.transient_max_attempts = 3
        cache_manager.backoff_base_seconds = 0.01

        locked = sqlite3.OperationalError("database is locked")
        cache_manager.backend.save_cache = Mock(side_effect=locked)

        with patch(
            "clang_index_mcp._persistence.cache_manager.time.sleep"
        ) as mock_sleep:
            result = cache_manager.save_cache(
                class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
            )

        # Should handle error (may not succeed but won't crash)
        self.assertFalse(result, "Should return False on database locked error")

        # 1 initial attempt + 2 retries = 3 calls, 2 sleeps
        self.assertEqual(cache_manager.backend.save_cache.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

        # Error should be tracked
        summary = cache_manager.get_error_summary()
        self.assertGreater(summary["total_errors"], 0, "Should have tracked the error")
        self.assertGreater(summary["total_operations"], 0, "Should have tracked the operation")

    def test_transient_retry_success_after_backoff(self):
        """A transient error that heals on retry returns success without recovery."""
        cache_manager = self._create_cache_manager()
        cache_manager.transient_max_attempts = 3
        cache_manager.backoff_base_seconds = 0.01

        locked = sqlite3.OperationalError("database is locked")
        cache_manager.backend.save_cache = Mock(side_effect=[locked, True])
        self.recovery_manager.clear_cache = Mock(return_value=True)

        with patch(
            "clang_index_mcp._persistence.cache_manager.time.sleep"
        ):
            result = cache_manager.save_cache(
                class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
            )

        self.assertTrue(result)
        self.assertEqual(cache_manager.backend.save_cache.call_count, 2)
        self.recovery_manager.clear_cache.assert_not_called()

    def test_transient_retry_never_clears_cache(self):
        """Transient retries must not destroy the cache."""
        cache_manager = self._create_cache_manager()
        cache_manager.transient_max_attempts = 2
        cache_manager.backoff_base_seconds = 0.01

        cache_manager.backend.save_cache = Mock(
            side_effect=sqlite3.OperationalError("database is busy")
        )
        self.recovery_manager.clear_cache = Mock(return_value=True)
        self.recovery_manager.backup_database = Mock(return_value="x.backup")

        with patch(
            "clang_index_mcp._persistence.cache_manager.time.sleep"
        ):
            cache_manager.save_cache(
                class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
            )

        self.recovery_manager.clear_cache.assert_not_called()
        self.recovery_manager.backup_database.assert_not_called()

    def test_resource_error_records_outcome_without_recovery(self):
        """Resource errors record the error but never attempt recovery."""
        cache_manager = self._create_cache_manager()
        cache_manager.backend.save_cache = Mock(side_effect=OSError(28, "No space left on device"))
        self.recovery_manager.clear_cache = Mock(return_value=True)

        cache_manager.save_cache(
            class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
        )

        summary = cache_manager.get_error_summary()
        self.assertGreater(summary["total_errors"], 0)
        self.assertFalse(summary.get("recovery_attempted", False))
        self.assertFalse(summary.get("recovery_succeeded", False))
        self.recovery_manager.clear_cache.assert_not_called()

    def test_corruption_records_recovery_outcome(self):
        """Corruption recovery outcomes are recorded on the error-state channel."""
        cache_manager = self._create_cache_manager()
        db_path = cache_manager.cache_dir / "symbols.db"

        corruption_error = sqlite3.DatabaseError("database disk image is malformed")
        save_mock = Mock(side_effect=[corruption_error, True])
        cache_manager.backend.save_cache = save_mock
        self.recovery_manager.backup_database = Mock(return_value=str(db_path) + ".backup")
        self.recovery_manager.attempt_repair = Mock(return_value=True)
        cache_manager._reconnect_backend = Mock(return_value=True)

        cache_manager.save_cache(
            class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
        )

        summary = cache_manager.get_error_summary()
        self.assertTrue(summary.get("recovery_attempted"))
        self.assertTrue(summary.get("recovery_succeeded"))
        self.assertGreaterEqual(summary.get("recovery_attempts", 0), 1)
        self.assertGreaterEqual(summary.get("recovery_successes", 0), 1)
        self.assertEqual(save_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
