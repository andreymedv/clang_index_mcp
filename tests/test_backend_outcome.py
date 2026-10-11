"""
Tests for BackendOutcome and CacheManager._safe_backend_call (REQ-6.8.5).

Covers the outcome contract: never bare None, never raises, retry-once after
successful recovery, and empty-vs-error disambiguation.
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from clang_index_mcp._persistence.cache_manager import CacheManager
from clang_index_mcp._persistence.error_tracking_adapter import ErrorTrackingAdapter
from clang_index_mcp._persistence.outcome import BackendOutcome
from clang_index_mcp._persistence.recovery import RecoveryManager


class TestBackendOutcome(unittest.TestCase):
    """Unit tests for the BackendOutcome type itself."""

    def test_ok_property(self):
        self.assertTrue(BackendOutcome(value=42).ok)
        self.assertTrue(BackendOutcome(value=None).ok)
        self.assertFalse(BackendOutcome(error=RuntimeError("x")).ok)

    def test_success_carries_value(self):
        outcome = BackendOutcome(value=[1, 2])
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.value, [1, 2])
        self.assertIsNone(outcome.error)
        self.assertFalse(outcome.recovered)

    def test_failure_carries_error(self):
        err = RuntimeError("boom")
        outcome = BackendOutcome(error=err)
        self.assertFalse(outcome.ok)
        self.assertIs(outcome.error, err)
        self.assertIsNone(outcome.value)


class TestSafeBackendCall(unittest.TestCase):
    """Fault-injection tests for CacheManager._safe_backend_call."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_project_dir = Path(self.temp_dir)
        self.cache_managers = []
        self.recovery_manager = RecoveryManager()
        self.recovery_adapter = ErrorTrackingAdapter(recovery_manager=self.recovery_manager)

    def tearDown(self):
        for cm in self.cache_managers:
            try:
                cm.close()
            except Exception:
                pass
        self.cache_managers.clear()
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_cache_manager(self, **kwargs) -> CacheManager:
        cm = CacheManager(
            self.temp_project_dir, recovery=self.recovery_adapter, **kwargs
        )
        self.cache_managers.append(cm)
        return cm

    def test_success_returns_ok_value(self):
        cm = self._create_cache_manager()
        func = Mock(return_value={"symbols": 3})

        outcome = cm._safe_backend_call("load_cache", func, "arg")

        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.value, {"symbols": 3})
        self.assertIsNone(outcome.error)
        self.assertFalse(outcome.recovered)
        func.assert_called_once_with("arg")

    def test_backend_raises_returns_error_outcome(self):
        cm = self._create_cache_manager()
        error = Exception("Test error")
        func = Mock(side_effect=error)

        outcome = cm._safe_backend_call("save_cache", func)

        self.assertFalse(outcome.ok)
        self.assertIs(outcome.error, error)
        self.assertIsNone(outcome.value)
        self.assertFalse(outcome.recovered)
        self.assertEqual(func.call_count, 1)

    def test_legit_none_is_ok_not_error(self):
        cm = self._create_cache_manager()
        func = Mock(return_value=None)

        outcome = cm._safe_backend_call("get_canonical_for_alias", func, "Missing")

        self.assertTrue(outcome.ok)
        self.assertIsNone(outcome.value)
        self.assertIsNone(outcome.error)

    def test_retry_once_after_successful_recovery(self):
        cm = self._create_cache_manager()
        first = sqlite3.DatabaseError("database disk image is malformed")
        func = Mock(side_effect=[first, "recovered-result"])
        cm._attempt_recovery = Mock(return_value=True)

        outcome = cm._safe_backend_call("save_cache", func)

        self.assertEqual(func.call_count, 2)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.value, "recovered-result")
        self.assertTrue(outcome.recovered)
        cm._attempt_recovery.assert_called_once()

    def test_recovery_failure_reports_error_without_retry(self):
        cm = self._create_cache_manager()
        error = sqlite3.DatabaseError("database disk image is malformed")
        func = Mock(side_effect=error)
        cm._attempt_recovery = Mock(return_value=False)

        outcome = cm._safe_backend_call("save_cache", func)

        self.assertEqual(func.call_count, 1)
        self.assertFalse(outcome.ok)
        self.assertIs(outcome.error, error)
        self.assertIsNone(outcome.value)
        self.assertFalse(outcome.recovered)
        cm._attempt_recovery.assert_called_once()

    def test_never_raises_when_error_handling_raises(self):
        cm = self._create_cache_manager()
        error = OSError("disk full")
        func = Mock(side_effect=error)
        cm.recovery.record_error = Mock(side_effect=RuntimeError("tracking exploded"))

        outcome = cm._safe_backend_call("save_cache", func)

        self.assertIsInstance(outcome, BackendOutcome)
        self.assertFalse(outcome.ok)
        self.assertIs(outcome.error, error)
        self.assertIsNone(outcome.value)
        self.assertEqual(func.call_count, 1)

    def test_never_raises_when_handle_backend_error_raises(self):
        cm = self._create_cache_manager()
        error = OSError("disk full")
        func = Mock(side_effect=error)
        cm._handle_backend_error = Mock(side_effect=RuntimeError("handler exploded"))

        outcome = cm._safe_backend_call("save_cache", func)

        self.assertIsInstance(outcome, BackendOutcome)
        self.assertFalse(outcome.ok)
        self.assertIs(outcome.error, error)

    def test_retry_error_is_carried_not_raised(self):
        cm = self._create_cache_manager()
        first = sqlite3.DatabaseError("database disk image is malformed")
        second = RuntimeError("retry also failed")
        func = Mock(side_effect=[first, second])
        cm._attempt_recovery = Mock(return_value=True)

        outcome = cm._safe_backend_call("save_cache", func)

        self.assertEqual(func.call_count, 2)
        self.assertFalse(outcome.ok)
        self.assertIs(outcome.error, second)
        self.assertFalse(outcome.recovered)

    def test_zero_retry_limit_skips_retry(self):
        cm = self._create_cache_manager()
        error = sqlite3.DatabaseError("database disk image is malformed")
        func = Mock(side_effect=error)
        cm._attempt_recovery = Mock(return_value=True)
        cm._max_retries_after_recovery = 0

        outcome = cm._safe_backend_call("save_cache", func)

        self.assertEqual(func.call_count, 1)
        self.assertFalse(outcome.ok)
        self.assertIs(outcome.error, error)
        self.assertFalse(outcome.recovered)


if __name__ == "__main__":
    unittest.main()
