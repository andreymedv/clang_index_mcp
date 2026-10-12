"""
Degradation mode state machine tests (epic clang_index_mcp-ent, child .10).

Covers the per-operation-class state machine (decision D3): Normal -> Degraded
after N consecutive failures, short-circuit without hitting the backend,
recovery probe after cooldown (at most once per interval), auto-recovery to
Normal, injectable clock (no real sleeps), and rate-limited short-circuit logs.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from clang_index_mcp._persistence.cache_manager import CacheManager
from clang_index_mcp._persistence.degradation import (
    CallAdmission,
    CircuitOpenError,
    DegradationMode,
)
from clang_index_mcp._persistence.error_tracking_adapter import ErrorTrackingAdapter


class FakeClock:
    """Monotonic clock stub so cooldown/probe intervals are deterministic."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestDegradationStateMachine(unittest.TestCase):
    """Unit tests for DegradationMode with a fake clock (no sleeps)."""

    def setUp(self):
        self.clock = FakeClock()
        self.mode = DegradationMode(
            failure_threshold=3,
            cooldown_seconds=30.0,
            probe_interval_seconds=5.0,
            clock=self.clock,
        )

    def test_normal_passes_through(self):
        self.assertEqual(self.mode.admit("load_cache"), CallAdmission.ALLOW)
        self.assertFalse(self.mode.is_degraded("load_cache"))
        self.assertEqual(self.mode.mode_for("load_cache"), "normal")

    def test_fail_n_times_enters_degraded(self):
        for i in range(2):
            self.assertFalse(self.mode.note_failure("load_cache"), f"early degrade at {i}")
            self.assertEqual(self.mode.admit("load_cache"), CallAdmission.ALLOW)

        self.assertTrue(self.mode.note_failure("load_cache"))
        self.assertTrue(self.mode.is_degraded("load_cache"))
        self.assertEqual(self.mode.mode_for("load_cache"), "degraded")

    def test_success_resets_consecutive_failures(self):
        self.mode.note_failure("load_cache")
        self.mode.note_failure("load_cache")
        self.mode.note_success("load_cache")
        self.mode.note_failure("load_cache")
        self.assertFalse(self.mode.is_degraded("load_cache"))
        self.assertEqual(self.mode.snapshot("load_cache").consecutive_failures, 1)

    def test_class_isolation_read_vs_write(self):
        for _ in range(3):
            self.mode.note_failure("save_cache")
        self.assertTrue(self.mode.is_degraded("save_cache"))
        self.assertTrue(self.mode.is_degraded("save_file_cache"))
        self.assertFalse(self.mode.is_degraded("load_cache"))
        self.assertEqual(self.mode.mode_for("load_cache"), "normal")
        self.assertEqual(self.mode.mode_for("save_cache"), "degraded")

    def test_short_circuit_blocks_before_cooldown(self):
        for _ in range(3):
            self.mode.note_failure("load_cache")

        self.assertEqual(self.mode.admit("load_cache"), CallAdmission.SHORT_CIRCUIT)
        self.clock.advance(29.0)
        self.assertEqual(self.mode.admit("load_cache"), CallAdmission.SHORT_CIRCUIT)
        self.assertEqual(self.mode.snapshot("load_cache").short_circuit_count, 2)

    def test_probe_fires_after_cooldown(self):
        for _ in range(3):
            self.mode.note_failure("load_cache")
        self.clock.advance(30.0)
        self.assertEqual(self.mode.admit("load_cache"), CallAdmission.PROBE)

    def test_probe_ok_returns_to_normal(self):
        for _ in range(3):
            self.mode.note_failure("load_cache")
        self.clock.advance(30.0)
        self.assertEqual(self.mode.admit("load_cache"), CallAdmission.PROBE)
        self.mode.note_success("load_cache")

        self.assertFalse(self.mode.is_degraded("load_cache"))
        self.assertEqual(self.mode.admit("load_cache"), CallAdmission.ALLOW)
        self.assertEqual(self.mode.snapshot("load_cache").recovered_count, 1)

    def test_probe_failure_stays_degraded_and_gates_next_probe(self):
        for _ in range(3):
            self.mode.note_failure("load_cache")
        self.clock.advance(30.0)
        self.assertEqual(self.mode.admit("load_cache"), CallAdmission.PROBE)
        self.mode.note_failure("load_cache")

        self.assertTrue(self.mode.is_degraded("load_cache"))
        # Still inside probe interval: short-circuit, not another probe.
        self.assertEqual(self.mode.admit("load_cache"), CallAdmission.SHORT_CIRCUIT)
        self.clock.advance(5.0)
        self.assertEqual(self.mode.admit("load_cache"), CallAdmission.PROBE)

    def test_probe_at_most_once_per_interval(self):
        for _ in range(3):
            self.mode.note_failure("load_cache")
        self.clock.advance(30.0)
        self.assertEqual(self.mode.admit("load_cache"), CallAdmission.PROBE)
        # Second concurrent admit while probe is in flight is short-circuited.
        self.assertEqual(self.mode.admit("load_cache"), CallAdmission.SHORT_CIRCUIT)
        self.mode.note_failure("load_cache")

    def test_should_log_rate_limit_one_per_cooldown(self):
        for _ in range(3):
            self.mode.note_failure("load_cache")

        self.assertTrue(self.mode.should_log("load_cache"))
        for _ in range(50):
            self.assertFalse(self.mode.should_log("load_cache"))
        self.clock.advance(30.0)
        self.assertTrue(self.mode.should_log("load_cache"))
        self.assertFalse(self.mode.should_log("load_cache"))

    def test_get_states_additive_shape(self):
        self.mode.note_failure("save_cache")
        states = self.mode.get_states()
        self.assertIn("read", states)
        self.assertIn("write", states)
        self.assertEqual(states["write"]["consecutive_failures"], 1)
        self.assertEqual(states["write"]["mode"], "normal")
        for key in (
            "mode",
            "consecutive_failures",
            "short_circuit_count",
            "probe_count",
            "recovered_count",
            "entered_count",
        ):
            self.assertIn(key, states["read"])

    def test_reset_restores_normal(self):
        for _ in range(3):
            self.mode.note_failure("load_cache")
        self.mode.reset()
        self.assertFalse(self.mode.is_degraded("load_cache"))
        self.assertEqual(self.mode.admit("load_cache"), CallAdmission.ALLOW)


