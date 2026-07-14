"""
Worker result merging for C++ Analyzer.

Extracted from CppAnalyzer to isolate the logic that merges symbols, call sites,
and header-tracking state produced by worker processes back into the main process
indexes.
"""

import queue
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from .._core import diagnostics

if TYPE_CHECKING:
    from .._persistence.cache_orchestrator import CacheOrchestrator
    from .._search.call_graph_service import CallGraphService
    from .._symbols.symbol_index_store import SymbolIndexStore


@dataclass
class _CacheWriteRequest:
    """Per-file cache data handed off to the background writer thread."""

    file_path: str
    symbols: List[Any]
    file_hash: str
    compile_args_hash: Optional[str]
    success: bool
    error_message: Optional[str]
    retry_count: int


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

        self._cache_queue: Optional[queue.SimpleQueue] = None
        self._cache_writer_thread: Optional[threading.Thread] = None
        self._cache_writer_lock = threading.Lock()

    def _get_project_identity(self) -> Optional[Any]:
        """Return the project identity used to open a private cache connection."""
        cache_manager = getattr(self.cache_orchestrator, "cache_manager", None)
        if cache_manager is None:
            return None
        return getattr(cache_manager, "project_identity", None)

    def _ensure_cache_writer_started(self) -> None:
        """Start the background cache writer thread on first use."""
        with self._cache_writer_lock:
            if self._cache_writer_thread is not None:
                return

            identity = self._get_project_identity()
            if identity is None:
                diagnostics.warning(
                    "Cannot start background cache writer: no project identity available"
                )
                return

            q: queue.SimpleQueue = queue.SimpleQueue()
            self._cache_queue = q
            t = threading.Thread(
                target=self._cache_writer_thread_target,
                args=(identity, q),
                daemon=True,
                name="CacheWriter",
            )
            t.start()
            self._cache_writer_thread = t

    def _cache_writer_thread_target(self, identity: Any, q: queue.SimpleQueue) -> None:
        """Background thread target: own a cache connection and write file caches."""
        from .._persistence.cache_manager import CacheManager

        try:
            cache_manager = CacheManager(identity, skip_schema_recreation=False)
        except Exception as e:
            diagnostics.error(f"Background cache writer failed to initialize: {e}")
            return

        try:
            while True:
                try:
                    item = q.get(timeout=0.1)
                except queue.Empty:
                    continue
                if item is None:
                    break
                self._write_one(cache_manager, item)
        finally:
            try:
                cache_manager.close()
            except Exception:
                pass

    def _write_one(self, cache_manager: Any, item: _CacheWriteRequest) -> None:
        """Persist a single file's cache from the background thread."""
        try:
            cache_manager.save_file_cache(
                item.file_path,
                item.symbols,
                item.file_hash,
                item.compile_args_hash,
                item.success,
                item.error_message,
                item.retry_count,
            )
        except Exception as e:
            diagnostics.error(f"Background cache write failed for {item.file_path}: {e}")

    def _enqueue_file_cache(
        self,
        file_path: str,
        symbols: List[Any],
        file_hash: str,
        compile_args_hash: Optional[str],
        success: bool,
        error_message: Optional[str],
        retry_count: int,
    ) -> None:
        """Hand the per-file cache write to the background writer thread.

        Falls back to a synchronous write if the background writer could not be
        started (e.g. in tests with a mock orchestrator).
        """
        self._ensure_cache_writer_started()
        q = self._cache_queue
        if q is None:
            self.cache_orchestrator.save_file_cache(
                file_path,
                symbols,
                file_hash,
                compile_args_hash,
                success=success,
                error_message=error_message,
                retry_count=retry_count,
            )
            return

        q.put(
            _CacheWriteRequest(
                file_path=file_path,
                symbols=symbols,
                file_hash=file_hash,
                compile_args_hash=compile_args_hash,
                success=success,
                error_message=error_message,
                retry_count=retry_count,
            )
        )

    def merge_worker_result(self, result: Tuple, file_path: str):
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
        ) = result

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

    def get_worker_result(self, future, file_path: str) -> Tuple[bool, bool]:
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

    def flush_cache_writes(self) -> None:
        """Flush any pending per-file cache writes and stop the background writer."""
        with self._cache_writer_lock:
            t = self._cache_writer_thread
            q = self._cache_queue
            if t is None or q is None:
                return
            q.put(None)
            self._cache_writer_thread = None
            self._cache_queue = None

        t.join(timeout=120.0)
        if t.is_alive():
            diagnostics.warning("Background cache writer did not finish within timeout")

    def close(self) -> None:
        """Stop the background cache writer and release resources."""
        self.flush_cache_writes()
