"""
Refresh pipeline for C++ Analyzer.

Extracted from CppAnalyzer to isolate the logic that detects changed/deleted files
and re-indexes them incrementally.
"""

import time
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from .._core import diagnostics
from .._symbols.indexing_callbacks import IndexingCallbacks

if TYPE_CHECKING:
    from concurrent.futures import Executor

    from .._compilation.compilation_environment import CompilationEnvironment
    from .._indexing.execution_config import ExecutionConfig
    from .._indexing.indexing_progress_reporter import IndexingProgressReporter
    from .._persistence.cache_manager import CacheManager
    from .._persistence.cache_orchestrator import CacheOrchestrator
    from .._symbols.symbol_extractor import SymbolExtractor
    from .._symbols.symbol_index_store import SymbolIndexStore


class RefreshPipeline:
    """Detects changed files and refreshes the index incrementally."""

    def __init__(
        self,
        compilation_env: "CompilationEnvironment",
        execution: "ExecutionConfig",
        cache_manager: "CacheManager",
        cache_orchestrator: "CacheOrchestrator",
        symbol_extractor: "SymbolExtractor",
        symbol_store: "SymbolIndexStore",
        progress_reporter: "IndexingProgressReporter",
        task_submitter: Any,
        worker_result_merger: Any,
    ):
        """
        Initialize the refresh pipeline.

        Args:
            compilation_env: Compilation environment for file scanning.
            execution: Execution configuration with worker pool.
            cache_manager: SQLite-backed cache and persistence.
            cache_orchestrator: Cache orchestration and header tracking.
            symbol_extractor: Symbol extraction from translation units.
            symbol_store: In-memory symbol indexes.
            progress_reporter: Progress reporting for indexing operations.
            task_submitter: IndexingTaskSubmitter instance.
            worker_result_merger: WorkerResultMerger instance.
        """
        self.compilation_env = compilation_env
        self.execution = execution
        self.cache_manager = cache_manager
        self.cache_orchestrator = cache_orchestrator
        self.symbol_extractor = symbol_extractor
        self.symbol_store = symbol_store
        self.progress_reporter = progress_reporter
        self.task_submitter = task_submitter
        self.worker_result_merger = worker_result_merger

    def refresh_if_needed(
        self,
        include_dependencies: bool,
        callbacks: Optional[IndexingCallbacks] = None,
    ) -> int:
        """
        Refresh index for changed files and remove deleted files.

        Returns:
            Number of files refreshed
        """
        refreshed, deleted, start_time = 0, 0, time.time()

        if self.compilation_env.has_active_compile_commands():
            compile_commands_manager = self.compilation_env.compile_commands_manager
            assert compile_commands_manager is not None
            if compile_commands_manager.refresh_if_needed():
                diagnostics.debug("Compile commands refreshed")

        modified_files, new_files, deleted = self._prepare_refresh_set(include_dependencies)
        total_to_check = len(modified_files) + len(new_files)

        if total_to_check == 0:
            if deleted > 0:
                self._finalize_refresh(0, deleted)
            return 0

        diagnostics.debug(f"Refresh: {len(modified_files)} modified, {len(new_files)} new files")
        self.cache_manager.ensure_schema_current()

        executor = self.execution.worker_pool.setup()
        try:
            refreshed, failed = self._run_refresh_loop(
                executor,
                modified_files,
                new_files,
                total_to_check,
                start_time,
                include_dependencies,
                callbacks,
            )
        except KeyboardInterrupt:
            diagnostics.info("\nRefresh interrupted by user (Ctrl-C)")
            self.execution.worker_pool.shutdown(name="Refresh")
            raise
        finally:
            self.execution.worker_pool.shutdown_nowait(name="Refresh")

        self._finalize_refresh(refreshed, deleted)
        return refreshed

    def _prepare_refresh_set(self, include_dependencies: bool) -> Tuple[List[str], List[str], int]:
        """Identify files to refresh and handle deleted files. Returns (modified, new, deleted_count)."""
        current_files = set(self.compilation_env.find_cpp_files(include_dependencies))
        deleted_count = self.compilation_env.handle_deleted_files(current_files)
        modified_files, new_files = self.compilation_env.identify_refresh_files(current_files)
        return modified_files, new_files, deleted_count

    def _run_refresh_loop(
        self,
        executor: "Executor",
        modified_files: List[str],
        new_files: List[str],
        total_to_check: int,
        start_time: float,
        include_dependencies: bool,
        callbacks: Optional[IndexingCallbacks],
    ) -> Tuple[int, int]:
        """Run the parallel refresh loop and return (refreshed_count, failed_count)."""
        from concurrent.futures import as_completed

        refreshed, failed = 0, 0
        future_to_file = self.task_submitter.submit_refresh_tasks(
            executor, modified_files, new_files, include_dependencies
        )
        for i, future in enumerate(as_completed(future_to_file)):
            if callbacks and callbacks.wait_for_tools:
                callbacks.wait_for_tools()

            file_path = future_to_file[future]
            try:
                if self.worker_result_merger.process_refresh_result(file_path, future.result()):
                    refreshed += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                diagnostics.error(f"Error refreshing {file_path}: {e}")

            progress_callback = callbacks.progress if callbacks else None
            if progress_callback and ((i + 1) % 10 == 0 or (i + 1) == total_to_check):
                self.progress_reporter.report_refresh_progress(
                    progress_callback, total_to_check, refreshed, failed, file_path, start_time
                )
        return refreshed, failed

    def _finalize_refresh(self, refreshed: int, deleted: int) -> None:
        """Perform post-refresh cleanup and optimizations."""
        if refreshed > 0 or deleted > 0:
            self.symbol_extractor.resolve_deferred_instantiation_bases()
            self.cache_orchestrator.save_cache()
            self.cache_orchestrator.save_header_tracking()
            if deleted > 0:
                diagnostics.info(f"Removed {deleted} deleted files from indexes")
            if refreshed > 0:
                self.cache_manager.backend.rebuild_fts()
        self.symbol_store.indexed_file_count = len(list(self.symbol_store.iter_file_paths()))
