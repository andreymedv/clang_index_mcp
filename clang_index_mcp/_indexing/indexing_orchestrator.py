"""
Project-level indexing orchestration for C++ Analyzer.

Extracted from CppAnalyzer to isolate the high-level flow that indexes an entire
project: cache priming, file discovery, task submission, result merging, progress
reporting, and finalization.
"""

import sys
import time
from concurrent.futures import as_completed
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from .._core import diagnostics
from .._symbols.indexing_callbacks import IndexingCallbacks

if TYPE_CHECKING:
    from .._compilation.compilation_environment import CompilationEnvironment
    from .._core.cancellation_coordinator import CancellationCoordinator
    from .._core.concurrency_context import ConcurrencyContext
    from .._indexing.execution_config import ExecutionConfig
    from .._indexing.indexing_progress_reporter import IndexingProgressReporter
    from .._persistence.cache_manager import CacheManager
    from .._persistence.cache_orchestrator import CacheOrchestrator
    from .._symbols.symbol_extractor import SymbolExtractor
    from .._symbols.symbol_index_store import SymbolIndexStore


class ProjectIndexingOrchestrator:
    """Orchestrates a full project indexing run."""

    def __init__(
        self,
        cancellation: "CancellationCoordinator",
        concurrency: "ConcurrencyContext",
        execution: "ExecutionConfig",
        compilation_env: "CompilationEnvironment",
        cache_orchestrator: "CacheOrchestrator",
        cache_manager: "CacheManager",
        symbol_extractor: "SymbolExtractor",
        symbol_store: "SymbolIndexStore",
        progress_reporter: "IndexingProgressReporter",
        task_submitter: Any,
        worker_result_merger: Any,
        refresh_pipeline: Any = None,
    ):
        """
        Initialize the project indexing orchestrator.

        Args:
            cancellation: Cancellation coordinator for interrupting indexing.
            concurrency: Concurrency context with index_lock.
            execution: Execution configuration with worker pool.
            compilation_env: Compilation environment for file scanning.
            cache_orchestrator: Cache orchestration and header tracking.
            cache_manager: SQLite-backed cache and persistence.
            symbol_extractor: Symbol extraction from translation units.
            symbol_store: In-memory symbol indexes.
            progress_reporter: Progress reporting for indexing operations.
            task_submitter: IndexingTaskSubmitter instance.
            worker_result_merger: WorkerResultMerger instance.
            refresh_pipeline: RefreshPipeline instance (optional, for cache initial index).
        """
        self.cancellation = cancellation
        self.concurrency = concurrency
        self.execution = execution
        self.compilation_env = compilation_env
        self.cache_orchestrator = cache_orchestrator
        self.cache_manager = cache_manager
        self.symbol_extractor = symbol_extractor
        self.symbol_store = symbol_store
        self.progress_reporter = progress_reporter
        self.task_submitter = task_submitter
        self.worker_result_merger = worker_result_merger
        self.refresh_pipeline = refresh_pipeline

    def index_project(
        self,
        include_dependencies: bool,
        force: bool = False,
        callbacks: Optional[IndexingCallbacks] = None,
    ) -> int:
        """
        Index all C++ files in the project.

        Args:
            include_dependencies: Include dependency files in indexing
            force: Force re-indexing even if cache exists
            callbacks: Optional IndexingCallbacks with progress and wait_for_tools callbacks

        Returns:
            Number of files indexed
        """
        start_time = time.time()

        refresh_fn = None
        if self.refresh_pipeline is not None:
            refresh_fn = self.refresh_pipeline.refresh_if_needed
        cached_count = self.cache_orchestrator.handle_cache_initial_index(force, refresh_fn)
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
                if callbacks and callbacks.wait_for_tools:
                    callbacks.wait_for_tools()

                file_path = future_to_file[future]
                success, was_cached = self.worker_result_merger.get_worker_result(future, file_path)

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
                    callbacks.progress if callbacks else None,
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
        files = self.compilation_env.find_cpp_files(include_dependencies=include_dependencies)

        if not files:
            diagnostics.warning("No C++ files found in project")
            return []

        diagnostics.debug(f"Found {len(files)} C++ files to index")
        self.compilation_env.log_compilation_environment(files)
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
            class_count = self.symbol_store.total_class_symbols()
            function_count = self.symbol_store.total_function_symbols()

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

        self.symbol_extractor.resolve_deferred_instantiation_bases()
        self.cache_orchestrator.save_cache()
        self.cache_orchestrator.save_progress_summary(
            indexed_count, total_files, cache_hits, failed_count
        )
        self.cache_orchestrator.save_header_tracking()
        self.cache_manager.backend.rebuild_fts()

        return indexed_count

    @staticmethod
    def _update_indexing_counts(success: bool, was_cached: bool) -> Tuple[int, int, int]:
        """Return (indexed_delta, cache_delta, failed_delta) for a single result."""
        if success:
            return 1, 1 if was_cached else 0, 0
        return 0, 0, 1
