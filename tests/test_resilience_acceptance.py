"""Acceptance suite for epic clang_index_mcp-ent (child .11).

Cross-cutting proof that the epic's behavioral contract holds end-to-end.
This module is the epic's completion checklist.

Scenarios (from the epic analysis):
1. Total backend outage — indexing completes, query tools stay valid,
   error summary reports failures, short-circuit logs are rate-limited.
2. Alias store down — alias tools return degraded-but-valid responses
   (empty vs unavailable); core symbol tools stay unchanged.
3. Disk-full on save_cache (OSError 28) — existing cache file preserved,
   warning logged, in-memory queries unaffected, next run rebuilds.
4. Writer stress — 1000 consecutive write failures leave CacheWriterThread
   alive, queue bounded, drops counted.
5. Recovery — backend heals, degradation probe returns to Normal,
   persistence resumes without a process restart.

The basedpyright type gate is a separate make target (`basedpyright-gate`)
and is intentionally not exercised here.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from clang_index_mcp._indexing.cache_writer import (
    CacheWriteRequest,
    CacheWriterThread,
)
from clang_index_mcp._mcp.context import ctx
from clang_index_mcp._mcp.state_manager import AnalyzerState, AnalyzerStateManager
from clang_index_mcp._persistence.cache_manager import CacheManager
from clang_index_mcp._persistence.degradation import CallAdmission, DegradationMode
from clang_index_mcp._persistence.error_tracking_adapter import ErrorTrackingAdapter
from clang_index_mcp.cpp_analyzer import CppAnalyzer

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class FakeClock:
    """Monotonic clock stub so cooldown/probe intervals are deterministic."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class AlwaysFailBackend:
    """Backend proxy that raises on every cache operation."""

    def __init__(self, error: BaseException | None = None) -> None:
        self._error = error or OSError("backend down")
        self.call_counts: dict[str, int] = {}

    def close(self) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def _fail(*args: Any, **kwargs: Any) -> Any:
            self.call_counts[name] = self.call_counts.get(name, 0) + 1
            raise self._error

        return _fail


class SelectiveFailBackend:
    """Backend proxy that fails only the named methods; others return safe empties."""

    def __init__(
        self, failing: frozenset[str] | set[str], error: BaseException | None = None
    ) -> None:
        self._failing = set(failing)
        self._error = error or OSError("backend down")
        self.call_counts: dict[str, int] = {}

    def close(self) -> None:
        return None

    def get_all_cached_file_paths(self) -> set[str]:
        return set()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def _call(*args: Any, **kwargs: Any) -> Any:
            self.call_counts[name] = self.call_counts.get(name, 0) + 1
            if name in self._failing:
                raise self._error
            if name in {
                "get_aliases_for_canonical",
                "get_type_alias_details",
                "get_all_alias_mappings",
            }:
                return [] if name != "get_all_alias_mappings" else {}
            if name in {
                "get_canonical_for_alias",
                "get_type_alias_info",
                "load_cache",
                "load_file_cache",
            }:
                return None
            if name in {"save_cache", "save_file_cache", "save_type_aliases_batch"}:
                return True
            return None

        return _call


def _write_sample_cpp(temp_project_dir: Path) -> None:
    (temp_project_dir / "src" / "test.cpp").write_text("""
class TestClass {
public:
    void method();
};

void free_function() {}
""")


def _parse(result: Any) -> Any:
    if hasattr(result, "content"):
        text = result.content[0].text
    else:
        text = result[0].text
    return json.loads(text)


def _install_ctx(analyzer: Any) -> Any:
    original_analyzer = ctx.analyzer
    original_state = ctx.state_manager
    ctx.analyzer = analyzer
    ctx.state_manager = AnalyzerStateManager()
    ctx.state_manager.transition_to(AnalyzerState.INDEXED)

    def restore() -> None:
        ctx.analyzer = original_analyzer
        ctx.state_manager = original_state

    return restore


def _create_cache_manager(
    backend: Any,
    *,
    clock: FakeClock | None = None,
    **kwargs: Any,
) -> CacheManager:
    kwargs.setdefault("degradation_failure_threshold", 3)
    kwargs.setdefault("degradation_cooldown_seconds", 30.0)
    kwargs.setdefault("degradation_probe_interval_seconds", 5.0)
    if clock is not None:
        kwargs["clock"] = clock
    return CacheManager(
        project_root,
        backend=backend,
        recovery=ErrorTrackingAdapter(),
        **kwargs,
    )


