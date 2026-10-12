"""Background per-file cache writer with bounded resilience.

`CacheWriterThread` serializes per-file cache writes on one background thread
that owns its own SQLite connection (see docs/ARCHITECTURE.md). The thread must
never die on a write exception, the queue must stay bounded, and sustained
backend failure must enter a write-disabled mode that can recover without a
process restart (epic clang_index_mcp-ent, child .8, REQ-6.7.x).
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .._core import diagnostics

# Thresholds are constructor-injectable so tests drive transitions without
# real sleeps (same seam as cache_manager retry policy / child .10).
DEFAULT_QUEUE_MAXSIZE = 256
DEFAULT_DISABLE_AFTER_FAILURES = 5
DEFAULT_COOLDOWN_SECONDS = 30.0
DEFAULT_PROBE_INTERVAL_SECONDS = 5.0
DEFAULT_GET_TIMEOUT_SECONDS = 0.1
DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 120.0

# Reuse the child .6 transient classification/backoff policy.
DEFAULT_TRANSIENT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE_SECONDS = 0.1
DEFAULT_BACKOFF_CAP_SECONDS = 1.0

_SHUTDOWN = object()


class SupportsSaveFileCache(Protocol):
    """Minimal cache-manager surface used by the writer."""

    def save_file_cache(self, *args: Any, **kwargs: Any) -> bool:
        """Persist one file's cache; returns success flag."""
        ...

    def close(self) -> Any:
        """Release the cache manager's resources."""
        ...


@dataclass
class CacheWriteRequest:
    """Per-file cache data handed off to the background writer thread."""

    file_path: str
    symbols: list[Any]
    file_hash: str
    compile_args_hash: str | None
    success: bool
    error_message: str | None
    retry_count: int


