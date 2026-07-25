"""
Worker pool and parallel execution management for C++ Analyzer.

This module contains only the parent-process side: WorkerPoolManager owns the
ProcessPoolExecutor lifecycle (setup, shutdown, termination). The worker-side
entry points that run inside spawned child processes (_init_worker,
_process_file_worker, and the process-local analyzer instance) live in
``clang_index_mcp/worker_bootstrap.py``, the designated worker-side
composition root.
"""

import multiprocessing
import sys
import time
from concurrent.futures import (
    Executor,
    ProcessPoolExecutor,
)
from typing import Any, List, Optional

# Handle both package and script imports
try:
    from .._core import diagnostics
    from ..worker_bootstrap import _init_worker
except ImportError:
    import diagnostics  # type: ignore[no-redef]
    from worker_bootstrap import _init_worker  # type: ignore[no-redef]


class WorkerPoolManager:
    """Manages a pool of workers for parallel C++ file indexing."""

    def __init__(self, max_workers: int):
        self.max_workers = max_workers
        self.executor: Optional[Executor] = None
        self.mp_context: Optional[Any] = None

    def setup(self) -> Executor:
        """Initialize and return the process pool executor."""
        try:
            self.mp_context = multiprocessing.get_context("spawn")
            diagnostics.debug(f"Using ProcessPoolExecutor (spawn) with {self.max_workers} workers")
            self.executor = ProcessPoolExecutor(
                max_workers=self.max_workers,
                mp_context=self.mp_context,
                initializer=_init_worker,
            )
        except Exception as e:
            diagnostics.warning(f"Failed to use 'spawn' context: {e}. Falling back to default.")
            self.executor = ProcessPoolExecutor(
                max_workers=self.max_workers,
                initializer=_init_worker,
            )

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
