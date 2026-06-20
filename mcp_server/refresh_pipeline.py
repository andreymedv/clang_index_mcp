"""
Refresh pipeline for C++ Analyzer.

Extracted from CppAnalyzer to isolate the logic that detects changed/deleted files
and re-indexes them incrementally.
"""

import time
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Tuple

from . import diagnostics

if TYPE_CHECKING:
    from concurrent.futures import Executor

    from .project_context import ProjectContext


class RefreshPipeline:
    """Detects changed files and refreshes the index incrementally."""

    def __init__(
        self,
        context: "ProjectContext",
        task_submitter: Any,
        worker_result_merger: Any,
    ):
        """
        Initialize the refresh pipeline.

        Args:
            context: Shared project context with compilation, cache, symbol, and
                     progress services.
            task_submitter: IndexingTaskSubmitter instance.
            worker_result_merger: WorkerResultMerger instance.
        """
        self.context = context
        assert context.compilation_env is not None
        self.compilation_env = context.compilation_env
        assert context.execution is not None
        self.execution = context.execution
        assert context.cache_manager is not None
        self.cache_manager = context.cache_manager
        assert context.cache_orchestrator is not None
        self.cache_orchestrator = context.cache_orchestrator
        assert context.symbol_extractor is not None
        self.symbol_extractor = context.symbol_extractor
        assert context.symbol_store is not None
        self.symbol_store = context.symbol_store
        self.task_submitter = task_submitter
        self.worker_result_merger = worker_result_merger
        assert context.progress_reporter is not None
        self.progress_reporter = context.progress_reporter

    def refresh_if_needed(
        self,
        include_dependencies: bool,
        compile_commands_manager: Any,
        progress_callback: Optional[Callable] = None,
        wait_for_tools_callback: Optional[Callable[[], None]] = None,
    ) -> int:
        """
        Refresh index for changed files and remove deleted files.

        Returns:
            Number of files refreshed
        """
        refreshed, deleted, start_time = 0, 0, time.time()

        if self.context.is_compile_commands_enabled():
            compile_commands_manager = self.context.compile_commands_manager
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
        if self.execution.use_processes:
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
                progress_callback,
                wait_for_tools_callback,
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
        current_files = set(self.compilation_env._find_cpp_files(include_dependencies))
        deleted_count = self.compilation_env._handle_deleted_files(current_files)
        modified_files, new_files = self.compilation_env._identify_refresh_files(current_files)
        return modified_files, new_files, deleted_count

    def _run_refresh_loop(
        self,
        executor: "Executor",
        modified_files: List[str],
        new_files: List[str],
        total_to_check: int,
        start_time: float,
        include_dependencies: bool,
        progress_callback: Optional[Callable],
        wait_for_tools_callback: Optional[Callable[[], None]],
    ) -> Tuple[int, int]:
        """Run the parallel refresh loop and return (refreshed_count, failed_count)."""
        from concurrent.futures import as_completed

        refreshed, failed = 0, 0
        future_to_file = self.task_submitter.submit_refresh_tasks(
            executor, modified_files, new_files, include_dependencies
        )
        for i, future in enumerate(as_completed(future_to_file)):
            if wait_for_tools_callback:
                wait_for_tools_callback()

            file_path = future_to_file[future]
            try:
                if self.worker_result_merger.process_refresh_result(
                    file_path, future.result(), self.execution.use_processes
                ):
                    refreshed += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                diagnostics.error(f"Error refreshing {file_path}: {e}")

            if progress_callback and ((i + 1) % 10 == 0 or (i + 1) == total_to_check):
                self.progress_reporter.report_refresh_progress(
                    progress_callback, total_to_check, refreshed, failed, file_path, start_time
                )
        return refreshed, failed

    def _finalize_refresh(self, refreshed: int, deleted: int) -> None:
        """Perform post-refresh cleanup and optimizations."""
        if refreshed > 0 or deleted > 0:
            self.symbol_extractor._resolve_deferred_instantiation_bases()
            self.cache_orchestrator._save_cache()
            self.cache_orchestrator._save_header_tracking()
            if deleted > 0:
                diagnostics.info(f"Removed {deleted} deleted files from indexes")
            if refreshed > 0:
                self.cache_manager.backend.rebuild_fts()
        self.symbol_store.indexed_file_count = len(self.symbol_store.file_hashes)
