"""Cache management for C++ analyzer."""

import errno
import json
import sqlite3
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal, Optional, TypeVar

from .._indexing.ports.cache_backend import CacheBackend
from .._persistence.cache_validation_context import CacheValidationContext
from .._persistence.outcome import BackendOutcome
from .._persistence.project_identity import ProjectIdentity
from .._symbols.model import SymbolInfo
from .._symbols.ports.parser import TypeAliasRecord
from .error_tracking_adapter import ErrorTrackingAdapter

T = TypeVar("T")

if TYPE_CHECKING:
    from .._persistence.ports.recovery import CacheRecoveryPort

# Handle both package and script imports
try:
    from .._core import diagnostics
except ImportError:
    import diagnostics  # type: ignore[no-redef]

ErrorClass = Literal["transient", "resource", "corruption", "other"]

# Transient retry defaults (REQ-6.7.3 / REQ-9.4.5). Constructor-injectable so
# tests and child .10 can override without patching module state.
DEFAULT_TRANSIENT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE_SECONDS = 0.1
DEFAULT_BACKOFF_CAP_SECONDS = 1.0

_TRANSIENT_SQLITE_MARKERS = ("database is locked", "database is busy", "database table is locked")
_CORRUPTION_MARKERS = ("corrupt", "malformed")
_NETWORK_TIMEOUT_ERRNOS = frozenset(
    {errno.ETIMEDOUT, getattr(errno, "ENETUNREACH", None), getattr(errno, "EHOSTUNREACH", None)}
    - {None}
)


def classify_backend_error(error: BaseException) -> ErrorClass:
    """Classify a backend error per REQ-6.7.3.

    Order matters: OperationalError is a DatabaseError subclass and
    TimeoutError is an OSError subclass, so transient markers are checked
    before corruption and resource.
    """
    message = str(error).lower()

    if isinstance(error, sqlite3.OperationalError) and any(
        marker in message for marker in _TRANSIENT_SQLITE_MARKERS
    ):
        return "transient"
    if isinstance(error, TimeoutError):
        return "transient"
    if isinstance(error, OSError) and error.errno in _NETWORK_TIMEOUT_ERRNOS:
        return "transient"
    if isinstance(error, OSError) and "timed out" in message:
        return "transient"

    if isinstance(error, sqlite3.DatabaseError) and any(
        marker in message for marker in _CORRUPTION_MARKERS
    ):
        return "corruption"

    if isinstance(error, (PermissionError, OSError)):
        return "resource"

    return "other"


