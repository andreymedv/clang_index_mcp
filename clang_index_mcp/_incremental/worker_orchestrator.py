"""Worker-pool orchestration for incremental re-analysis.

Handles submitting indexing tasks to a shared worker pool, processing results,
and reporting progress during incremental refresh.
"""

import os
from collections.abc import Callable
from concurrent.futures import Executor, as_completed
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .._contexts.incremental_context import IncrementalContext
    from .._indexing.worker_result_merger import WorkerResultMerger
    from .._symbols.indexing_callbacks import IndexingCallbacks


def process_future_result(
    result_merger: "WorkerResultMerger", result: Any, file_path: str
) -> tuple[bool, bool]:
    """Process the result from a future and merge it into the analyzer.

    Delegates to WorkerResultMerger.merge_worker_result so the incremental path
    shares the full indexing merge semantics: stale index entries are cleared
    before merging, call sites are streamed to SQLite with full field fidelity,
    and file hashes are recorded only for successful, non-empty results. The
    per-file cache write is offloaded to the merger's background writer; the
    caller flushes it when the processing loop finishes.
    """
    # ProcessPoolExecutor returns:
    # (file_path, success, was_cached, symbols, call_sites, processed_headers,
    #  file_hash, compile_args_hash, error_message, retry_count)
    result_merger.merge_worker_result(result, file_path)
    return result[1], result[2]


def report_progress(
    progress_callback: Callable,
    i: int,
    total: int,
    analyzed: int,
    failed: int,
    start_time: float,
    file_path: str,
) -> None:
    """Calculate and report indexing progress via callback."""
    from .._indexing.indexing_progress_reporter import IndexingProgressReporter

    # In the caller's loop analyzed + failed == i + 1 (every iteration increments
    # exactly one of them), so the canonical reporter's processed counter and
    # its every-10-files / last-file gating match this function's old behavior.
    IndexingProgressReporter.report_refresh_progress(
        progress_callback, total, analyzed, failed, file_path, start_time
    )


def submit_tasks(
    ctx: "IncrementalContext",
    executor: Executor,
    file_list: list[str],
) -> dict[Any, str]:
    """Submit re-analysis tasks to the process pool executor."""
    from .._incremental.compile_args_resolver import get_file_compile_args
    from .._indexing.indexing_task_submitter import submit_file_task

    compilation_env = ctx.compilation_env
    file_compile_args = get_file_compile_args(ctx, file_list)

    return {
        submit_file_task(
            executor,
            project_root=str(ctx.project_root),
            config_file=ctx.config_file,
            file_path=file_path,
            force=True,
            include_dependencies=compilation_env.include_dependencies,
            compile_args=file_compile_args[file_path],
        ): file_path
        for file_path in file_list
    }


def process_loop(
    future_to_file: dict[Any, str],
    start_time: float,
    total: int,
    callbacks: Optional["IndexingCallbacks"],
    is_interrupted: Callable[[], bool],
    result_merger: "WorkerResultMerger",
) -> tuple[int, int]:
    """Process results from futures in a loop."""
    from .._core import diagnostics

    analyzed = 0
    failed = 0

    for i, future in enumerate(as_completed(future_to_file)):
        if is_interrupted():
            for f in future_to_file:
                f.cancel()
            diagnostics.info("Incremental refresh interrupted by request")
            raise KeyboardInterrupt("Incremental refresh interrupted by request")

        if callbacks and callbacks.wait_for_tools:
            callbacks.wait_for_tools()

        file_path = future_to_file[future]
        try:
            result = future.result()
            success, _was_cached = process_future_result(result_merger, result, file_path)

            if success:
                analyzed += 1
                diagnostics.debug(f"Re-analyzed: {file_path}")
            else:
                failed += 1
                diagnostics.warning(f"Failed to re-analyze: {file_path}")
        except Exception as e:
            failed += 1
            diagnostics.error(f"Error re-analyzing {file_path}: {e}")

        progress_callback = callbacks.progress if callbacks else None
        if progress_callback:
            report_progress(progress_callback, i, total, analyzed, failed, start_time, file_path)

    return analyzed, failed


def reanalyze_files(
    ctx: "IncrementalContext",
    files: set[str],
    start_time: float,
    callbacks: Optional["IndexingCallbacks"] = None,
    is_interrupted: Callable[[], bool] | None = None,
) -> int:
    """
    Re-analyze a set of files using parallel processing.

    Returns the number of files successfully analyzed.
    """
    if not files:
        return 0

    if is_interrupted is None:

        def _never_interrupted() -> bool:
            return False

        is_interrupted = _never_interrupted

    return _run_analysis_loop(ctx, list(files), start_time, len(files), callbacks, is_interrupted)


def _run_analysis_loop(
    ctx: "IncrementalContext",
    file_list: list[str],
    start_time: float,
    total: int,
    callbacks: Optional["IndexingCallbacks"],
    is_interrupted: Callable[[], bool],
) -> int:
    """Execute the analysis loop with executor lifecycle management."""
    from .._core import diagnostics
    from .._indexing.worker_pool import WorkerPoolManager
    from .._indexing.worker_result_merger import WorkerResultMerger

    result_merger = WorkerResultMerger(
        symbol_store=ctx.symbol_store,
        call_graph_service=ctx.call_graph_service,
        cache_orchestrator=ctx.cache_orchestrator,
    )

    pool = WorkerPoolManager(max_workers=os.cpu_count() or 4)
    analyzed = 0
    try:
        with pool.managed_executor("Incremental Refresh") as executor:
            future_to_file = submit_tasks(ctx, executor, file_list)
            analyzed, _failed = process_loop(
                future_to_file, start_time, total, callbacks, is_interrupted, result_merger
            )
    except KeyboardInterrupt:
        diagnostics.info("\nIncremental refresh interrupted")
        raise
    finally:
        # Ensure all background cache writes are durable before returning.
        result_merger.flush_cache_writes()

    return analyzed