@dataclass
class CacheWriterStats:
    """Writer failure counters and mode state for the error-summary channel."""

    write_enabled: bool = True
    consecutive_failures: int = 0
    dropped_count: int = 0
    accepted_count: int = 0
    written_count: int = 0
    failed_count: int = 0
    queue_size: int = 0
    queue_maxsize: int = 0
    last_error: dict[str, Any] | None = None
    mode: str = "normal"

    def as_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for merging into get_error_summary."""
        return {
            "write_enabled": self.write_enabled,
            "mode": self.mode,
            "consecutive_failures": self.consecutive_failures,
            "dropped_count": self.dropped_count,
            "accepted_count": self.accepted_count,
            "written_count": self.written_count,
            "failed_count": self.failed_count,
            "queue_size": self.queue_size,
            "queue_maxsize": self.queue_maxsize,
            "last_error": dict(self.last_error) if self.last_error else None,
        }


@dataclass
class _WriterCounters:
    """Mutable writer counters guarded by the writer lock."""

    consecutive_failures: int = 0
    dropped_count: int = 0
    accepted_count: int = 0
    written_count: int = 0
    failed_count: int = 0
    write_enabled: bool = True
    disabled_at: float | None = None
    last_log_at: float | None = None
    last_probe_at: float | None = None
    last_error: dict[str, Any] | None = None
    stop_requested: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class CacheWriterThread:
    """Never-die background writer with bounded queue and write-disabled mode.

    Producers call :meth:`enqueue`. The background thread owns a private cache
    connection and persists requests. After ``disable_after_failures``
    consecutive failures the writer stops accepting work (drops are counted),
    logs at most once per cooldown, and periodically probes the backend to
    re-enable writes without a restart.
    """

    def __init__(
        self,
        cache_manager_factory: Callable[[], SupportsSaveFileCache],
        *,
        max_queue_size: int = DEFAULT_QUEUE_MAXSIZE,
        disable_after_failures: int = DEFAULT_DISABLE_AFTER_FAILURES,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        probe_interval_seconds: float = DEFAULT_PROBE_INTERVAL_SECONDS,
        transient_max_attempts: int = DEFAULT_TRANSIENT_MAX_ATTEMPTS,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        backoff_cap_seconds: float = DEFAULT_BACKOFF_CAP_SECONDS,
        get_timeout_seconds: float = DEFAULT_GET_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        error_recorder: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self._cache_manager_factory = cache_manager_factory
        self._max_queue_size = max(1, max_queue_size)
        self._disable_after_failures = max(1, disable_after_failures)
        self._cooldown_seconds = max(0.0, cooldown_seconds)
        self._probe_interval_seconds = max(0.0, probe_interval_seconds)
        self._transient_max_attempts = max(1, transient_max_attempts)
        self._backoff_base_seconds = backoff_base_seconds
        self._backoff_cap_seconds = backoff_cap_seconds
        self._get_timeout_seconds = get_timeout_seconds
        self._clock = clock
        self._sleep = sleep
        self._error_recorder = error_recorder

        self._lock = threading.RLock()
        self._counters = _WriterCounters()
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=self._max_queue_size)
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_alive(self) -> bool:
        """True when the background thread has been started and is running."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    def is_write_enabled(self) -> bool:
        """Producers check this flag before enqueueing (write-disabled mode)."""
        with self._lock:
            return self._counters.write_enabled

    def get_stats(self) -> CacheWriterStats:
        """Return a snapshot of failure counters and mode state."""
        with self._lock:
            c = self._counters
            return CacheWriterStats(
                write_enabled=c.write_enabled,
                consecutive_failures=c.consecutive_failures,
                dropped_count=c.dropped_count,
                accepted_count=c.accepted_count,
                written_count=c.written_count,
                failed_count=c.failed_count,
                queue_size=self._queue.qsize(),
                queue_maxsize=self._max_queue_size,
                last_error=dict(c.last_error) if c.last_error else None,
                mode="normal" if c.write_enabled else "write_disabled",
            )

    def enqueue(self, request: CacheWriteRequest) -> bool:
        """Accept a write request, or drop-and-count when disabled/full.

        Returns True when the request was accepted onto the bounded queue.
        """
        with self._lock:
            if self._counters.stop_requested:
                self._counters.dropped_count += 1
                return False
            if not self._counters.write_enabled:
                self._counters.dropped_count += 1
                self._log_rate_limited(
                    "Cache writer is write-disabled; dropping enqueue",
                )
                return False

        try:
            self._queue.put_nowait(request)
        except queue.Full:
            with self._lock:
                self._counters.dropped_count += 1
                self._log_rate_limited(
                    "Cache writer queue is full; dropping enqueue",
                )
            return False

        with self._lock:
            self._counters.accepted_count += 1
        return True

    def start(self) -> bool:
        """Start the background thread. Returns False if already running."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._counters.stop_requested = False
            thread = threading.Thread(
                target=self._run,
                name="CacheWriter",
                daemon=True,
            )
            self._thread = thread
        thread.start()
        return True

    def stop(self, timeout: float = DEFAULT_SHUTDOWN_TIMEOUT_SECONDS) -> bool:
        """Drain remaining work and stop the thread. Returns True on clean stop."""
        with self._lock:
            self._counters.stop_requested = True
            thread = self._thread
            self._thread = None
        if thread is None:
            return True
        self._put_shutdown_sentinel()
        thread.join(timeout=timeout)
        if thread.is_alive():
            diagnostics.warning("Background cache writer did not finish within timeout")
            return False
        return True

    def _put_shutdown_sentinel(self) -> None:
        """Enqueue the shutdown marker even when the bounded queue is full."""
        try:
            self._queue.put_nowait(_SHUTDOWN)
            return
        except queue.Full:
            pass
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(_SHUTDOWN)
        except queue.Full:
            diagnostics.warning("Cache writer shutdown sentinel dropped (queue full)")

    def try_recover(self, cache_manager: Any | None = None) -> bool:
        """Probe the backend and re-enable writes when it is healthy again.

        Callable from the child .10 degradation state machine. Safe to call
        concurrently; rate-limited by ``probe_interval_seconds``.
        """
        with self._lock:
            if self._counters.write_enabled:
                return True
            now = self._clock()
            last = self._counters.last_probe_at
            if last is not None and (now - last) < self._probe_interval_seconds:
                return False
            self._counters.last_probe_at = now

        probe_cm = cache_manager
        if probe_cm is None:
            try:
                probe_cm = self._cache_manager_factory()
            except Exception as e:
                self._log_rate_limited(f"Cache writer probe could not open backend: {e}")
                return False

        if not self._probe_backend(probe_cm):
            self._log_rate_limited("Cache writer probe failed; writes remain disabled")
            return False

        with self._lock:
            self._counters.write_enabled = True
            self._counters.consecutive_failures = 0
            self._counters.disabled_at = None
        diagnostics.info("Cache writer re-enabled after successful backend probe")
        return True

    # ------------------------------------------------------------------
    # Writer loop (never dies)
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Outer guard: the thread survives any exception from the loop body."""
        cache_manager: Any | None = self._open_cache_manager()
        try:
            while True:
                try:
                    keep_going, cache_manager = self._tick(cache_manager)
                    if not keep_going:
                        break
                except Exception as e:
                    # Outer loop guard: 1000 consecutive failures must not kill us.
                    diagnostics.error(f"Cache writer loop error (continuing): {e}")
                    self._note_failure(e, file_path=None)
        finally:
            self._close_quietly(cache_manager)

    def _tick(self, cache_manager: Any) -> tuple[bool, Any]:
        """One loop iteration. Returns (continue_flag, current_cache_manager)."""
        if cache_manager is None:
            cache_manager = self._open_cache_manager()
        item = self._get_next_item()
        if item is None:
            if cache_manager is not None:
                self.try_recover(cache_manager)
            else:
                self._sleep(self._get_timeout_seconds)
            return True, cache_manager
        if item is _SHUTDOWN:
            self._drain_remaining(cache_manager)
            return False, cache_manager
        if cache_manager is None or not self._prepare_for_write(cache_manager):
            with self._lock:
                self._counters.dropped_count += 1
            return True, cache_manager
        self._process_item(cache_manager, item)
        return True, cache_manager

    def _prepare_for_write(self, cache_manager: Any) -> bool:
        """Attempt recovery when disabled; True when a write may proceed."""
        if self.is_write_enabled():
            return True
        self.try_recover(cache_manager)
        return self.is_write_enabled()

    def _get_next_item(self) -> Any | None:
        try:
            return self._queue.get(timeout=self._get_timeout_seconds)
        except queue.Empty:
            return None

    def _open_cache_manager(self) -> Any | None:
        try:
            return self._cache_manager_factory()
        except Exception as e:
            with self._lock:
                self._counters.write_enabled = False
                if self._counters.disabled_at is None:
                    self._counters.disabled_at = self._clock()
                    self._counters.consecutive_failures += 1
                    self._counters.failed_count += 1
            self._log_rate_limited(f"Background cache writer failed to initialize: {e}")
            return None

    def _process_item(self, cache_manager: Any, item: CacheWriteRequest) -> None:
        """Persist one request; never raises."""
        try:
            ok = self._save_with_retry(cache_manager, item)
        except Exception as e:
            self._note_failure(e, file_path=item.file_path)
            return
        if not ok:
            self._note_failure(
                Exception("save_file_cache returned False"),
                file_path=item.file_path,
            )
            return
        self._note_success()

    def _save_with_retry(self, cache_manager: Any, item: CacheWriteRequest) -> bool:
        """Bounded transient retry with backoff (child .6 policy)."""
        from .._persistence.cache_manager import classify_backend_error

        last_error: Exception | None = None
        for attempt in range(self._transient_max_attempts):
            try:
                return bool(
                    cache_manager.save_file_cache(
                        item.file_path,
                        item.symbols,
                        item.file_hash,
                        item.compile_args_hash,
                        item.success,
                        item.error_message,
                        item.retry_count,
                    )
                )
            except Exception as e:
                last_error = e
                if classify_backend_error(e) != "transient":
                    break
                if attempt + 1 < self._transient_max_attempts:
                    self._sleep(self._backoff_delay(attempt + 1))
        if last_error is not None:
            raise last_error
        return False

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff delay for a 1-based retry attempt number."""
        delay = self._backoff_base_seconds * float(2 ** (attempt - 1))
        return float(min(delay, self._backoff_cap_seconds))

    def _drain_remaining(self, cache_manager: Any) -> None:
        """Best-effort drain after shutdown signal; remaining items are dropped."""
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
            if item is _SHUTDOWN:
                continue
            if cache_manager is None or not self.is_write_enabled():
                with self._lock:
                    self._counters.dropped_count += 1
                continue
            self._process_item(cache_manager, item)

    def _probe_backend(self, cache_manager: Any) -> bool:
        """Cheap backend read probe (child .10 style)."""
        try:
            backend = getattr(cache_manager, "backend", None)
            if backend is None:
                return False
            backend.get_all_cached_file_paths()
            return True
        except Exception:
            return False

    def _close_quietly(self, cache_manager: Any) -> None:
        if cache_manager is None:
            return
        try:
            cache_manager.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Counters, mode transitions, rate-limited logging
    # ------------------------------------------------------------------

    def _note_success(self) -> None:
        with self._lock:
            self._counters.written_count += 1
            self._counters.consecutive_failures = 0
            self._counters.last_error = None

    def _note_failure(self, error: Exception, file_path: str | None) -> None:
        error_state = {
            "operation": "save_file_cache",
            "error_type": type(error).__name__,
            "message": str(error),
            "timestamp": self._clock(),
            "file_path": file_path,
        }
        entered_disabled = False
        with self._lock:
            self._counters.failed_count += 1
            self._counters.consecutive_failures += 1
            self._counters.last_error = error_state
            if (
                self._counters.write_enabled
                and self._counters.consecutive_failures >= self._disable_after_failures
            ):
                self._counters.write_enabled = False
                self._counters.disabled_at = self._clock()
                entered_disabled = True

        self._report_error(error_state)
        if entered_disabled:
            diagnostics.error(
                "Cache writer entered write-disabled mode after "
                f"{self._disable_after_failures} consecutive failures "
                f"(last: {error_state['error_type']}: {error_state['message']})"
            )

    def _report_error(self, error_state: dict[str, Any]) -> None:
        recorder = self._error_recorder
        if recorder is None:
            return
        try:
            recorder(
                error_state.get("error_type", "Error"),
                error_state.get("message", ""),
                error_state.get("operation", "save_file_cache"),
            )
        except Exception:
            # Reporting must never break the writer.
            pass

    def _log_rate_limited(self, message: str) -> None:
        """Log at most once per cooldown while degraded. Reentrant-lock safe."""
        with self._lock:
            now = self._clock()
            last = self._counters.last_log_at
            if last is not None and (now - last) < self._cooldown_seconds:
                return
            self._counters.last_log_at = now
        diagnostics.warning(message)
