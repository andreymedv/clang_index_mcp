"""
Worker pool and parallel execution management for C++ Analyzer.
"""

import atexit
import gc
import multiprocessing
import os
import sys
import time
from concurrent.futures import (
    Executor,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
)
from typing import Any, Dict, List, Optional

# Handle both package and script imports
try:
    from . import diagnostics
    from .indexing_task_spec import IndexingTaskSpec
except ImportError:
    import diagnostics  # type: ignore[no-redef]
    from indexing_task_spec import IndexingTaskSpec  # type: ignore[no-redef]

# Global analyzer instance for each worker process
# This is a process-local global, NOT shared between processes
_worker_analyzer = None


def _cleanup_worker_analyzer():
    """Ensure worker analyzer resources are released on process exit."""
    global _worker_analyzer
    if _worker_analyzer is not None:
        _worker_analyzer.close()
        _worker_analyzer = None


def _process_file_worker(spec: IndexingTaskSpec):
    """
    Worker function for ProcessPoolExecutor-based parallel parsing.

    This is a module-level function (required for pickling) that uses
    a shared, process-local CppAnalyzer instance to parse a single file.
    """
    global _worker_analyzer

    # Lazy import to avoid circular dependency at module level
    from .cpp_analyzer import CppAnalyzer
    from .call_graph import CallGraphAnalyzer

    # Create a single analyzer instance per worker process (process-local)
    if _worker_analyzer is None:
        diagnostics.debug(f"Worker process {os.getpid()}: Creating shared CppAnalyzer instance")
        _worker_analyzer = CppAnalyzer(
            spec.project_root,
            spec.config_file,
            skip_schema_recreation=True,
            use_compile_commands_manager=False,
        )
        # Ensure cleanup is called when the worker process exits
        atexit.register(_cleanup_worker_analyzer)

    assert _worker_analyzer is not None
    context = _worker_analyzer.context
    assert context.compilation_env is not None
    assert context.call_graph_service is not None
    assert context.symbol_store is not None
    assert context.cache_orchestrator is not None

    # Set per-call parameters
    context.compilation_env.include_dependencies = spec.include_dependencies
    # Reset stateful components to prevent data leakage between files
    context.call_graph_service.call_graph_analyzer = CallGraphAnalyzer()

    # Mark this instance as isolated (no shared memory, locks not needed)
    context.concurrency._needs_locking = False

    # Set precomputed compile args
    context.compilation_env._provided_compile_args = spec.compile_args

    # Parse the file
    success, was_cached = _worker_analyzer.index_file(spec.file_path, spec.force)

    # Extract symbols from this file
    symbols: List[Any] = []
    call_sites: List[Any] = []
    processed_headers: Dict[str, str] = {}
    if success:
        for fpath, file_symbols in context.symbol_store.file_index.items():
            symbols.extend(file_symbols)

        # Extract call sites collected during this file's parsing
        call_sites = context.call_graph_service.call_graph_analyzer.get_all_call_sites()

        # Extract header tracking information
        processed_headers = context.cache_orchestrator.header_tracker.get_processed_headers()

    # Clean up worker indexes to prevent memory leaks (Issue #14)
    context.symbol_store.file_index.clear()
    context.symbol_store.class_index.clear()
    context.symbol_store.function_index.clear()
    context.symbol_store.usr_index.clear()
    context.symbol_store.file_hashes.clear()

    # Force garbage collection to free TranslationUnit objects
    gc.collect()

    return (spec.file_path, success, was_cached, symbols, call_sites, processed_headers)


