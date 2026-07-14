"""Worker-pool orchestration for incremental re-analysis.

Handles creating a process pool, submitting indexing tasks, processing results,
and reporting progress during incremental refresh.
"""

import multiprocessing
import os
import time
from concurrent.futures import Executor, ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple, Type

if TYPE_CHECKING:
    from .._contexts.incremental_context import IncrementalContext
    from .._symbols.indexing_callbacks import IndexingCallbacks


def create_executor(
    max_workers: int,
) -> Tuple[Optional[multiprocessing.context.BaseContext], Type[ProcessPoolExecutor], str]:
    """Create a process pool executor and its spawn context."""
    from .._core import diagnostics

    mp_context = None
    try:
        mp_context = multiprocessing.get_context("spawn")
        msg = f"Incremental refresh: Using ProcessPoolExecutor (spawn) with {max_workers} workers"
    except Exception as e:
        diagnostics.warning(f"Failed to use 'spawn' context: {e}. Falling back to default.")
        mp_context = None
        msg = f"Incremental refresh: Using ProcessPoolExecutor with {max_workers} workers"

    return mp_context, ProcessPoolExecutor, msg


def process_future_result(
    ctx: "IncrementalContext", result: Any, file_path: str
) -> Tuple[bool, bool]:
    """Process the result from a future and merge it into the analyzer."""
    from .._incremental.symbol_merger import merge_symbols

    call_graph_analyzer = ctx.call_graph_analyzer
    cache_orchestrator = ctx.cache_orchestrator
    symbol_store = ctx.symbol_store

    # ProcessPoolExecutor returns:
    # (file_path, success, was_cached, symbols, call_sites, processed_headers,
    #  file_hash, compile_args_hash, error_message, retry_count)
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
        merge_symbols(ctx, symbols)

    if call_sites:
        for cs_dict in call_sites:
            call_graph_analyzer.add_call(
                cs_dict["caller_usr"],
                cs_dict["callee_usr"],
                cs_dict["file"],
                cs_dict["line"],
                cs_dict.get("column"),
            )

    if processed_headers:
        for header_path, header_hash in processed_headers.items():
            cache_orchestrator.mark_header_completed(header_path, header_hash)

    symbol_store.set_file_hash(file_path, file_hash)

    # Persist per-file cache from the main process. Workers skip cache writes so
    # that all SQLite writes are serialized through a single process.
    if not was_cached:
        cache_orchestrator.save_file_cache(
            file_path,
            symbols if success else [],
            file_hash,
            compile_args_hash,
            success=success,
            error_message=error_message,
            retry_count=retry_count,
        )

    return success, was_cached


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
    from .._core import diagnostics

    processed = i + 1
    if processed % 10 == 0 or processed == total:
        try:
            from .._indexing.progress import IndexingProgress

            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (total - processed) / rate if rate > 0 else 0

            estimated_completion = datetime.now() + timedelta(seconds=eta) if eta > 0 else None

            progress = IndexingProgress(
                total_files=total,
                indexed_files=analyzed,
                failed_files=failed,
                cache_hits=0,
                current_file=file_path if processed < total else None,
                start_time=datetime.fromtimestamp(start_time),
                estimated_completion=estimated_completion,
            )

            progress_callback(progress)
        except Exception as e:
            diagnostics.debug(f"Progress callback failed: {e}")


def submit_tasks(
    ctx: "IncrementalContext",
    executor: Executor,
    file_list: List[str],
) -> Dict[Any, str]:
    """Submit re-analysis tasks to the process pool executor."""
    import os

    from .._indexing.indexing_task_spec import IndexingTaskSpec
    from .._indexing.worker_pool import _process_file_worker
    from .._incremental.compile_args_resolver import get_file_compile_args

    project_root = str(ctx.project_root)
    config_file_str = ctx.config_file
    compilation_env = ctx.compilation_env
    include_dependencies = compilation_env.include_dependencies
    file_compile_args = get_file_compile_args(ctx, file_list)

    return {
        executor.submit(
            _process_file_worker,
            IndexingTaskSpec(
                project_root=project_root,
                config_file=config_file_str,
                file_path=os.path.abspath(file_path),
                force=True,
                include_dependencies=include_dependencies,
                compile_args=file_compile_args[file_path],
            ),
        ): file_path
        for file_path in file_list
    }


def process_loop(
    ctx: "IncrementalContext",
    executor: Executor,
    future_to_file: Dict[Any, str],
    start_time: float,
    total: int,
    callbacks: Optional["IndexingCallbacks"],
    is_interrupted: Callable[[], bool],
    shutdown_executor: Callable[[Executor, str], None],
) -> Tuple[int, int]:
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
            success, was_cached = process_future_result(ctx, result, file_path)

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
    files: Set[str],
    start_time: float,
    callbacks: Optional["IndexingCallbacks"] = None,
    is_interrupted: Optional[Callable[[], bool]] = None,
    shutdown_executor: Optional[Callable[[Executor, str], None]] = None,
) -> int:
    """
    Re-analyze a set of files using parallel processing.

    Returns the number of files successfully analyzed.
    """
    if not files:
        return 0

    from .._core import diagnostics

    if is_interrupted is None:

        def _never_interrupted() -> bool:
            return False

        is_interrupted = _never_interrupted
    if shutdown_executor is None:

        def _default_shutdown(executor: Executor, name: str) -> None:
            try:
                executor.shutdown(wait=False)
            except Exception:
                pass

        shutdown_executor = _default_shutdown

    total = len(files)
    file_list = list(files)

    max_workers = os.cpu_count() or 4
    mp_context, _, msg = create_executor(max_workers)
    diagnostics.debug(msg)

    return _run_analysis_loop(
        ctx, file_list, start_time, total, callbacks, is_interrupted, shutdown_executor, mp_context
    )


def _run_analysis_loop(
    ctx: "IncrementalContext",
    file_list: List[str],
    start_time: float,
    total: int,
    callbacks: Optional["IndexingCallbacks"],
    is_interrupted: Callable[[], bool],
    shutdown_executor: Callable[[Executor, str], None],
    mp_context: Optional[multiprocessing.context.BaseContext],
) -> int:
    """Execute the analysis loop with executor lifecycle management."""
    from .._core import diagnostics
    from .._indexing.worker_pool import _init_worker

    executor: Optional[Executor] = None
    max_workers = os.cpu_count() or 4
    try:
        if mp_context:
            executor = ProcessPoolExecutor(
                max_workers=max_workers, mp_context=mp_context, initializer=_init_worker
            )
        else:
            executor = ProcessPoolExecutor(max_workers=max_workers, initializer=_init_worker)

        future_to_file = submit_tasks(ctx, executor, file_list)
        analyzed, _failed = process_loop(
            ctx,
            executor,
            future_to_file,
            start_time,
            total,
            callbacks,
            is_interrupted,
            shutdown_executor,
        )
    except KeyboardInterrupt:
        diagnostics.info("\nIncremental refresh interrupted")
        if executor is not None:
            shutdown_executor(executor, "Incremental Refresh")
        raise
    finally:
        if executor is not None:
            try:
                executor.shutdown(wait=False)
            except Exception:
                pass

    return analyzed
