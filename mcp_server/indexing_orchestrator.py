"""
Project-level indexing orchestration for C++ Analyzer.

Extracted from CppAnalyzer to isolate the high-level flow that indexes an entire
project: cache priming, file discovery, task submission, result merging, progress
reporting, and finalization.
"""

import sys
import time
from concurrent.futures import as_completed
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Tuple

from . import diagnostics

if TYPE_CHECKING:
    from .project_context import ProjectContext


class ProjectIndexingOrchestrator:
    """Orchestrates a full project indexing run."""

    def __init__(
        self,
        context: "ProjectContext",
        task_submitter: Any,
        worker_result_merger: Any,
    ):
        """
        Initialize the project indexing orchestrator.

        Args:
            context: Shared project context with cancellation, concurrency,
                     execution, compilation, cache, and symbol services.
            task_submitter: IndexingTaskSubmitter instance.
            worker_result_merger: WorkerResultMerger instance.
        """
        self.context = context
        self.cancellation = context.cancellation
        self.concurrency = context.concurrency
        self.execution = context.execution
        assert context.compilation_env is not None
        self.compilation_env = context.compilation_env
        self.cache_orchestrator = context.cache_orchestrator
        self.cache_manager = context.cache_manager
        self.symbol_extractor = context.symbol_extractor
        self.symbol_store = context.symbol_store
        self.task_submitter = task_submitter
        self.worker_result_merger = worker_result_merger
        self.progress_reporter = context.progress_reporter

    def index_project(
        self,
        include_dependencies: bool,
        force: bool = False,
        progress_callback: Optional[Callable] = None,
        wait_for_tools_callback: Optional[Callable[[], None]] = None,
    ) -> int:
        """
        Index all C++ files in the project.

        Args:
            include_dependencies: Include dependency files in indexing
            force: Force re-indexing even if cache exists
            progress_callback: Optional callback for progress updates
            wait_for_tools_callback: Optional callback to wait for tool availability

        Returns:
            Number of files indexed
        """
        start_time = time.time()

        cached_count = self.cache_orchestrator._handle_cache_initial_index(force)
        if cached_count is not None:
            return cached_count  # type: ignore[no-any-return]

        files = self._prepare_indexing_files(include_dependencies)
        if not files:
            return 0

        self.cancellation.reset()
        is_terminal = self.progress_reporter.is_terminal()
        indexed_count, cache_hits, failed_count = 0, 0, 0
        last_report_time = start_time

        executor = self.execution.worker_pool.setup()

        try:
            future_to_file = self.task_submitter.submit_indexing_tasks(
                executor, files, force, include_dependencies
            )

            for i, future in enumerate(as_completed(future_to_file)):
                if self.cancellation.is_interrupted():
                    raise KeyboardInterrupt("Indexing interrupted by request")
                if wait_for_tools_callback:
                    wait_for_tools_callback()

                file_path = future_to_file[future]
                success, was_cached = self.worker_result_merger.get_worker_result(
                    future, file_path, self.execution.use_processes
                )

                idx_d, cache_d, fail_d = self._update_indexing_counts(success, was_cached)
                indexed_count += idx_d
                cache_hits += cache_d
                failed_count += fail_d

                last_report_time = self.progress_reporter.maybe_report_indexing_progress(
                    i + 1,
                    len(files),
                    indexed_count,
                    failed_count,
                    cache_hits,
                    start_time,
                    last_report_time,
                    is_terminal,
                    progress_callback,
                    file_path,
                )

        except KeyboardInterrupt:
            diagnostics.info("\nIndexing interrupted by user (Ctrl-C)")
            self.execution.worker_pool.shutdown(name="Indexing")
            raise
        finally:
            self.execution.worker_pool.shutdown_nowait(name="Indexing")

        return self._finalize_indexing(
            indexed_count, len(files), start_time, is_terminal, cache_hits, failed_count
        )

    def _prepare_indexing_files(self, include_dependencies: bool) -> List[str]:
        """Find C++ files to index and log compilation environment."""
        diagnostics.debug(f"Finding C++ files (include_dependencies={include_dependencies})...")
        files = self.compilation_env._find_cpp_files(include_dependencies=include_dependencies)

        if not files:
            diagnostics.warning("No C++ files found in project")
            return []

        diagnostics.debug(f"Found {len(files)} C++ files to index")
        self.compilation_env._log_compilation_environment(files)
        return files  # type: ignore[no-any-return]

    def _finalize_indexing(
        self,
        indexed_count: int,
        total_files: int,
        start_time: float,
        is_terminal: bool,
        cache_hits: int,
        failed_count: int,
    ) -> int:
        """Finalize indexing by saving state and reporting summary."""
        self.symbol_store.indexed_file_count = indexed_count
        self.cache_orchestrator.last_index_time = time.time() - start_time

        if is_terminal:
            print("", file=sys.stderr)

        with self.concurrency.index_lock:
            class_count = sum(len(infos) for infos in self.symbol_store.class_index.values())
            function_count = sum(len(infos) for infos in self.symbol_store.function_index.values())

        diagnostics.info(f"Indexing complete in {self.cache_orchestrator.last_index_time:.2f}s")
        diagnostics.info(
            f"Indexed {indexed_count}/{total_files} files successfully "
            f"({cache_hits} from cache, {failed_count} failed)"
        )
        diagnostics.info(f"Found {class_count} classes, {function_count} functions")

        if failed_count > 0:
            diagnostics.info(
                f"Note: {failed_count} files failed to parse - this is normal for complex projects"
            )

        self.symbol_extractor._resolve_deferred_instantiation_bases()
        self.cache_orchestrator._save_cache()
        self.cache_orchestrator._save_progress_summary(
            indexed_count, total_files, cache_hits, failed_count
        )
        self.cache_orchestrator._save_header_tracking()
        self.cache_manager.backend.rebuild_fts()

        return indexed_count

    @staticmethod
    def _update_indexing_counts(success: bool, was_cached: bool) -> Tuple[int, int, int]:
        """Return (indexed_delta, cache_delta, failed_delta) for a single result."""
        if success:
            return 1, 1 if was_cached else 0, 0
        return 0, 0, 1
