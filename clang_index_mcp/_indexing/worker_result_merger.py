"""
Worker result merging for C++ Analyzer.

Extracted from CppAnalyzer to isolate the logic that merges symbols, call sites,
and header-tracking state produced by worker processes back into the main process
indexes.
"""

import threading
from typing import TYPE_CHECKING, Any

from .._core import diagnostics
from .cache_writer import CacheWriteRequest, CacheWriterStats, CacheWriterThread

if TYPE_CHECKING:
    from .._persistence.cache_orchestrator import CacheOrchestrator
    from .._search.call_graph_service import CallGraphService
    from .._symbols.symbol_index_store import SymbolIndexStore


class WorkerResultMerger:
    """Merges results from indexing workers into the shared indexes."""

    def __init__(
        self,
        symbol_store: "SymbolIndexStore",
        call_graph_service: "CallGraphService",
        cache_orchestrator: "CacheOrchestrator",
    ):
        """
        Initialize the worker result merger.

        Args:
            symbol_store: In-memory symbol indexes.
            call_graph_service: Call graph and dependency tracking.
            cache_orchestrator: Cache orchestration and header tracking.
        """
        self.symbol_store = symbol_store
        self.call_graph_service = call_graph_service
        self.cache_orchestrator = cache_orchestrator

        self._cache_writer: CacheWriterThread | None = None
        self._cache_writer_lock = threading.Lock()

    def _get_project_identity(self) -> Any | None:
        """Return the project identity used to open a private cache connection."""
        cache_manager = getattr(self.cache_orchestrator, "cache_manager", None)
        if cache_manager is None:
            return None
        return getattr(cache_manager, "project_identity", None)

    def _build_cache_writer(self) -> CacheWriterThread | None:
        """Create the background writer, or None when no project identity exists."""
        identity = self._get_project_identity()
        if identity is None:
            diagnostics.warning(
                "Cannot start background cache writer: no project identity available"
            )
            return None

        def factory() -> Any:
            from .._persistence.cache_manager import CacheManager

            # Secondary connection: primary backend owns schema lifecycle.
            return CacheManager(identity, skip_schema_recreation=True)

        return CacheWriterThread(factory, error_recorder=self._record_writer_error)

    def _record_writer_error(self, error_type: str, message: str, operation: str) -> None:
        """Feed writer failures into the main process error-state channel (write class)."""
        cache_manager = getattr(self.cache_orchestrator, "cache_manager", None)
        recovery = getattr(cache_manager, "recovery", None) if cache_manager else None
        if recovery is None:
            return
        try:
            recovery.record_error(error_type, message, operation, recoverable=True)
        except Exception:
            pass

    def _ensure_cache_writer_started(self) -> None:
        """Start the background cache writer thread on first use."""
        with self._cache_writer_lock:
            if self._cache_writer is not None:
                return
            writer = self._build_cache_writer()
            if writer is None:
                return
            writer.start()
            self._cache_writer = writer
            self._register_writer_stats()

    def _register_writer_stats(self) -> None:
        """Expose writer counters via get_error_summary (additive cache_writer key)."""
        cache_manager = getattr(self.cache_orchestrator, "cache_manager", None)
        writer = self._cache_writer
        if cache_manager is None or writer is None:
            return
        setter = getattr(cache_manager, "set_error_summary_extra_provider", None)
        if callable(setter):
            setter(lambda: writer.get_stats().as_dict())

    def _enqueue_file_cache(
        self,
        file_path: str,
        symbols: list[Any],
        file_hash: str,
        compile_args_hash: str | None,
        success: bool,
        error_message: str | None,
        retry_count: int,
    ) -> None:
        """Hand the per-file cache write to the background writer thread.

        Falls back to a synchronous write if the background writer could not be
        started (e.g. in tests with a mock orchestrator).
        """
        self._ensure_cache_writer_started()
        writer = self._cache_writer
        if writer is None:
            self._save_file_cache_sync(
                file_path,
                symbols,
                file_hash,
                compile_args_hash,
                success,
                error_message,
                retry_count,
            )
            return

        request = CacheWriteRequest(
            file_path=file_path,
            symbols=symbols,
            file_hash=file_hash,
            compile_args_hash=compile_args_hash,
            success=success,
            error_message=error_message,
            retry_count=retry_count,
        )
        if not writer.enqueue(request):
            # Dropped (write-disabled or full): keep indexing healthy; the
            # drop is already counted in writer stats (REQ-6.7.1).
            diagnostics.debug(f"Cache write dropped for {file_path}")

    def _save_file_cache_sync(
        self,
        file_path: str,
        symbols: list[Any],
        file_hash: str,
        compile_args_hash: str | None,
        success: bool,
        error_message: str | None,
        retry_count: int,
    ) -> None:
        try:
            self.cache_orchestrator.save_file_cache(
                file_path,
                symbols,
                file_hash,
                compile_args_hash,
                success=success,
                error_message=error_message,
                retry_count=retry_count,
            )
        except Exception as e:
            diagnostics.error(f"Background cache write failed for {file_path}: {e}")

    def merge_worker_result(self, result: tuple, file_path: str):
        """Merge symbols and call sites from a worker process result.

        In-memory indexes are updated synchronously on the main thread. The
        per-file cache write is offloaded to a background thread so that worker
        results can be consumed as fast as the workers produce them.
        """
        (
            _,
            success,
            was_cached,
            symbols,
            call_sites,
            processed_headers,
            file_hash,
            compile_args_hash,
            error_message,
            retry_count,
        ) = result[:10]
        cache_write_ok = bool(result[10]) if len(result) > 10 else True
        if not cache_write_ok:
            # Worker-side write failures are DATA, never an exception (child .8).
            diagnostics.warning(
                f"Worker reported cache write failure for {file_path}; "
                "in-memory results are kept"
            )

        if success and symbols:
            with self.symbol_store.index_lock:
                # CRITICAL: Clear old entries for this file FIRST (before adding new symbols)
                # This ensures that modified files don't have duplicate/stale symbols
                self.symbol_store.clear_file_index_entries(file_path)

                for symbol in symbols:
                    self.symbol_store.merge_symbol_into_indexes(symbol)

            if call_sites:
                self.call_graph_service.stream_call_sites(file_path, call_sites)

            if processed_headers:
                for header_path, header_hash in processed_headers.items():
                    self.cache_orchestrator.mark_header_completed(header_path, header_hash)

            self.symbol_store.set_file_hash(file_path, file_hash)

        # Offload the per-file cache write to the background writer thread.
        # Workers deliberately skip this step; serializing through one background
        # writer avoids the SQLite contention of N worker processes while still
        # allowing the main thread to consume results asynchronously.
        if not was_cached:
            self._enqueue_file_cache(
                file_path,
                symbols if success else [],
                file_hash,
                compile_args_hash,
                success=success,
                error_message=error_message,
                retry_count=retry_count,
            )

    def get_worker_result(self, future, file_path: str) -> tuple[bool, bool]:
        """Get result from future and merge into indexes."""
        try:
            result = future.result()
            self.merge_worker_result(result, file_path)
            return bool(result[1]), bool(result[2])  # success, was_cached
        except Exception as exc:
            diagnostics.error(f"Error indexing {file_path}: {exc}")
            return False, False

    def process_refresh_result(self, file_path: str, res: Any) -> bool:
        """Process result from indexing worker during refresh. Returns True if successful."""
        success = bool(res[1])
        self.merge_worker_result(res, file_path)
        return success

    def get_cache_writer_stats(self) -> CacheWriterStats | None:
        """Return background-writer counters, or None when the writer never started."""
        with self._cache_writer_lock:
            writer = self._cache_writer
        return writer.get_stats() if writer is not None else None

    def flush_cache_writes(self) -> None:
        """Flush any pending per-file cache writes and stop the background writer."""
        with self._cache_writer_lock:
            writer = self._cache_writer
            self._cache_writer = None
        if writer is None:
            return
        writer.stop()

    def close(self) -> None:
        """Stop the background cache writer and release resources."""
        self.flush_cache_writes()