class TestCacheManagerDegradation(unittest.TestCase):
    """CacheManager wrapper consults the mode before invoking the backend."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_project_dir = Path(self.temp_dir)
        self.cache_managers = []
        self.clock = FakeClock()
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

    def _create_cache_manager(self, backend, **kwargs) -> CacheManager:
        kwargs.setdefault("degradation_failure_threshold", 3)
        kwargs.setdefault("degradation_cooldown_seconds", 30.0)
        kwargs.setdefault("degradation_probe_interval_seconds", 5.0)
        kwargs.setdefault("clock", self.clock)
        cm = CacheManager(
            self.temp_project_dir,
            backend=backend,
            recovery=self.recovery_adapter,
            **kwargs,
        )
        self.cache_managers.append(cm)
        return cm

    def _failing_backend(self, method: str) -> Mock:
        backend = Mock()
        backend.close = Mock()
        setattr(backend, method, Mock(side_effect=OSError("backend down")))
        return backend

    def test_short_circuit_does_not_call_backend(self):
        backend = self._failing_backend("get_canonical_for_alias")
        cm = self._create_cache_manager(backend)

        # N failures hit the backend and enter Degraded.
        for _ in range(3):
            self.assertIsNone(cm.get_canonical_for_alias("Foo"))
        self.assertEqual(backend.get_canonical_for_alias.call_count, 3)

        # Subsequent calls must short-circuit: backend NOT invoked.
        for _ in range(10):
            self.assertIsNone(cm.get_canonical_for_alias("Foo"))
        self.assertEqual(backend.get_canonical_for_alias.call_count, 3)
        self.assertTrue(cm.is_degraded("get_canonical_for_alias"))

        outcome_states = cm.get_error_summary()["degradation"]
        self.assertEqual(outcome_states["read"]["mode"], "degraded")
        self.assertEqual(outcome_states["read"]["short_circuit_count"], 10)

    def test_short_circuit_returns_typed_safe_values(self):
        backend = Mock()
        backend.close = Mock()
        for name, err in (
            ("save_file_cache", OSError("down")),
            ("save_type_aliases_batch", OSError("down")),
            ("get_aliases_for_canonical", OSError("down")),
            ("get_all_alias_mappings", OSError("down")),
        ):
            setattr(backend, name, Mock(side_effect=err))
        cm = self._create_cache_manager(backend)

        # Drive write class into Degraded.
        for _ in range(3):
            self.assertIs(cm.save_file_cache("a.h", [], "h"), False)
        self.assertIs(cm.save_file_cache("a.h", [], "h"), False)
        self.assertEqual(backend.save_file_cache.call_count, 3)

        for _ in range(3):
            self.assertEqual(cm.save_type_aliases_batch([]), 0)

        # Drive read class into Degraded via aliases.
        for _ in range(3):
            self.assertEqual(cm.get_aliases_for_canonical("int"), [])
        self.assertEqual(cm.get_aliases_for_canonical("int"), [])
        self.assertEqual(cm.get_all_alias_mappings(), {})

    def test_probe_after_cooldown_and_auto_recovery(self):
        backend = self._failing_backend("load_file_cache")
        cm = self._create_cache_manager(backend)

        for _ in range(3):
            self.assertIsNone(cm.load_file_cache("a.h", "h"))
        self.assertEqual(backend.load_file_cache.call_count, 3)

        # Before cooldown: still short-circuited.
        self.clock.advance(29.0)
        self.assertIsNone(cm.load_file_cache("a.h", "h"))
        self.assertEqual(backend.load_file_cache.call_count, 3)

        # Past cooldown: the next call is the recovery probe.
        self.clock.advance(1.0)
        backend.load_file_cache = Mock(return_value={"symbols": [], "file_hash": "h"})
        result = cm.load_file_cache("a.h", "h")
        self.assertEqual(result, {"symbols": [], "file_hash": "h"})
        self.assertEqual(backend.load_file_cache.call_count, 1)

        # Probe ok -> Normal: subsequent calls pass through.
        self.assertFalse(cm.is_degraded("load_file_cache"))
        self.assertEqual(cm.load_file_cache("a.h", "h"), {"symbols": [], "file_hash": "h"})
        self.assertEqual(backend.load_file_cache.call_count, 2)

    def test_probe_failure_keeps_short_circuit(self):
        backend = self._failing_backend("load_file_cache")
        cm = self._create_cache_manager(backend)

        for _ in range(3):
            cm.load_file_cache("a.h", "h")
        self.clock.advance(30.0)
        self.assertIsNone(cm.load_file_cache("a.h", "h"))
        self.assertEqual(backend.load_file_cache.call_count, 4)

        # Failed probe: still degraded, next call short-circuits until interval.
        self.assertTrue(cm.is_degraded("load_file_cache"))
        self.assertIsNone(cm.load_file_cache("a.h", "h"))
        self.assertEqual(backend.load_file_cache.call_count, 4)

        self.clock.advance(5.0)
        self.assertIsNone(cm.load_file_cache("a.h", "h"))
        self.assertEqual(backend.load_file_cache.call_count, 5)

    def test_short_circuit_logs_once_per_cooldown(self):
        from clang_index_mcp._core import diagnostics

        backend = self._failing_backend("get_canonical_for_alias")
        cm = self._create_cache_manager(backend)

        for _ in range(3):
            cm.get_canonical_for_alias("Foo")

        with patch.object(diagnostics, "warning") as mock_warning:
            for _ in range(20):
                cm.get_canonical_for_alias("Foo")
            short_circuit_logs = [
                call
                for call in mock_warning.call_args_list
                if "short-circuited" in str(call.args[0])
            ]
            self.assertEqual(len(short_circuit_logs), 1)

            self.clock.advance(30.0)
            for _ in range(20):
                cm.get_canonical_for_alias("Foo")
            short_circuit_logs = [
                call
                for call in mock_warning.call_args_list
                if "short-circuited" in str(call.args[0])
            ]
            self.assertEqual(len(short_circuit_logs), 2)

    def test_short_circuit_outcome_is_circuit_open_error(self):
        from clang_index_mcp._persistence.outcome import BackendOutcome

        backend = self._failing_backend("load_cache")
        cm = self._create_cache_manager(backend)

        for _ in range(3):
            cm.load_cache()
        outcome = cm._safe_backend_call("load_cache", lambda: None)
        self.assertIsInstance(outcome, BackendOutcome)
        self.assertFalse(outcome.ok)
        self.assertIsInstance(outcome.error, CircuitOpenError)

    def test_read_and_write_degrade_independently(self):
        backend = Mock()
        backend.close = Mock()
        backend.save_file_cache = Mock(side_effect=OSError("down"))
        backend.load_file_cache = Mock(return_value={"symbols": [], "file_hash": "h"})
        cm = self._create_cache_manager(backend)

        for _ in range(3):
            cm.save_file_cache("a.h", [], "h")
        self.assertTrue(cm.degradation.is_degraded("save_file_cache"))
        self.assertFalse(cm.degradation.is_degraded("load_file_cache"))

        # Reads still hit the backend while writes are short-circuited.
        self.assertEqual(cm.load_file_cache("a.h", "h"), {"symbols": [], "file_hash": "h"})
        self.assertEqual(backend.load_file_cache.call_count, 1)
        self.assertIs(cm.save_file_cache("a.h", [], "h"), False)
        self.assertEqual(backend.save_file_cache.call_count, 3)

    def test_degradation_visible_in_error_summary(self):
        backend = self._failing_backend("load_cache")
        cm = self._create_cache_manager(backend)
        for _ in range(3):
            cm.load_cache()

        summary = cm.get_error_summary()
        self.assertIn("degradation", summary)
        self.assertEqual(summary["degradation"]["read"]["mode"], "degraded")
        self.assertEqual(summary["degradation"]["read"]["entered_count"], 1)

    def test_constructor_accepts_injected_mode(self):
        mode = DegradationMode(failure_threshold=1, cooldown_seconds=30.0, clock=self.clock)
        backend = self._failing_backend("load_cache")
        cm = self._create_cache_manager(backend, degradation=mode)

        cm.load_cache()
        self.assertTrue(mode.is_degraded("load_cache"))
        self.assertIsNone(cm.load_cache())
        self.assertEqual(backend.load_cache.call_count, 1)


if __name__ == "__main__":
    unittest.main()