class _HealthyBackend:
    """Minimal healthy backend used by the recovery scenario."""

    def close(self) -> None:
        return None

    def save_cache(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def save_file_cache(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def get_all_cached_file_paths(self) -> set[str]:
        return set()


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


# ---------------------------------------------------------------------------
# Scenario 1: total backend outage
# ---------------------------------------------------------------------------


@pytest.mark.error_handling
class TestScenario1TotalBackendOutage:
    """Every cache call raises: indexing still completes and tools stay valid."""

    def test_indexing_completes_and_error_summary_reports_failures(self, temp_project_dir):
        _write_sample_cpp(temp_project_dir)

        analyzer = CppAnalyzer(str(temp_project_dir))
        try:
            # Outage starts before indexing: every backend call raises.
            analyzer.cache_manager.backend = AlwaysFailBackend(OSError("backend down"))

            indexed_count = analyzer.index_project(force=True)
            assert indexed_count >= 1

            progress = analyzer.cache_manager.load_progress()
            assert progress is not None
            assert progress["status"] == "complete"
            assert progress["cache_persisted"] is False

            summary = analyzer.get_error_summary()
            assert summary["total_errors"] >= 1
            assert summary["last_error"] is not None
        finally:
            analyzer.close()

    def test_query_tools_return_valid_responses_under_outage(self, temp_project_dir):
        _write_sample_cpp(temp_project_dir)

        analyzer = CppAnalyzer(str(temp_project_dir))
        try:
            analyzer.index_project(force=True)
            failing = AlwaysFailBackend(OSError("backend down"))
            original = analyzer.cache_manager.backend
            analyzer.cache_manager.backend = failing

            classes = analyzer.search_classes("TestClass")
            assert isinstance(classes, list)
            assert any("TestClass" in str(c) for c in classes)

            info = analyzer.get_class_info("TestClass")
            assert info is None or isinstance(info, dict)

            sites = analyzer.get_call_sites("method")
            assert isinstance(sites, list)

            alias = analyzer.get_type_alias_info("Missing")
            assert isinstance(alias, dict)

            hierarchy = analyzer.get_class_hierarchy("TestClass")
            assert isinstance(hierarchy, dict)

            analyzer.cache_manager.backend = original
        finally:
            analyzer.close()

    @pytest.mark.asyncio
    async def test_mcp_tools_stay_alive_and_status_is_valid(self, temp_project_dir):
        from clang_index_mcp._mcp.tool_handlers.project_tools import (
            _handle_check_system_status,
        )
        from clang_index_mcp._mcp.tool_handlers.search_tools import (
            _handle_get_class_info,
            _handle_get_type_alias_info,
            _handle_search_classes,
        )

        _write_sample_cpp(temp_project_dir)
        analyzer = CppAnalyzer(str(temp_project_dir))
        try:
            analyzer.index_project(force=True)
            analyzer.cache_manager.backend = AlwaysFailBackend(OSError("backend down"))

            restore = _install_ctx(analyzer)
            try:
                status = _parse(await _handle_check_system_status({}))
                assert status["state"] in {"indexed", "indexing", "ready"}
                assert status["state"] != "error"

                search = _parse(await _handle_search_classes({"symbol_name": "TestClass"}))
                assert "isError" not in search or search.get("isError") is not True

                info = _parse(await _handle_get_class_info({"class_name": "TestClass"}))
                assert "isError" not in info or info.get("isError") is not True

                alias = _parse(await _handle_get_type_alias_info({"type_name": "Missing"}))
                assert alias.get("isError") is not True or alias.get("error")
            finally:
                restore()
        finally:
            analyzer.close()

    def test_short_circuit_logs_are_rate_limited(self, temp_project_dir):
        from clang_index_mcp._core import diagnostics

        clock = FakeClock()
        backend = AlwaysFailBackend(OSError("backend down"))
        cm = _create_cache_manager(backend, clock=clock)
        try:
            for _ in range(3):
                cm.get_canonical_for_alias("Foo")
            assert cm.degradation.is_degraded("get_canonical_for_alias")

            with patch.object(diagnostics, "warning") as mock_warning:
                for _ in range(50):
                    cm.get_canonical_for_alias("Foo")
                short_circuit_logs = [
                    call
                    for call in mock_warning.call_args_list
                    if "short-circuited" in str(call.args[0])
                ]
                assert len(short_circuit_logs) == 1

                clock.advance(30.0)
                for _ in range(50):
                    cm.get_canonical_for_alias("Foo")
                short_circuit_logs = [
                    call
                    for call in mock_warning.call_args_list
                    if "short-circuited" in str(call.args[0])
                ]
                assert len(short_circuit_logs) == 2
        finally:
            cm.close()


# ---------------------------------------------------------------------------
# Scenario 2: alias store down
# ---------------------------------------------------------------------------


@pytest.mark.error_handling
class TestScenario2AliasStoreDown:
    """Alias tools degrade honestly; core symbol tools stay unchanged."""

    ALIAS_OPS = frozenset(
        {
            "get_canonical_for_alias",
            "get_type_alias_info",
            "get_aliases_for_canonical",
            "get_type_alias_details",
            "get_all_alias_mappings",
        }
    )

    @pytest.mark.asyncio
    async def test_alias_tools_say_unavailable_not_not_found(self, temp_project_dir):
        from clang_index_mcp._mcp.tool_handlers.search_tools import (
            _handle_get_type_alias_info,
        )

        _write_sample_cpp(temp_project_dir)
        analyzer = CppAnalyzer(str(temp_project_dir))
        try:
            analyzer.index_project(force=True)
            backend = SelectiveFailBackend(self.ALIAS_OPS, OSError("alias store down"))
            analyzer.cache_manager.backend = backend

            restore = _install_ctx(analyzer)
            try:
                result = await _handle_get_type_alias_info({"type_name": "Missing"})
                payload = _parse(result)
                blob = json.dumps(payload).lower()
                assert "unavailable" in blob
                assert "not found" not in blob
                assert payload.get("isError") is True
                assert payload.get("error_type") == "alias_lookup_unavailable"
                assert payload.get("next_steps")
            finally:
                restore()
        finally:
            analyzer.close()

    @pytest.mark.asyncio
    async def test_core_symbol_tools_unchanged_by_alias_outage(self, temp_project_dir):
        from clang_index_mcp._mcp.tool_handlers.search_tools import (
            _handle_get_class_info,
            _handle_search_classes,
        )

        _write_sample_cpp(temp_project_dir)
        analyzer = CppAnalyzer(str(temp_project_dir))
        try:
            analyzer.index_project(force=True)
            analyzer.cache_manager.backend = SelectiveFailBackend(
                self.ALIAS_OPS, OSError("alias store down")
            )

            restore = _install_ctx(analyzer)
            try:
                search = _parse(await _handle_search_classes({"symbol_name": "TestClass"}))
                data = search.get("data", search)
                assert data, "core search must still return symbols"

                info = _parse(await _handle_get_class_info({"class_name": "TestClass"}))
                body = info.get("data", info)
                assert body.get("name") == "TestClass" or "TestClass" in json.dumps(body)
            finally:
                restore()
        finally:
            analyzer.close()

    def test_alias_empty_vs_unavailable_on_cache_manager(self, temp_project_dir):
        from clang_index_mcp._mcp.tool_handlers.resilience import consume_alias_degradation

        backend = SelectiveFailBackend(self.ALIAS_OPS, OSError("alias store down"))
        cm = _create_cache_manager(backend)
        try:
            assert cm.get_type_alias_info("Missing") is None
            assert consume_alias_degradation(cm) is True

            clean = SelectiveFailBackend(set())
            clean_cm = _create_cache_manager(clean)
            try:
                assert clean_cm.get_type_alias_info("Missing") is None
                assert consume_alias_degradation(clean_cm) is False
            finally:
                clean_cm.close()
        finally:
            cm.close()


# ---------------------------------------------------------------------------
# Scenario 3: disk-full on save_cache
# ---------------------------------------------------------------------------


@pytest.mark.error_handling
class TestScenario3DiskFullSaveCache:
    """ENOSPC on save preserves the cache file and does not poison queries."""

    def test_disk_full_preserves_cache_warns_and_next_run_rebuilds(self, temp_project_dir, mocker):
        _write_sample_cpp(temp_project_dir)

        from clang_index_mcp._core import diagnostics
        from clang_index_mcp._persistence.cache_manager import CacheManager as CM

        # First run: successful cache write.
        analyzer = CppAnalyzer(str(temp_project_dir))
        cache_file = analyzer.cache_manager.cache_dir / "symbols.db"
        try:
            analyzer.index_project(force=True)
            assert analyzer.cache_orchestrator.cache_persisted is True
            assert cache_file.exists()
            preserved_size = cache_file.stat().st_size
            assert preserved_size > 0
        finally:
            analyzer.close()

        # Second run: disk full on save_cache.
        save_calls: list[int] = []

        def disk_full_save(self, *args, **kwargs):
            save_calls.append(1)
            raise OSError(28, "No space left on device")

        mocker.patch.object(CM, "save_cache", disk_full_save)

        analyzer2 = CppAnalyzer(str(temp_project_dir))
        try:
            with patch.object(diagnostics, "warning") as mock_warning:
                analyzer2.index_project(force=True)

            assert save_calls, "save_cache must have been attempted"
            assert mock_warning.called, "disk-full save must log a warning"
            warning_text = " ".join(str(c.args[0]) for c in mock_warning.call_args_list)
            assert (
                "save_cache failed" in warning_text
                or "No space left" in warning_text
                or "resource" in warning_text.lower()
            )

            # Existing cache file is preserved (resource errors never clear it).
            assert cache_file.exists(), "disk-full must not delete the cache file"
            assert cache_file.stat().st_size >= preserved_size

            # In-memory queries still work.
            classes = analyzer2.search_classes("TestClass")
            assert any("TestClass" in str(c) for c in classes)

            progress = analyzer2.cache_manager.load_progress()
            assert progress is not None
            assert progress["status"] == "complete"
            assert progress["cache_persisted"] is False
        finally:
            analyzer2.close()

        # Next run after space is available rebuilds persistence.
        mocker.stopall()
        analyzer3 = CppAnalyzer(str(temp_project_dir))
        try:
            analyzer3.index_project(force=True)
            assert analyzer3.cache_orchestrator.cache_persisted is True
            assert cache_file.exists()
        finally:
            analyzer3.close()

    def test_disk_full_does_not_clear_cache_via_recovery(self, temp_project_dir):
        """Resource-class errors must never take the clear-cache last resort."""
        backend = Mock()
        backend.close = Mock()
        backend.save_cache = Mock(side_effect=OSError(28, "No space left on device"))
        cm = _create_cache_manager(backend)
        try:
            with patch.object(cm.recovery, "clear_cache") as mock_clear:
                result = cm.save_cache(
                    class_index={},
                    function_index={},
                    file_hashes={},
                    indexed_file_count=0,
                )
            assert result is False
            mock_clear.assert_not_called()
        finally:
            cm.close()


# ---------------------------------------------------------------------------
# Scenario 4: writer stress
# ---------------------------------------------------------------------------


@pytest.mark.error_handling
class TestScenario4WriterStress:
    """1000 consecutive write failures: thread alive, queue bounded, drops counted."""

    def test_1000_write_failures_keep_writer_alive_and_bounded(self):
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
        assert writer.start()

        accepted = 0
        for i in range(1000):
            if writer.enqueue(_request(i)):
                accepted += 1

        assert writer.is_alive, "writer thread must survive 1000 failures"

        writer.stop(timeout=30.0)
        assert not writer.is_alive

        stats = writer.get_stats()
        # Cumulative accepts during the storm are not just "queue bound + 1":
        # the writer concurrently dequeues (and fails) items, freeing slots
        # for new accepts until write-disabled engages. Bound is therefore
        # queue capacity + items consumable before disable + one race window
        # where enqueue passed the write_enabled check before disable landed.
        max_queue_size = 16
        disable_after = 5
        storm_bound = max_queue_size + disable_after + 2
        assert accepted <= storm_bound, (
            "accepted bounded by queue + pre-disable consumes + race window"
        )
        assert stats.queue_size <= max_queue_size
        assert stats.dropped_count >= 1000 - storm_bound
        assert stats.write_enabled is False
        assert stats.mode == "write_disabled"
        assert stats.failed_count >= 5
        assert stats.consecutive_failures >= 5

    def test_writer_stats_visible_on_error_summary(self):
        backend_cm = Mock()
        backend_cm.save_file_cache = Mock(side_effect=OSError("disk full"))
        backend_cm.close = Mock()
        backend_cm.backend = Mock()
        backend_cm.backend.get_all_cached_file_paths = Mock(return_value=set())

        writer = CacheWriterThread(
            lambda: backend_cm,
            max_queue_size=8,
            disable_after_failures=1,
            transient_max_attempts=1,
            sleep=lambda _s: None,
        )
        writer.start()
        writer.enqueue(_request(1))
        writer.stop(timeout=10.0)

        cm = _create_cache_manager(Mock(close=Mock()))
        try:
            cm.set_error_summary_extra_provider(writer.get_stats().as_dict)
            summary = cm.get_error_summary()
            assert summary["cache_writer"]["write_enabled"] is False
            assert summary["cache_writer"]["dropped_count"] >= 0
        finally:
            cm.close()


# ---------------------------------------------------------------------------
# Scenario 5: recovery
# ---------------------------------------------------------------------------


@pytest.mark.error_handling
class TestScenario5Recovery:
    """Backend heals -> probe returns to Normal; persistence resumes in-process."""

    def test_probe_returns_to_normal_and_persistence_resumes(self):
        clock = FakeClock()
        backend = AlwaysFailBackend(OSError("backend down"))
        cm = _create_cache_manager(backend, clock=clock)
        try:
            for _ in range(3):
                assert (
                    cm.save_cache(
                        class_index={},
                        function_index={},
                        file_hashes={},
                        indexed_file_count=0,
                    )
                    is False
                )
            assert cm.degradation.mode_for("save_cache") == "degraded"
            assert cm.degradation.admit("save_cache") is CallAdmission.SHORT_CIRCUIT

            # Backend heals after the cooldown.
            clock.advance(30.0)
            cm.backend = _HealthyBackend()

            # First post-cooldown call is the recovery probe and must succeed.
            result = cm.save_cache(
                class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
            )
            assert result is True
            assert cm.degradation.mode_for("save_cache") == "normal"
            assert cm.degradation.snapshot("save_cache").recovered_count >= 1

            # Persistence resumes without restart.
            assert (
                cm.save_cache(
                    class_index={}, function_index={}, file_hashes={}, indexed_file_count=1
                )
                is True
            )
        finally:
            cm.close()

    def test_read_and_write_recover_independently(self):
        clock = FakeClock()
        backend = SelectiveFailBackend({"save_file_cache", "save_cache"}, OSError("down"))
        cm = _create_cache_manager(backend, clock=clock)
        try:
            for _ in range(3):
                cm.save_file_cache("a.h", [], "h")
            assert cm.degradation.mode_for("save_file_cache") == "degraded"
            assert cm.degradation.mode_for("load_file_cache") == "normal"

            # Reads still pass through while writes are degraded.
            cm.load_file_cache("a.h", "h")
            assert backend.call_counts.get("load_file_cache", 0) >= 1

            # Heal writes; after cooldown the probe restores Normal.
            backend._failing.clear()
            clock.advance(30.0)
            assert cm.save_file_cache("a.h", [], "h") is True
            assert cm.degradation.mode_for("save_file_cache") == "normal"
        finally:
            cm.close()

    def test_degradation_reset_and_auto_recovery_counters(self):
        clock = FakeClock()
        mode = DegradationMode(
            failure_threshold=2,
            cooldown_seconds=10.0,
            probe_interval_seconds=1.0,
            clock=clock,
        )
        assert mode.note_failure("load_cache") is False
        assert mode.note_failure("load_cache") is True
        assert mode.is_degraded("load_cache")

        clock.advance(10.0)
        assert mode.admit("load_cache") is CallAdmission.PROBE
        mode.note_success("load_cache")
        assert mode.mode_for("load_cache") == "normal"
        snap = mode.snapshot("load_cache")
        assert snap.recovered_count == 1
        assert snap.entered_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
