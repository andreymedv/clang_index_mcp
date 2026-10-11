"""
CacheWriterThread resilience tests (epic clang_index_mcp-ent, child .8).

Covers never-die under sustained backend failure, bounded queue with
drop-and-count, write-disabled mode, rate-limited logging, recovery probe
re-enable, and error-summary visibility of writer counters.
"""

import os
import sys
import threading
import unittest
from unittest.mock import Mock

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from clang_index_mcp._indexing.cache_writer import (
    CacheWriteRequest,
    CacheWriterThread,
)
from clang_index_mcp._indexing.worker_result_merger import WorkerResultMerger
from clang_index_mcp._persistence.cache_manager import CacheManager


def _request(i: int) -> CacheWriteRequest:
    return CacheWriteRequest(
        file_path=f"file_{i}.cpp",
        symbols=[],
        file_hash=f"hash-{i}",
        compile_args_hash=None,
        success=True,
        error_message=None,
        retry_count=0,
    )


class FakeClock:
    """Monotonic clock stub so cooldown/probe intervals are deterministic."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestCacheWriterNeverDie(unittest.TestCase):
    """Thread survives 1000 consecutive backend failures (acceptance)."""

    def test_thread_alive_after_1000_failures(self):
        backend_cm = Mock()
        backend_cm.save_file_cache = Mock(side_effect=OSError("backend down"))
        backend_cm.close = Mock()
        backend_cm.backend = Mock()
        backend_cm.backend.get_all_cached_file_paths = Mock(side_effect=OSError("down"))

        writer = CacheWriterThread(
            lambda: backend_cm,
            max_queue_size=16,
            disable_after_failures=5,
            cooldown_seconds=30.0,
            probe_interval_seconds=0.0,
            transient_max_attempts=1,
            sleep=lambda _s: None,
        )
        self.assertTrue(writer.start())

        accepted = 0
        for i in range(1000):
            if writer.enqueue(_request(i)):
                accepted += 1

        # Acceptance: the thread must still be running after the storm.
        self.assertTrue(writer.is_alive)

        writer.stop(timeout=30.0)
        self.assertFalse(writer.is_alive)

        self.assertLessEqual(accepted, 17, "at most bound+in-flight accepted")
        stats = writer.get_stats()
        self.assertLessEqual(stats.queue_size, 16)
        self.assertGreaterEqual(stats.dropped_count, 1000 - 17)
        self.assertFalse(stats.write_enabled, "write-disabled mode must be entered")
        self.assertEqual(stats.mode, "write_disabled")
        self.assertGreaterEqual(stats.failed_count, 5)
        self.assertGreaterEqual(stats.consecutive_failures, 5)

    def test_outer_loop_survives_unexpected_exceptions(self):
        """Even a raising enqueue-side path must not kill the writer thread."""
        calls = {"n": 0}

        def save(*_args, **_kwargs):
            calls["n"] += 1
            raise RuntimeError(f"boom {calls['n']}")

        cm = Mock()
        cm.save_file_cache = save
        cm.close = Mock()
        cm.backend = Mock()
        cm.backend.get_all_cached_file_paths = Mock(return_value=set())

        writer = CacheWriterThread(
            lambda: cm,
            max_queue_size=32,
            disable_after_failures=3,
            transient_max_attempts=1,
            sleep=lambda _s: None,
        )
        writer.start()
        for i in range(50):
            writer.enqueue(_request(i))
        # Give the loop a moment to process, then stop.
        writer.stop(timeout=30.0)
        self.assertGreaterEqual(calls["n"], 1)


class TestBoundedQueueDropAndCount(unittest.TestCase):
    def test_queue_bound_and_drops(self):
        gate = threading.Event()
        cm = Mock()

        def slow_save(*_args, **_kwargs):
            gate.wait(timeout=2.0)
            return True

        cm.save_file_cache = Mock(side_effect=slow_save)
        cm.close = Mock()
        cm.backend = Mock()
        cm.backend.get_all_cached_file_paths = Mock(return_value=set())

        writer = CacheWriterThread(
            lambda: cm,
            max_queue_size=4,
            disable_after_failures=100,
            transient_max_attempts=1,
            sleep=lambda _s: None,
        )
        writer.start()
        # First item is taken by the worker; the rest fill the bound of 4.
        accepted = sum(1 for i in range(20) if writer.enqueue(_request(i)))
        self.assertLessEqual(accepted, 5)
        stats = writer.get_stats()
        self.assertLessEqual(stats.queue_size, 4)
        self.assertGreaterEqual(stats.dropped_count, 15)
        gate.set()
        writer.stop(timeout=30.0)

    def test_producers_check_write_disabled_flag(self):
        cm = Mock()
        cm.save_file_cache = Mock(side_effect=OSError("down"))
        cm.close = Mock()
        cm.backend = Mock()
        cm.backend.get_all_cached_file_paths = Mock(side_effect=OSError("down"))

        writer = CacheWriterThread(
            lambda: cm,
            max_queue_size=8,
            disable_after_failures=2,
            transient_max_attempts=1,
            sleep=lambda _s: None,
        )
        self.assertTrue(writer.is_write_enabled())
        writer.start()
        for i in range(10):
            writer.enqueue(_request(i))
        writer.stop(timeout=30.0)

        self.assertFalse(writer.is_write_enabled())
        self.assertFalse(writer.enqueue(_request(99)))
        self.assertEqual(writer.get_stats().dropped_count >= 1, True)


class TestModeTransitions(unittest.TestCase):
    """fail -> disabled -> probe -> re-enabled."""

    def test_disabled_then_probe_reenables(self):
        clock = FakeClock()
        cm = Mock()
        cm.save_file_cache = Mock(side_effect=OSError("down"))
        cm.close = Mock()
        cm.backend = Mock()
        cm.backend.get_all_cached_file_paths = Mock(side_effect=OSError("down"))

        writer = CacheWriterThread(
            lambda: cm,
            max_queue_size=8,
            disable_after_failures=2,
            cooldown_seconds=10.0,
            probe_interval_seconds=0.0,
            transient_max_attempts=1,
            clock=clock,
            sleep=lambda _s: None,
        )
        writer.start()
        writer.enqueue(_request(1))
        writer.enqueue(_request(2))
        writer.enqueue(_request(3))
        writer.stop(timeout=30.0)

        self.assertFalse(writer.is_write_enabled())

        # Probe fails while the backend is still down.
        self.assertFalse(writer.try_recover(cm))
        self.assertFalse(writer.is_write_enabled())

        # Backend heals; probe succeeds and re-enables writes without restart.
        cm.backend.get_all_cached_file_paths = Mock(return_value=set())
        clock.advance(11.0)
        self.assertTrue(writer.try_recover(cm))
        self.assertTrue(writer.is_write_enabled())
        self.assertEqual(writer.get_stats().consecutive_failures, 0)
        self.assertEqual(writer.get_stats().mode, "normal")

    def test_probe_rate_limited(self):
        clock = FakeClock()
        cm = Mock()
        cm.backend = Mock()
        cm.backend.get_all_cached_file_paths = Mock(side_effect=OSError("down"))

        writer = CacheWriterThread(
            lambda: cm,
            disable_after_failures=1,
            cooldown_seconds=60.0,
            probe_interval_seconds=30.0,
            transient_max_attempts=1,
            clock=clock,
            sleep=lambda _s: None,
        )
        # Force disabled state without running the thread.
        writer._counters.write_enabled = False
        writer._counters.consecutive_failures = 5

        self.assertFalse(writer.try_recover(cm))
        # Immediate second probe is rate-limited (backend not even consulted).
        cm.backend.get_all_cached_file_paths = Mock(side_effect=AssertionError("no call"))
        self.assertFalse(writer.try_recover(cm))

        clock.advance(31.0)
        cm.backend.get_all_cached_file_paths = Mock(return_value=set())
        self.assertTrue(writer.try_recover(cm))


class TestRateLimitedLogging(unittest.TestCase):
    def test_log_once_per_cooldown(self):
        clock = FakeClock()
        cm = Mock()
        cm.save_file_cache = Mock(side_effect=OSError("down"))
        cm.close = Mock()
        cm.backend = Mock()
        cm.backend.get_all_cached_file_paths = Mock(side_effect=OSError("down"))

        logged: list[str] = []
        writer = CacheWriterThread(
            lambda: cm,
            max_queue_size=8,
            disable_after_failures=1,
            cooldown_seconds=60.0,
            probe_interval_seconds=0.0,
            transient_max_attempts=1,
            clock=clock,
            sleep=lambda _s: None,
        )
        original = writer._log_rate_limited

        def capture(message: str) -> None:
            before = writer._counters.last_log_at
            original(message)
            if writer._counters.last_log_at != before:
                logged.append(message)

        writer._log_rate_limited = capture  # type: ignore[method-assign]

        # Force write-disabled mode so producers drop-and-count.
        writer._counters.write_enabled = False
        for i in range(5):
            writer.enqueue(_request(i))

        self.assertEqual(len(logged), 1, f"expected one log per cooldown, got {logged}")
        self.assertEqual(writer.get_stats().dropped_count, 5)

        clock.advance(61.0)
        writer._log_rate_limited("second window")
        self.assertEqual(len(logged), 2)


class TestErrorSummaryVisibility(unittest.TestCase):
    def test_counters_feed_error_summary(self):
        class Orchestrator:
            def __init__(self, cache_manager):
                self.cache_manager = cache_manager

        cm = Mock()
        cm.project_identity = object()
        cm.recovery = Mock()
        cm.recovery.record_error = Mock(return_value=False)
        cm.set_error_summary_extra_provider = Mock()

        merger = WorkerResultMerger(Mock(), Mock(), Orchestrator(cm))
        writer = CacheWriterThread(
            lambda: Mock(save_file_cache=Mock(return_value=True), close=Mock()),
            max_queue_size=4,
            disable_after_failures=1,
            transient_max_attempts=1,
            sleep=lambda _s: None,
        )
        writer.start()
        self.assertTrue(writer.enqueue(_request(1)))
        writer.stop(timeout=10.0)

        merger._cache_writer = writer
        merger._register_writer_stats()

        cm.set_error_summary_extra_provider.assert_called_once()
        provider = cm.set_error_summary_extra_provider.call_args[0][0]
        stats = provider()
        self.assertIn("write_enabled", stats)
        self.assertIn("dropped_count", stats)
        self.assertIn("consecutive_failures", stats)
        self.assertIn("mode", stats)

    def test_writer_error_recorded_on_main_channel(self):
        class Orchestrator:
            def __init__(self, cache_manager):
                self.cache_manager = cache_manager

        recovery = Mock()
        recovery.record_error = Mock(return_value=False)
        cm = Mock()
        cm.recovery = recovery
        merger = WorkerResultMerger(Mock(), Mock(), Orchestrator(cm))

        writer = CacheWriterThread(
            lambda: Mock(
                save_file_cache=Mock(side_effect=OSError("disk full")),
                close=Mock(),
                backend=Mock(),
            ),
            max_queue_size=8,
            disable_after_failures=1,
            transient_max_attempts=1,
            sleep=lambda _s: None,
            error_recorder=merger._record_writer_error,
        )
        writer.start()
        writer.enqueue(_request(1))
        writer.stop(timeout=10.0)

        self.assertTrue(recovery.record_error.called)
        args = recovery.record_error.call_args[0]
        self.assertIn("save_file_cache", args[2])


class TestCacheManagerErrorSummaryHook(unittest.TestCase):
    def test_extra_provider_nested_additively(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cm = CacheManager(Path(tmp))
            try:
                cm.set_error_summary_extra_provider(
                    lambda: {"write_enabled": False, "dropped_count": 3}
                )
                summary = cm.get_error_summary()
                self.assertEqual(summary["cache_writer"]["write_enabled"], False)
                self.assertEqual(summary["cache_writer"]["dropped_count"], 3)
                # Existing keys remain.
                self.assertIn("backend_type", summary)
                self.assertIn("total_errors", summary)
            finally:
                cm.close()


class TestWorkerWriteFailureIsData(unittest.TestCase):
    def test_alias_write_failure_does_not_raise(self):
        from clang_index_mcp._symbols.symbol_index_store import SymbolIndexStore

        class BoomPersistence:
            def save_aliases(self, _aliases):
                raise OSError("sqlite gone")

        store = SymbolIndexStore(
            lock_provider=threading.RLock(),
            alias_persistence=BoomPersistence(),
            cache_manager=Mock(),
            call_graph_port=Mock(),
        )
        store.last_alias_write_ok = True
        # Should not raise.
        count = store.bulk_write_symbols([], [], [Mock()])
        self.assertEqual(count, 0)
        self.assertFalse(store.last_alias_write_ok)

    def test_worker_result_optional_flag_accepted(self):
        class Orchestrator:
            cache_manager = Mock()

        merger = WorkerResultMerger(Mock(), Mock(), Orchestrator())
        # 10-tuple (legacy) and 11-tuple (with cache_write_ok) both merge.
        legacy = ("f.cpp", True, False, [], [], {}, "h", "c", None, 0)
        flagged = ("f.cpp", True, False, [], [], {}, "h", "c", None, 0, False)
        merger.merge_worker_result(legacy, "f.cpp")
        merger.merge_worker_result(flagged, "f.cpp")


if __name__ == "__main__":
    unittest.main()
