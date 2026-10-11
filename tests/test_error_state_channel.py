"""
Error-state channel tests (epic clang_index_mcp-ent, child .3, REQ-6.8.6).

Covers per-operation counters, the most recent error state, per-operation-class
degraded flags (read/write), recovery outcome tracking, and thread safety of the
channel. Back-compat: legacy get_error_summary consumers keep working unchanged.
"""

import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

# Import test infrastructure
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from clang_index_mcp._core.error_tracking import ErrorTracker, operation_class
from clang_index_mcp._persistence.cache_manager import CacheManager
from clang_index_mcp._persistence.error_tracking_adapter import ErrorTrackingAdapter


class TestOperationClassification(unittest.TestCase):
    """Read/write classification of operation names (decision D3)."""

    def test_write_operations(self):
        for op in ("save_cache", "save_file_cache", "remove_file_cache", "ensure_schema_current"):
            self.assertEqual(operation_class(op), "write", op)

    def test_read_operations(self):
        for op in (
            "load_cache",
            "load_file_cache",
            "get_canonical_for_alias",
            "get_type_alias_info",
            "get_aliases_for_canonical",
            "get_all_alias_mappings",
        ):
            self.assertEqual(operation_class(op), "read", op)


class TestErrorStateChannel(unittest.TestCase):
    """Unit tests for the ErrorTracker error-state channel."""

    def setUp(self):
        self.tracker = ErrorTracker(window_seconds=60.0, fallback_threshold=1.1)

    def test_per_operation_counters_and_consecutive_reset(self):
        self.tracker.record_error("OSError", "boom", "save_cache", recoverable=True)
        self.tracker.record_error("OSError", "boom", "save_cache", recoverable=True)

        summary = self.tracker.get_error_summary()
        per_op = summary["per_operation"]["save_cache"]
        self.assertEqual(per_op["errors"], 2)
        self.assertEqual(per_op["consecutive_errors"], 2)

        # Success resets the consecutive counter but keeps totals
        self.tracker.record_operation("save_cache")
        per_op = self.tracker.get_error_summary()["per_operation"]["save_cache"]
        self.assertEqual(per_op["operations"], 1)
        self.assertEqual(per_op["errors"], 2)
        self.assertEqual(per_op["consecutive_errors"], 0)

    def test_last_error_fields(self):
        self.tracker.record_error("OSError", "disk full", "save_cache", recoverable=True)

        summary = self.tracker.get_error_summary()
        last_error = summary["last_error"]
        self.assertIsNotNone(last_error)
        self.assertEqual(last_error["operation"], "save_cache")
        self.assertEqual(last_error["error_type"], "OSError")
        self.assertEqual(last_error["message"], "disk full")
        self.assertIn("timestamp", last_error)

        for_op = self.tracker.last_error_for("save_cache")
        self.assertEqual(for_op["error_type"], "OSError")
        self.assertIsNone(self.tracker.last_error_for("load_cache"))

    def test_degraded_flag_per_class(self):
        # Write failure degrades only the write class
        self.tracker.record_error("OSError", "boom", "save_cache", recoverable=True)
        self.assertTrue(self.tracker.is_degraded("save_cache"))
        self.assertTrue(self.tracker.is_degraded("save_file_cache"))
        summary = self.tracker.get_error_summary()
        self.assertTrue(summary["degraded"]["write"])
        self.assertFalse(summary["degraded"]["read"])

        # Read failure degrades the read class too
        self.tracker.record_error("OSError", "boom", "get_canonical_for_alias", recoverable=True)
        self.assertTrue(self.tracker.is_degraded("get_canonical_for_alias"))
        self.assertTrue(self.tracker.get_error_summary()["degraded"]["read"])

    def test_success_clears_degraded(self):
        self.tracker.record_error("OSError", "boom", "get_type_alias_info", recoverable=True)
        self.assertTrue(self.tracker.is_degraded("get_type_alias_info"))

        self.tracker.record_operation("get_type_alias_info")
        self.assertFalse(self.tracker.is_degraded("get_type_alias_info"))
        self.assertFalse(self.tracker.get_error_summary()["degraded"]["read"])

    def test_get_and_clear_degraded(self):
        self.tracker.record_error("OSError", "boom", "get_canonical_for_alias", recoverable=True)

        # Atomic check-and-clear: first consumer sees it, later ones do not
        self.assertTrue(self.tracker.get_and_clear_degraded("get_canonical_for_alias"))
        self.assertFalse(self.tracker.get_and_clear_degraded("get_canonical_for_alias"))

    def test_mark_degraded_helper(self):
        self.assertFalse(self.tracker.is_degraded("load_cache"))
        self.tracker.mark_degraded("load_cache")
        self.assertTrue(self.tracker.is_degraded("load_cache"))
        self.assertTrue(self.tracker.get_error_summary()["degraded"]["read"])

    def test_record_recovery_tracking(self):
        self.tracker.record_recovery("save_cache", attempted=True, succeeded=False)
        summary = self.tracker.get_error_summary()
        self.assertTrue(summary["recovery_attempted"])
        self.assertFalse(summary["recovery_succeeded"])
        self.assertEqual(summary["recovery_attempts"], 1)
        self.assertEqual(summary["recovery_successes"], 0)

        self.tracker.record_recovery("save_cache", attempted=True, succeeded=True)
        summary = self.tracker.get_error_summary()
        self.assertTrue(summary["recovery_succeeded"])
        self.assertEqual(summary["recovery_successes"], 1)

    def test_summary_backcompat_keys(self):
        self.tracker.record_operation("op1")
        self.tracker.record_error("ErrorType1", "msg", "op1", True)

        summary = self.tracker.get_error_summary()
        for key in (
            "total_errors",
            "total_operations",
            "error_rate",
            "errors_by_type",
            "errors_by_operation",
            "fallback_triggered",
            "fallback_reason",
            "window_seconds",
        ):
            self.assertIn(key, summary)

    def test_reset_clears_channel(self):
        self.tracker.record_error("OSError", "boom", "save_cache", recoverable=True)
        self.tracker.record_recovery("save_cache", attempted=True, succeeded=True)

        self.tracker.reset()

        summary = self.tracker.get_error_summary()
        self.assertIsNone(summary["last_error"])
        self.assertEqual(summary["per_operation"], {})
        self.assertEqual(summary["degraded"], {"read": False, "write": False})
        self.assertFalse(summary["recovery_attempted"])
        self.assertFalse(summary["recovery_succeeded"])
        self.assertEqual(summary["recovery_attempts"], 0)
        self.assertIsNone(self.tracker.last_error_for("save_cache"))
        self.assertFalse(self.tracker.is_degraded("save_cache"))