class CacheManager:
    """Manages caching for the C++ analyzer with pluggable backends."""

    #: Extra attempts after a successful recovery (REQ-6.8.5). Epic child ent.6
    #: can override this to plug in classification/backoff without redesigning
    #: the wrapper.
    _max_retries_after_recovery: int = 1

    transient_max_attempts: int
    backoff_base_seconds: float
    backoff_cap_seconds: float

    def __init__(
        self,
        project_root_or_identity: Path | ProjectIdentity,
        skip_schema_recreation: bool = False,
        backend: CacheBackend | None = None,
        recovery: Optional["CacheRecoveryPort"] = None,
        transient_max_attempts: int = DEFAULT_TRANSIENT_MAX_ATTEMPTS,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        backoff_cap_seconds: float = DEFAULT_BACKOFF_CAP_SECONDS,
    ):
        """
        Initialize CacheManager with project identity.

        Args:
            project_root_or_identity: Either a Path (backward compatibility) or ProjectIdentity
            skip_schema_recreation: If True, skip database recreation on schema mismatch.
                                   Used by worker processes to avoid race conditions.
            backend: Optional pre-built cache backend. If None, a SqliteCacheBackend
                    is created internally (backward compatibility).
            recovery: Optional pre-built recovery/error-tracking adapter. If None,
                     an ErrorTrackingAdapter is created internally.
            transient_max_attempts: Total attempts for transient errors (REQ-6.7.3),
                    including the first call. Must be >= 1.
            backoff_base_seconds: Base delay for exponential backoff between
                    transient retries.
            backoff_cap_seconds: Upper bound for a single backoff delay.

        Backward Compatibility:
            Accepts Path for backward compatibility, automatically creates ProjectIdentity
            with no config file.
        """
        self.project_root, self.project_identity = self._resolve_project_identity(
            project_root_or_identity
        )
        self._skip_schema_recreation = skip_schema_recreation
        self.transient_max_attempts = max(1, transient_max_attempts)
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_cap_seconds = backoff_cap_seconds
        self.cache_dir = self._ensure_cache_dir()
        self.error_log_path = self.cache_dir / "parse_errors.jsonl"
        self.recovery = self._init_recovery(recovery)
        self.backend = backend if backend is not None else self._create_backend()

    @staticmethod
    def _resolve_project_identity(
        project_root_or_identity: Path | ProjectIdentity,
    ) -> tuple[Path, ProjectIdentity]:
        """Normalize constructor input into (project_root, project_identity)."""
        if isinstance(project_root_or_identity, ProjectIdentity):
            return project_root_or_identity.source_directory, project_root_or_identity
        project_root = Path(project_root_or_identity)
        return project_root, ProjectIdentity(project_root, None)

    def _ensure_cache_dir(self) -> Path:
        """Compute and create the cache directory for this project."""
        cache_dir = self._get_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    @staticmethod
    def _init_recovery(recovery: Optional["CacheRecoveryPort"]) -> "CacheRecoveryPort":
        """Return the injected recovery adapter or create a default one."""
        return recovery or ErrorTrackingAdapter()

    @staticmethod
    def compute_cache_dir(project_identity: ProjectIdentity) -> Path:
        """Compute the cache directory for a project identity."""
        import os

        # MCP_CACHE_BASE_DIR takes precedence; CLANG_INDEX_CACHE_DIR is the
        # legacy/user-facing alias and is honored when the newer variable is unset.
        env_base = os.environ.get("MCP_CACHE_BASE_DIR") or os.environ.get("CLANG_INDEX_CACHE_DIR")
        if env_base:
            cache_base = Path(env_base)
        else:
            clang_index_mcp_root = Path(
                __file__
            ).parent.parent  # Go up from cache_manager.py to package root
            cache_base = clang_index_mcp_root / ".mcp_cache"
        cache_dir_name = project_identity.get_cache_directory_name()
        return cache_base / cache_dir_name

    def _get_cache_dir(self) -> Path:
        """
        Get the cache directory for this project.

        Uses ProjectIdentity to create unique cache directory based on:
        - Source directory path
        - Configuration file path (if provided)

        Returns:
            Path to cache directory
        """
        return CacheManager.compute_cache_dir(self.project_identity)

    def cache_exists(self) -> bool:
        """
        Check if cache directory exists for this project.

        Returns:
            True if cache directory exists, False otherwise
        """
        return self.cache_dir.exists()

    def _create_backend(self) -> CacheBackend:
        """
        Create SQLite cache backend.

        Returns:
            SqliteCacheBackend instance

        Raises:
            Exception if SQLite backend initialization fails
        """
        from .._persistence.sqlite_cache_backend import SqliteCacheBackend

        db_path = self.cache_dir / "symbols.db"
        backend = SqliteCacheBackend(db_path, skip_schema_recreation=self._skip_schema_recreation)
        diagnostics.debug(f"Using SQLite cache backend: {db_path}")
        return backend

    def ensure_schema_current(self) -> bool:
        """
        Ensure database schema is current before spawning workers.

        This should be called by main process BEFORE creating ProcessPoolExecutor
        to prevent race conditions where multiple workers detect schema mismatch
        and try to recreate the database simultaneously.

        Returns:
            True if schema was recreated, False if it was already current or
            the check failed (best-effort; failure is marked degraded).
        """
        outcome = self._safe_backend_call(
            "ensure_schema_current", lambda: self.backend.ensure_schema_current()
        )
        return self._map_outcome("ensure_schema_current", outcome, False)

    def close(self):
        """
        Close the cache manager and release all resources.

        This should be called when the CacheManager is no longer needed
        to properly close the database connection and avoid resource leaks.
        """
        # Lifecycle teardown, not a cache entry point (REQ-6.8.7 covers cache
        # ops). Use getattr so GC/shutdown never raises and the AST routing
        # meta-test only has to reason about cache backend calls.
        backend = getattr(self, "backend", None)
        if backend is not None:
            try:
                backend.close()
            except Exception:
                pass

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False

    def __del__(self):
        """Destructor to ensure resources are released on garbage collection."""
        # During Python shutdown, modules may be None. Suppress all errors.
        try:
            # Check if we're shutting down - skip cleanup if so
            if sys is None or sys.meta_path is None:
                return
            self.close()
        except (ImportError, AttributeError, TypeError):
            # Suppress errors during shutdown - resources will be cleaned up by OS
            pass

    def _handle_backend_error(self, error: Exception, operation: str) -> bool:
        """
        Classify a backend error and apply the REQ-6.7.3 recovery policy.

        Policy:
            - transient: record only; bounded backoff retry is the caller's job.
            - resource (PermissionError/OSError/ENOSPC): record and fail fast.
              NEVER clear the cache (REQ-6.7.2 / REQ-9.4.1).
            - corruption: backup + repair/rebuild via ``_attempt_recovery``, then
              the caller retries once (REQ-6.7.3 / REQ-9.3.4).

        Returns:
            True only when recovery succeeded and the operation may be retried.

        Never raises: error tracking or recovery failures are swallowed so the
        wrapper contract holds even if the recovery port misbehaves.
        """
        try:
            error_class = classify_backend_error(error)
            error_type = type(error).__name__
            error_message = str(error)
            recoverable = error_class in ("transient", "other")

            self.recovery.record_error(
                error_type, error_message, operation, recoverable=recoverable
            )

            if error_class == "corruption":
                recovery_succeeded = self._attempt_recovery(error, operation)
                self.record_recovery_outcome(
                    operation, attempted=True, succeeded=recovery_succeeded
                )
                return recovery_succeeded

            if error_class == "resource":
                diagnostics.error(
                    f"Resource error in {operation} — cache preserved, no retry: "
                    f"{error_type}: {error_message}"
                )
                return False

            return False
        except Exception as handling_error:
            diagnostics.error(
                f"Error handling failed in {operation}: "
                f"{type(handling_error).__name__}: {handling_error}"
            )
            return False

    def _attempt_recovery(self, error: Exception, operation: str) -> bool:
        """
        Attempt non-destructive recovery from a critical (corruption) error.

        Corrupt cache (REQ-6.7.3 / REQ-9.3.4):
            1. forensic backup via ``recovery.backup_database``
            2. ``recovery.attempt_repair`` (dump/restore rebuild)
            3. last resort ONLY when repair failed — i.e. the database is
               unreadable beyond repair (integrity check and data dump both
               failed): clear the live cache so a fresh one can be built.
               This path is never taken for resource errors (PermissionError /
               OSError / ENOSPC), which always preserve the cache (REQ-6.7.2).

        Returns:
            True if recovery succeeded and the backend is ready for a retry.

        Never raises.
        """
        try:
            if classify_backend_error(error) != "corruption":
                # Resource and other classes must not destroy the cache.
                return False

            diagnostics.warning(f"Attempting recovery from {type(error).__name__} in {operation}")
            diagnostics.info("Database corruption detected, attempting repair...")

            db_path = self.cache_dir / "symbols.db"
            backup_path = self.recovery.backup_database(db_path)
            if not backup_path:
                diagnostics.error("Failed to create backup before repair")
                return False

            if self.recovery.attempt_repair(db_path):
                diagnostics.info("Database repair successful")
                return self._reconnect_backend(db_path)

            diagnostics.error("Database repair failed")
            # LAST RESORT (documented condition): attempt_repair returned False,
            # meaning PRAGMA integrity_check failed AND the dump-and-rebuild path
            # failed — the cache is unreadable beyond repair. Clearing lets a
            # fresh cache be rebuilt; the forensic backup above is left for
            # inspection. Never used for resource errors.
            diagnostics.warning(
                "Cache unreadable beyond repair; clearing as last resort "
                f"({operation}, backup at {backup_path})"
            )
            if self.recovery.clear_cache(self.cache_dir):
                diagnostics.info("Cache cleared successfully")
                return self._reconnect_backend(db_path)
            diagnostics.error("Failed to clear cache")
            return False
        except Exception as recovery_error:
            diagnostics.error(
                f"Recovery attempt failed in {operation}: "
                f"{type(recovery_error).__name__}: {recovery_error}"
            )
            return False

    def _reconnect_backend(self, db_path: Path) -> bool:
        """Rebuild the backend handle against ``db_path`` after repair/clear."""
        try:
            from .._persistence.sqlite_cache_backend import SqliteCacheBackend

            self.backend = SqliteCacheBackend(db_path)
            return True
        except Exception as e:
            diagnostics.error(f"Failed to reconnect after repair: {e}")
            return False

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff delay for a 1-based retry attempt number."""
        delay = self.backoff_base_seconds * float(2 ** (attempt - 1))
        return float(min(delay, self.backoff_cap_seconds))

    def _retry_with_backoff(
        self,
        operation: str,
        func: Callable[..., T],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        last_error: Exception,
    ) -> BackendOutcome[T]:
        """Retry a transient failure with bounded exponential backoff (REQ-6.7.3)."""
        last = last_error
        remaining = self.transient_max_attempts - 1
        for attempt in range(1, remaining + 1):
            try:
                time.sleep(self._backoff_delay(attempt))
            except Exception:
                pass
            try:
                result = func(*args, **kwargs)
                self.recovery.record_operation(operation)
                return BackendOutcome(value=result)
            except Exception as retry_error:
                diagnostics.warning(
                    f"Transient retry {attempt}/{remaining} failed in {operation}: "
                    f"{type(retry_error).__name__}: {retry_error}"
                )
                last = retry_error
                if classify_backend_error(retry_error) != "transient":
                    break
        return BackendOutcome(error=last)

    def _map_outcome(
        self,
        operation: str,
        outcome: BackendOutcome[T],
        default: T,
        *,
        log_note: str | None = None,
    ) -> T:
        """Map a backend outcome to a typed safe value (REQ-6.8.4).

        On failure, mark the operation degraded through the error-state channel
        so callers can distinguish "empty" from "unavailable" (REQ-6.8.6), then
        return ``default``. On success, return the backend value, folding a
        legitimate None into ``default`` for methods whose declared type
        excludes None.
        """
        if outcome.ok and outcome.value is not None:
            return outcome.value
        if not outcome.ok:
            self.mark_degraded(operation)
            if log_note is not None and outcome.error is not None:
                diagnostics.warning(f"{log_note}: {type(outcome.error).__name__}: {outcome.error}")
        return default

    def _safe_backend_call(
        self,
        operation: str,
        func: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> BackendOutcome[T]:
        """
        Safely call a backend method with error tracking, recovery, and retry.

        Never raises and never returns bare None. Success is reported as
        ``BackendOutcome(value=...)`` (value may legitimately be None for
        "not found"); failure is reported as ``BackendOutcome(error=...)``.
        After a successful recovery the call is retried once (REQ-6.8.5);
        ``recovered`` is True only when that retried call succeeds.

        Args:
            operation: Operation name for tracking
            func: Backend method to call
            *args, **kwargs: Arguments to pass to method

        Returns:
            BackendOutcome carrying either the backend value or the error.
        """
        try:
            self.recovery.record_operation(operation)
            result = func(*args, **kwargs)
            return BackendOutcome(value=result)
        except Exception as error:
            return self._resolve_backend_failure(operation, func, args, kwargs, error)

    def _resolve_backend_failure(
        self,
        operation: str,
        func: Callable[..., T],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        error: Exception,
    ) -> BackendOutcome[T]:
        """Handle a failed backend call without ever raising (REQ-6.8.5 / REQ-6.7.3)."""
        diagnostics.error(f"Backend error in {operation}: {type(error).__name__}: {error}")
        error_class = classify_backend_error(error)

        try:
            recovery_succeeded = self._handle_backend_error(error, operation)
        except Exception as handling_error:
            diagnostics.error(
                f"Error handling failed in {operation}: "
                f"{type(handling_error).__name__}: {handling_error}"
            )
            return BackendOutcome(error=error)

        if error_class == "transient":
            return self._retry_with_backoff(operation, func, args, kwargs, error)

        if recovery_succeeded and self._max_retries_after_recovery > 0:
            try:
                retried = func(*args, **kwargs)
                return BackendOutcome(value=retried, recovered=True)
            except Exception as retry_error:
                diagnostics.error(
                    f"Retry after recovery failed in {operation}: "
                    f"{type(retry_error).__name__}: {retry_error}"
                )
                return BackendOutcome(error=retry_error)

        return BackendOutcome(error=error)

    def get_file_hash(self, file_path: str) -> str:
        """Calculate hash of a file using chunked reads."""
        from .._core.file_utils import hash_file

        return hash_file(file_path)

    def save_cache(
        self,
        class_index: dict[str, list[SymbolInfo]],
        function_index: dict[str, list[SymbolInfo]],
        file_hashes: dict[str, str],
        indexed_file_count: int,
        include_dependencies: bool = False,
        config_file_path: Path | None = None,
        config_file_mtime: float | None = None,
        compile_commands_path: Path | None = None,
        compile_commands_mtime: float | None = None,
        validation_context: CacheValidationContext | None = None,
    ) -> bool:
        """Save indexes to cache file with configuration metadata"""
        if validation_context is not None:
            config_file_path = validation_context.config_file_path
            config_file_mtime = validation_context.config_file_mtime
            compile_commands_path = validation_context.compile_commands_path
            compile_commands_mtime = validation_context.compile_commands_mtime
        outcome = self._safe_backend_call(
            "save_cache",
            lambda: self.backend.save_cache(
                class_index,
                function_index,
                file_hashes,
                indexed_file_count,
                include_dependencies,
                config_file_path,
                config_file_mtime,
                compile_commands_path,
                compile_commands_mtime,
            ),
        )
        return self._map_outcome("save_cache", outcome, False)

    def load_cache(
        self,
        include_dependencies: bool = False,
        config_file_path: Path | None = None,
        config_file_mtime: float | None = None,
        compile_commands_path: Path | None = None,
        compile_commands_mtime: float | None = None,
        validation_context: CacheValidationContext | None = None,
    ) -> dict[str, Any] | None:
        """Load cache if it exists and is valid, checking for configuration changes"""
        if validation_context is not None:
            config_file_path = validation_context.config_file_path
            config_file_mtime = validation_context.config_file_mtime
            compile_commands_path = validation_context.compile_commands_path
            compile_commands_mtime = validation_context.compile_commands_mtime
        outcome = self._safe_backend_call(
            "load_cache",
            lambda: self.backend.load_cache(
                include_dependencies,
                config_file_path,
                config_file_mtime,
                compile_commands_path,
                compile_commands_mtime,
            ),
        )
        # Error and genuine miss converge to the same safe action: full re-parse.
        return self._map_outcome(
            "load_cache",
            outcome,
            None,
            log_note="load_cache failed; treating as cache miss",
        )

    def save_file_cache(
        self,
        file_path: str,
        symbols: list[SymbolInfo],
        file_hash: str,
        compile_args_hash: str | None = None,
        success: bool = True,
        error_message: str | None = None,
        retry_count: int = 0,
    ) -> bool:
        """Save parsed symbols for a single file with compilation arguments hash"""
        outcome = self._safe_backend_call(
            "save_file_cache",
            lambda: self.backend.save_file_cache(
                file_path,
                symbols,
                file_hash,
                compile_args_hash,
                success,
                error_message,
                retry_count,
            ),
        )
        return self._map_outcome("save_file_cache", outcome, False)

    def load_file_cache(
        self, file_path: str, current_hash: str, compile_args_hash: str | None = None
    ) -> dict[str, Any] | None:
        """Load cached data for a file if hash matches"""
        outcome = self._safe_backend_call(
            "load_file_cache",
            lambda: self.backend.load_file_cache(file_path, current_hash, compile_args_hash),
        )
        # Error and genuine miss converge to the same safe action: re-parse.
        return self._map_outcome(
            "load_file_cache",
            outcome,
            None,
            log_note="load_file_cache failed; treating as cache miss",
        )

    def remove_file_cache(self, file_path: str) -> bool:
        """Remove cached data for a deleted file"""
        outcome = self._safe_backend_call(
            "remove_file_cache", lambda: self.backend.remove_file_cache(file_path)
        )
        return self._map_outcome("remove_file_cache", outcome, False)

    def save_progress(
        self,
        total_files: int,
        indexed_files: int,
        failed_files: int,
        cache_hits: int,
        last_index_time: float,
        class_count: int,
        function_count: int,
        status: str = "in_progress",
    ):
        """Save indexing progress"""
        try:
            progress_file = self.cache_dir / "indexing_progress.json"
            progress_data = {
                "project_root": str(self.project_root),
                "total_files": total_files,
                "indexed_files": indexed_files,
                "failed_files": failed_files,
                "cache_hits": cache_hits,
                "last_index_time": last_index_time,
                "timestamp": time.time(),
                "class_count": class_count,
                "function_count": function_count,
                "status": status,
            }

            with open(progress_file, "w") as f:
                json.dump(progress_data, f, indent=2)
        except Exception:
            pass  # Silently fail for progress tracking

    def load_progress(self) -> dict[str, Any] | None:
        """Load indexing progress if available"""
        try:
            progress_file = self.cache_dir / "indexing_progress.json"
            if not progress_file.exists():
                return None

            with open(progress_file, "r") as f:
                data: dict[str, Any] = json.load(f)
                return data
        except Exception:
            return None

    def get_error_summary(self) -> dict[str, Any]:
        """
        Get summary of cache errors and health status.

        Returns:
            Dict with error statistics
        """
        # Get error tracker summary for cache backend errors
        tracker_summary = self.recovery.get_error_summary()

        # Also include parse errors from the JSONL log
        parse_errors = self.get_parse_errors()

        # Count unique files and error types from parse errors
        unique_files: set[str] = set()
        error_types: dict[str, int] = {}
        for error in parse_errors:
            unique_files.add(error["file_path"])
            error_type = error.get("error_type", "Unknown")
            error_types[error_type] = error_types.get(error_type, 0) + 1

        # Combine both sources
        summary = tracker_summary.copy()
        summary["backend_type"] = "sqlite"
        summary["total_errors"] = tracker_summary["total_errors"] + len(parse_errors)
        summary["unique_files"] = len(unique_files)
        summary["error_types"] = error_types

        return summary

    def reset_error_tracking(self):
        """Reset error tracking state (useful for testing)."""
        self.recovery.reset()

    # ------------------------------------------------------------------
    # Error-state channel (REQ-6.8.6): empty vs degraded distinction
    # ------------------------------------------------------------------

    def _channel_method(self, name: str):
        """Return a recovery-port channel method, or None when unavailable.

        Custom recovery implementations predating the error-state channel do
        not expose the query API; callers fall back to safe defaults so the
        server keeps running (REQ-10.13.x).
        """
        method = getattr(self.recovery, name, None)
        return method if callable(method) else None

    def mark_degraded(self, operation: str) -> None:
        """Mark a cache call as having ended degraded (REQ-6.8.6)."""
        marker = self._channel_method("mark_degraded")
        if marker is not None:
            marker(operation)

    def is_degraded(self, operation: str) -> bool:
        """Return True if the operation's most recent call ended degraded."""
        query = self._channel_method("is_degraded")
        return bool(query(operation)) if query is not None else False

    def get_and_clear_degraded(self, operation: str) -> bool:
        """Atomically report degraded state for the last call and clear it."""
        query = self._channel_method("get_and_clear_degraded")
        return bool(query(operation)) if query is not None else False

    def last_error_for(self, operation: str) -> dict[str, Any] | None:
        """Return the most recent backend error state for one operation."""
        query = self._channel_method("last_error_for")
        return query(operation) if query is not None else None

    def record_recovery_outcome(self, operation: str, attempted: bool, succeeded: bool) -> None:
        """Record a recovery attempt outcome in the error-state channel."""
        recorder = self._channel_method("record_recovery")
        if recorder is not None:
            recorder(operation, attempted, succeeded)

    def log_parse_error(
        self,
        file_path: str,
        error: Exception,
        file_hash: str,
        compile_args_hash: str | None,
        retry_count: int,
    ) -> bool:
        """Log a parsing error to the centralized error log for developer analysis.

        Args:
            file_path: Path to the file that failed to parse
            error: The exception that was raised
            file_hash: Hash of the file content
            compile_args_hash: Hash of compilation arguments
            retry_count: Current retry count

        Returns:
            True if logged successfully, False otherwise
        """
        try:
            error_entry = {
                "timestamp": time.time(),
                "timestamp_readable": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "file_path": file_path,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "stack_trace": traceback.format_exc() if sys.exc_info()[0] is not None else None,
                "file_hash": file_hash,
                "compile_args_hash": compile_args_hash,
                "retry_count": retry_count,
            }

            # Append to JSONL file (one JSON object per line)
            with open(self.error_log_path, "a") as f:
                f.write(json.dumps(error_entry) + "\n")

            return True
        except Exception as e:
            # Don't let error logging break the main flow
            print(f"Failed to log parse error: {e}", file=sys.stderr)
            return False

    def get_parse_errors(
        self, limit: int | None = None, file_path_filter: str | None = None
    ) -> list[dict[str, Any]]:
        """Get parse errors from the error log.

        Args:
            limit: Maximum number of errors to return (most recent first)
            file_path_filter: Only return errors for files matching this path (substring match)

        Returns:
            List of error entries (dicts)
        """
        errors = []
        try:
            if not self.error_log_path.exists():
                return []

            with open(self.error_log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        error_entry = json.loads(line)
                        # Filter by file path if specified
                        if file_path_filter and file_path_filter not in error_entry.get(
                            "file_path", ""
                        ):
                            continue
                        errors.append(error_entry)
                    except json.JSONDecodeError:
                        # Skip malformed lines
                        continue

            # Sort by timestamp (most recent first)
            errors.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

            # Apply limit if specified
            if limit:
                errors = errors[:limit]

            return errors
        except Exception as e:
            print(f"Failed to load parse errors: {e}", file=sys.stderr)
            return []

    def get_parse_error_summary(self) -> dict[str, Any]:
        """Get a summary of parse errors for developer analysis.

        Returns:
            Dict with error statistics and recent errors
        """
        errors = self.get_parse_errors()

        # Count errors by type
        error_types: defaultdict[str, int] = defaultdict(int)
        files_with_errors = set()
        for error in errors:
            error_types[error.get("error_type", "Unknown")] += 1
            files_with_errors.add(error.get("file_path"))

        # Get most recent errors
        recent_errors = errors[:10] if len(errors) > 10 else errors

        return {
            "total_errors": len(errors),
            "unique_files": len(files_with_errors),
            "error_types": dict(error_types),
            "recent_errors": recent_errors,
            "error_log_path": str(self.error_log_path),
        }

    def clear_error_log(self, older_than_days: int | None = None) -> int:
        """Clear the error log, optionally keeping recent errors.

        Args:
            older_than_days: If specified, only clear errors older than this many days.
                           If None, clear all errors.

        Returns:
            Number of errors cleared
        """
        try:
            if not self.error_log_path.exists():
                return 0

            if older_than_days is None:
                # Clear all errors
                count = sum(1 for _ in open(self.error_log_path))
                self.error_log_path.unlink()
                return count
            else:
                # Keep recent errors
                cutoff_time = time.time() - (older_than_days * 86400)
                errors = self.get_parse_errors()
                kept_errors = [e for e in errors if e.get("timestamp", 0) > cutoff_time]
                cleared_count = len(errors) - len(kept_errors)

                # Rewrite file with kept errors
                with open(self.error_log_path, "w") as f:
                    f.writelines(json.dumps(error) + "\n" for error in kept_errors)

                return cleared_count
        except Exception as e:
            print(f"Failed to clear error log: {e}", file=sys.stderr)
            return 0

    # -------------------------------------------------------------------------
    # Type Aliases (Phase 1.3: Type Alias Tracking)
    # -------------------------------------------------------------------------

    def save_type_aliases_batch(self, aliases: list[TypeAliasRecord]) -> int:
        """
        Batch save type aliases to cache.

        Phase 1.3: Type Alias Tracking - Wrapper for backend storage

        Args:
            aliases: List of alias records

        Returns:
            Number of aliases successfully saved
        """
        outcome = self._safe_backend_call(
            "save_type_aliases_batch", lambda: self.backend.save_type_aliases_batch(aliases)
        )
        return self._map_outcome(
            "save_type_aliases_batch",
            outcome,
            0,
            log_note=f"save_type_aliases_batch failed; {len(aliases)} aliases not persisted",
        )

    def get_aliases_for_canonical(self, canonical_type: str) -> list[str]:
        """
        Get all alias names that resolve to a canonical type.

        Phase 1.3: Type Alias Tracking - Search unification support

        Args:
            canonical_type: Canonical type to look up

        Returns:
            List of alias names
        """
        outcome = self._safe_backend_call(
            "get_aliases_for_canonical",
            lambda: self.backend.get_aliases_for_canonical(canonical_type),
        )
        return self._map_outcome("get_aliases_for_canonical", outcome, [])

    def get_canonical_for_alias(self, alias_name: str) -> str | None:
        """
        Get canonical type for an alias name.

        Phase 1.3: Type Alias Tracking - Hybrid response format support

        Args:
            alias_name: Alias name to look up

        Returns:
            Canonical type string, or None if not found
        """
        outcome = self._safe_backend_call(
            "get_canonical_for_alias", lambda: self.backend.get_canonical_for_alias(alias_name)
        )
        # Failure must not claim "not found": mark degraded so handlers can
        # phrase "alias lookup unavailable" honestly (empty vs unavailable).
        return self._map_outcome("get_canonical_for_alias", outcome, None)

    def get_type_alias_info(self, type_name: str) -> dict[str, Any] | None:
        """
        Get high-level information for a known type alias from the cache.

        Returns:
            Dict with canonical_type, aliases, and metadata, or None if not found.
        """
        outcome = self._safe_backend_call(
            "get_type_alias_info", lambda: self.backend.get_type_alias_info(type_name)
        )
        # Same empty-vs-unavailable rule as get_canonical_for_alias.
        return self._map_outcome("get_type_alias_info", outcome, None)

    def get_type_alias_details(self, alias_names: list[str]) -> list[dict[str, Any]]:
        """
        Get detailed records for a list of alias names from the cache.

        Returns:
            List of alias detail dicts.
        """
        outcome = self._safe_backend_call(
            "get_type_alias_details", lambda: self.backend.get_type_alias_details(alias_names)
        )
        return self._map_outcome("get_type_alias_details", outcome, [])

    def get_all_alias_mappings(self) -> dict[str, str]:
        """
        Get all alias → canonical type mappings.

        Phase 1.3: Type Alias Tracking - Bulk lookup for search expansion

        Returns:
            Dictionary mapping alias names to canonical types
        """
        outcome = self._safe_backend_call(
            "get_all_alias_mappings", lambda: self.backend.get_all_alias_mappings()
        )
        return self._map_outcome("get_all_alias_mappings", outcome, {})
