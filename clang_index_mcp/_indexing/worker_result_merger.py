"""
Worker result merging for C++ Analyzer.

Extracted from CppAnalyzer to isolate the logic that merges symbols, call sites,
and header-tracking state produced by worker processes back into the main process
indexes.
"""

from typing import TYPE_CHECKING, Any, Tuple

from .._core import diagnostics

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

    def merge_worker_result(self, result: Tuple, file_path: str):
        """Merge symbols and call sites from a worker process result.

        Also persist the per-file cache from the main process. Workers no longer
        write cache themselves, so all SQLite writes during indexing are
        serialized through this path.
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

        # Persist per-file cache from the main process. Workers deliberately skip
        # this step so that all SQLite writes contend on a single writer instead
        # of N worker processes.
        if not was_cached:
            self.cache_orchestrator.save_file_cache(
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
