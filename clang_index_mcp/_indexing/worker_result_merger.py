"""
Worker result merging for C++ Analyzer.

Extracted from CppAnalyzer to isolate the logic that merges symbols, call sites,
and header-tracking state produced by worker processes back into the main process
indexes.
"""

from typing import TYPE_CHECKING, Any, Tuple

from .._core import diagnostics

if TYPE_CHECKING:
    from .._core.concurrency_context import ConcurrencyContext
    from .._persistence.cache_orchestrator import CacheOrchestrator
    from .._search.call_graph_service import CallGraphService
    from .._symbols.symbol_index_store import SymbolIndexStore


class WorkerResultMerger:
    """Merges results from indexing workers into the shared indexes."""

    def __init__(
        self,
        concurrency: "ConcurrencyContext",
        symbol_store: "SymbolIndexStore",
        call_graph_service: "CallGraphService",
        cache_orchestrator: "CacheOrchestrator",
    ):
        """
        Initialize the worker result merger.

        Args:
            concurrency: Concurrency context with index_lock.
            symbol_store: In-memory symbol indexes.
            call_graph_service: Call graph and dependency tracking.
            cache_orchestrator: Cache orchestration and header tracking.
        """
        self.concurrency = concurrency
        self.symbol_store = symbol_store
        self.call_graph_service = call_graph_service
        self.cache_orchestrator = cache_orchestrator

    def merge_worker_result(self, result: Tuple, file_path: str):
        """Merge symbols and call sites from a worker process result."""
        _, success, was_cached, symbols, call_sites, processed_headers = result

        if success and symbols:
            with self.concurrency.index_lock:
                # CRITICAL: Clear old entries for this file FIRST (before adding new symbols)
                # This ensures that modified files don't have duplicate/stale symbols
                self.symbol_store._clear_file_index_entries(file_path)

                for symbol in symbols:
                    self.symbol_store._merge_symbol_into_indexes(symbol)

            if call_sites:
                self.call_graph_service._stream_call_sites(file_path, call_sites)

            if processed_headers:
                for header_path, header_hash in processed_headers.items():
                    self.cache_orchestrator.mark_header_completed(header_path, header_hash)

            file_hash = self.cache_orchestrator._get_file_hash(file_path)
            self.symbol_store.set_file_hash(file_path, file_hash)

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
        success = res[1]
        if success:
            self.merge_worker_result(res, file_path)
            return True
        return False
