"""
Worker result merging for C++ Analyzer.

Extracted from CppAnalyzer to isolate the logic that merges symbols, call sites,
and header-tracking state produced by worker processes (or threads) back into the
main process indexes.
"""

from typing import TYPE_CHECKING, Any, Tuple

from . import diagnostics

if TYPE_CHECKING:
    from .project_context import ProjectContext


class WorkerResultMerger:
    """Merges results from indexing workers into the shared indexes."""

    def __init__(self, context: "ProjectContext"):
        """
        Initialize the worker result merger.

        Args:
            context: Shared project context with concurrency, symbol store, call
                     graph service, and cache orchestrator.
        """
        self.context = context
        assert context.concurrency is not None
        self.concurrency = context.concurrency
        assert context.symbol_store is not None
        self.symbol_store = context.symbol_store
        assert context.call_graph_service is not None
        self.call_graph_service = context.call_graph_service
        assert context.cache_orchestrator is not None
        self.cache_orchestrator = context.cache_orchestrator

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
                    self.cache_orchestrator.header_tracker.mark_completed(header_path, header_hash)

            file_hash = self.cache_orchestrator._get_file_hash(file_path)
            self.symbol_store.file_hashes[file_path] = file_hash

    def get_worker_result(self, future, file_path: str, use_processes: bool) -> Tuple[bool, bool]:
        """Get result from future and merge into indexes."""
        try:
            result = future.result()
            if use_processes:
                # ProcessPoolExecutor: result is 6-tuple
                self.merge_worker_result(result, file_path)
                return bool(result[1]), bool(result[2])  # success, was_cached

            # ThreadPoolExecutor: result is (success, was_cached)
            return bool(result[0]), bool(result[1])
        except Exception as exc:
            diagnostics.error(f"Error indexing {file_path}: {exc}")
            return False, False

    def process_refresh_result(self, file_path: str, res: Any, use_processes: bool) -> bool:
        """Process result from indexing worker during refresh. Returns True if successful."""
        success = res[1] if use_processes else res[0]
        if success:
            if use_processes:
                self.merge_worker_result(res, file_path)
            return True
        return False