class TestErrorStateChannelConcurrency(unittest.TestCase):
    """Concurrency smoke test (pattern: tests/test_concurrency_race.py)."""

    def test_concurrent_record_and_query(self):
        tracker = ErrorTracker(window_seconds=60.0, fallback_threshold=1.1)
        thread_count = 8
        iterations = 50
        errors: list[BaseException] = []

        def writer(worker_id: int) -> None:
            try:
                for i in range(iterations):
                    tracker.record_operation("get_type_alias_info")
                    tracker.record_error("OSError", f"boom {i}", "save_cache", recoverable=True)
            except BaseException as e:  # noqa: BLE001 - test collects failures
                errors.append(e)

        def reader(worker_id: int) -> None:
            try:
                for _ in range(iterations):
                    tracker.get_error_summary()
                    tracker.is_degraded("save_cache")
                    tracker.last_error_for("save_cache")
                    tracker.get_and_clear_degraded("get_type_alias_info")
            except BaseException as e:  # noqa: BLE001 - test collects failures
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=(i,)) for i in range(thread_count // 2)
        ] + [threading.Thread(target=reader, args=(i,)) for i in range(thread_count // 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        summary = tracker.get_error_summary()
        self.assertEqual(
            summary["per_operation"]["save_cache"]["errors"], (thread_count // 2) * iterations
        )
        self.assertEqual(
            summary["per_operation"]["get_type_alias_info"]["operations"],
            (thread_count // 2) * iterations,
        )


class TestCacheManagerErrorStateChannel(unittest.TestCase):
    """CacheManager-level delegation to the error-state channel."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_project_dir = Path(self.temp_dir)
        self.cache_managers = []
        self.recovery_adapter = ErrorTrackingAdapter()

    def tearDown(self):
        for cm in self.cache_managers:
            try:
                cm.close()
            except Exception:
                pass
        self.cache_managers.clear()
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_cache_manager(self, backend):
        cm = CacheManager(
            self.temp_project_dir, backend=backend, recovery=self.recovery_adapter
        )
        self.cache_managers.append(cm)
        return cm

    def test_failed_lookup_marks_degraded(self):
        backend = Mock()
        backend.close = Mock()
        backend.get_canonical_for_alias = Mock(side_effect=OSError("backend down"))
        cm = self._create_cache_manager(backend)

        result = cm.get_canonical_for_alias("Foo")

        # Current contract: None on error (typed mapping lands in child .4);
        # the channel already reports the degraded state (REQ-6.8.6).
        self.assertIsNone(result)
        self.assertTrue(cm.is_degraded("get_canonical_for_alias"))
        self.assertIsNotNone(cm.last_error_for("get_canonical_for_alias"))

        summary = cm.get_error_summary()
        self.assertIsNotNone(summary["last_error"])
        self.assertEqual(summary["last_error"]["operation"], "get_canonical_for_alias")
        self.assertTrue(summary["degraded"]["read"])

        # Atomic consume: a later check without a fresh failure reports clean
        self.assertTrue(cm.get_and_clear_degraded("get_canonical_for_alias"))
        self.assertFalse(cm.get_and_clear_degraded("get_canonical_for_alias"))

    def test_successful_call_clears_degraded(self):
        backend = Mock()
        backend.close = Mock()
        backend.get_type_alias_info = Mock(side_effect=OSError("backend down"))
        cm = self._create_cache_manager(backend)

        cm.get_type_alias_info("Foo")
        self.assertTrue(cm.is_degraded("get_type_alias_info"))

        backend.get_type_alias_info = Mock(return_value=None)
        cm.get_type_alias_info("Foo")
        self.assertFalse(cm.is_degraded("get_type_alias_info"))

    def test_channel_helpers_are_defensive(self):
        # A recovery double without channel methods must not break the manager
        class MinimalRecovery:
            def record_operation(self, operation):
                pass

            def record_error(self, error_type, error_message, operation, recoverable=True):
                return False

            def get_error_summary(self):
                return {"total_errors": 0, "total_operations": 0}

            def reset(self):
                pass

        cm = CacheManager(
            self.temp_project_dir, backend=Mock(close=Mock()), recovery=MinimalRecovery()
        )
        self.cache_managers.append(cm)

        self.assertFalse(cm.is_degraded("save_cache"))
        self.assertFalse(cm.get_and_clear_degraded("save_cache"))
        self.assertIsNone(cm.last_error_for("save_cache"))
        cm.mark_degraded("save_cache")  # must not raise
        cm.record_recovery_outcome("save_cache", attempted=True, succeeded=True)  # must not raise


if __name__ == "__main__":
    unittest.main()
