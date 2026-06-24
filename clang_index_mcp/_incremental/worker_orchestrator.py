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
    from ..cpp_analyzer import CppAnalyzer
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
    analyzer: "CppAnalyzer", result: Any, file_path: str
) -> Tuple[bool, bool]:
    """Process the result from a future and merge it into the analyzer."""
    from .._incremental.symbol_merger import merge_symbols

    call_graph_service = analyzer.context.call_graph_service
    assert call_graph_service is not None
    cache_orchestrator = analyzer.context.cache_orchestrator
    assert cache_orchestrator is not None
    symbol_store = analyzer.context.symbol_store
    assert symbol_store is not None

    # ProcessPoolExecutor returns (file_path, success, was_cached, symbols, call_sites, processed_headers)
    _, success, was_cached, symbols, call_sites, processed_headers = result

    if success and symbols:
        merge_symbols(analyzer, symbols)

    if call_sites:
        for cs_dict in call_sites:
            call_graph_service.call_graph_analyzer.add_call(
                cs_dict["caller_usr"],
                cs_dict["callee_usr"],
                cs_dict["file"],
                cs_dict["line"],
                cs_dict.get("column"),
            )

    if processed_headers:
        for header_path, header_hash in processed_headers.items():
            cache_orchestrator.mark_header_completed(header_path, header_hash)

    file_hash = cache_orchestrator._get_file_hash(file_path)
    symbol_store.set_file_hash(file_path, file_hash)

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
            from .._mcp.state_manager import IndexingProgress

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
    analyzer: "CppAnalyzer",
    executor: Executor,
    file_list: List[str],
) -> Dict[Any, str]:
    """Submit re-analysis tasks to the process pool executor."""
    import os

    from .._indexing.indexing_task_spec import IndexingTaskSpec
    from .._indexing.worker_pool import _process_file_worker
    from .._incremental.compile_args_resolver import get_file_compile_args

    project_root = str(analyzer.project_root)
    config_file_str = (
        str(analyzer.project_identity.config_file_path)
        if analyzer.project_identity.config_file_path
        else None
    )
    compilation_env = analyzer.context.compilation_env
    assert compilation_env is not None
    include_dependencies = compilation_env.include_dependencies
    file_compile_args = get_file_compile_args(analyzer, file_list)

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
    analyzer: "CppAnalyzer",
    executor: Executor,
    future_to_file: Dict[Any, str],
    start_time: float,
    total: int,
    callbacks: Optional["IndexingCallbacks"],
) -> Tuple[int, int]:
    """Process results from futures in a loop."""
    from .._core import diagnostics

    analyzed = 0
    failed = 0

    for i, future in enumerate(as_completed(future_to_file)):
        if getattr(analyzer, "_interrupted", False) is True:
            for f in future_to_file:
                f.cancel()
            diagnostics.info("Incremental refresh interrupted by request")
            raise KeyboardInterrupt("Incremental refresh interrupted by request")

        if callbacks and callbacks.wait_for_tools:
            callbacks.wait_for_tools()

        file_path = future_to_file[future]
        try:
            result = future.result()
            success, was_cached = process_future_result(analyzer, result, file_path)

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
    analyzer: "CppAnalyzer",
    files: Set[str],
    start_time: float,
    callbacks: Optional["IndexingCallbacks"] = None,
) -> int:
    """
    Re-analyze a set of files using parallel processing.

    Returns the number of files successfully analyzed.
    """
    if not files:
        return 0

    from .._core import diagnostics

    analyzed = 0
    failed = 0
    total = len(files)
    file_list = list(files)

    max_workers = getattr(analyzer, "max_workers", None)
    if max_workers is None or not isinstance(max_workers, int):
        max_workers = os.cpu_count() or 4

    mp_context, _, msg = create_executor(max_workers)
    diagnostics.debug(msg)

    executor: Optional[Executor] = None
    try:
        if mp_context:
            executor = ProcessPoolExecutor(max_workers=max_workers, mp_context=mp_context)
        else:
            executor = ProcessPoolExecutor(max_workers=max_workers)

        future_to_file = submit_tasks(analyzer, executor, file_list)
        analyzed, failed = process_loop(
            analyzer,
            executor,
            future_to_file,
            start_time,
            total,
            callbacks,
        )
    except KeyboardInterrupt:
        diagnostics.info("\nIncremental refresh interrupted")
        if executor is not None:
            analyzer._shutdown_executor(executor, name="Incremental Refresh")  # type: ignore[attr-defined]
        raise
    finally:
        if executor is not None:
            try:
                executor.shutdown(wait=False)
            except Exception:
                pass

    return analyzed