class WorkerPoolManager:
    """Manages a pool of workers for parallel C++ file indexing."""

    def __init__(self, max_workers: int, use_processes: bool = True):
        self.max_workers = max_workers
        self.use_processes = use_processes
        self.executor: Optional[Executor] = None
        self.mp_context: Optional[Any] = None

    def setup(self) -> Executor:
        """Initialize and return the appropriate executor."""
        if self.use_processes:
            try:
                self.mp_context = multiprocessing.get_context("spawn")
                diagnostics.debug(
                    f"Using ProcessPoolExecutor (spawn) with {self.max_workers} workers"
                )
                self.executor = ProcessPoolExecutor(
                    max_workers=self.max_workers, mp_context=self.mp_context
                )
            except Exception as e:
                diagnostics.warning(f"Failed to use 'spawn' context: {e}. Falling back to default.")
                self.executor = ProcessPoolExecutor(max_workers=self.max_workers)
        else:
            diagnostics.debug(f"Using ThreadPoolExecutor with {self.max_workers} workers")
            self.executor = ThreadPoolExecutor(max_workers=self.max_workers)

        return self.executor

    def shutdown(self, name: str = "Indexing"):
        """Cleanly shut down the executor and its workers."""
        if self.executor is None:
            return

        # 1. Identify worker processes (if using ProcessPoolExecutor)
        is_process_pool = isinstance(self.executor, ProcessPoolExecutor)
        workers = []
        if is_process_pool:
            # Safely access _processes which is internal to ProcessPoolExecutor
            processes = getattr(self.executor, "_processes", None)
            workers = list(processes.values()) if processes else []

        # 2. Cancel all pending futures
        self._cancel_executor_futures()

        if not workers:
            diagnostics.info(f"{name} shutdown: waiting for workers to finish...")
            try:
                self.executor.shutdown(wait=True)
                diagnostics.info(f"{name} workers stopped cleanly")
            except Exception as e:
                diagnostics.debug(f"Error during {name} executor shutdown: {e}")
            return

        # 3. Informative logging for ProcessPool
        alive_workers = [w for w in workers if w.is_alive()]
        num_alive = len(alive_workers)

        if num_alive == 0:
            diagnostics.info(f"{name} workers already finished")
            return

        diagnostics.info(f"There are {num_alive} active {name} subprocesses. Terminating...")

        # 4. Graceful wait with progress updates
        self._wait_for_workers(workers, name)

        # 5. Forceful termination if timeout reached
        self._terminate_hanging_workers(workers, name)

        self.executor = None

    def shutdown_nowait(self, name: str = "Indexing"):
        """Fast, non-blocking shutdown used for normal completion paths."""
        if self.executor is None:
            return
        try:
            self.executor.shutdown(wait=False)
            diagnostics.debug(f"{name} shutdown: requested non-blocking executor shutdown")
        except Exception as e:
            diagnostics.debug(f"Error during {name} executor shutdown: {e}")
        finally:
            self.executor = None

    def _cancel_executor_futures(self) -> None:
        """Cancel pending futures in the executor if possible."""
        if self.executor is None:
            return

        try:
            if sys.version_info >= (3, 9):
                self.executor.shutdown(wait=False, cancel_futures=True)
            else:
                self.executor.shutdown(wait=False)
        except Exception:
            self.executor.shutdown(wait=False)

    def _wait_for_workers(self, workers: List[Any], name: str, timeout: float = 5.0):
        """Wait for worker processes to finish cleanly with progress updates."""
        num_workers = len(workers)
        start_wait = time.time()
        last_alive_count = len([w for w in workers if w.is_alive()])

        while time.time() - start_wait < timeout:
            alive_workers = [w for w in workers if w.is_alive()]
            current_alive = len(alive_workers)

            if current_alive == 0:
                diagnostics.info(f"All {num_workers} {name} subprocesses stopped cleanly")
                return

            if current_alive != last_alive_count:
                finished = num_workers - current_alive
                diagnostics.info(
                    f"Shutdown progress: {finished}/{num_workers} subprocesses finished"
                )
                last_alive_count = current_alive

            time.sleep(0.5)

    def _send_sigterm(self, workers: List[Any]):
        """Send SIGTERM to a list of worker processes."""
        for w in workers:
            try:
                if w.is_alive():
                    w.terminate()
            except Exception:
                pass

    def _send_sigkill(self, workers: List[Any]):
        """Send SIGKILL to a list of worker processes."""
        for w in workers:
            try:
                if hasattr(w, "kill") and w.is_alive():
                    w.kill()
            except Exception:
                pass

    def _terminate_hanging_workers(self, workers: List[Any], name: str):
        """Forcefully terminate worker processes that didn't finish cleanly."""
        alive_workers = [w for w in workers if w.is_alive()]
        if not alive_workers:
            return

        diagnostics.warning(
            f"Timeout reached: {len(alive_workers)} subprocesses still running. Killing them..."
        )

        # SIGTERM
        self._send_sigterm(alive_workers)

        time.sleep(0.5)

        # SIGKILL
        still_alive = [w for w in alive_workers if w.is_alive()]
        if still_alive:
            diagnostics.warning(f"Killing {len(still_alive)} remaining subprocesses with SIGKILL")
            self._send_sigkill(still_alive)

        diagnostics.info(f"{name} subprocesses forcefully terminated")

    def __enter__(self) -> Executor:
        """Context manager entry."""
        return self.setup()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.shutdown()
