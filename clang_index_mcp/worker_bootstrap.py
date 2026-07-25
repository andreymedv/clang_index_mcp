"""
Worker-side composition root for spawned indexing processes.

The functions in this module run INSIDE spawned worker processes, not in the
parent. This module is the designated composition root for workers: a live
CppAnalyzer (libclang handles, SQLite connections) cannot be pickled across
the process boundary, so each worker process rebuilds its own analyzer here.

Keeping the concrete CppAnalyzer construction in this top-level module —
rather than in ``_indexing/worker_pool.py`` — preserves the intended
dependency direction:

    cpp_analyzer (facade) -> composition_root (wiring) -> _indexing (policy)

The CppAnalyzer import is intentionally deferred into process_file_worker():
this module sits on the composition_root import chain (composition_root ->
_indexing.indexing_task_submitter -> worker_bootstrap), so a module-level
import of the facade would create a circular import in the parent process.

The executor lifecycle itself (setup/shutdown) is managed in the parent by
``_indexing/worker_pool.py`` (WorkerPoolManager).
"""

import atexit
import gc
import io
import os
import signal
import sys
from typing import TYPE_CHECKING, Any, Dict, List, Optional

# Handle both package and script imports
try:
    from ._core import diagnostics
    from ._indexing.indexing_task_spec import IndexingTaskSpec
except ImportError:
    import diagnostics  # type: ignore[no-redef]
    from indexing_task_spec import IndexingTaskSpec  # type: ignore[no-redef]

if TYPE_CHECKING:
    from .cpp_analyzer import CppAnalyzer

# Global analyzer instance for each worker process
# This is a process-local global, NOT shared between processes
_worker_analyzer: Optional["CppAnalyzer"] = None


def init_worker():
    """Initializer for each worker process.

    Ignores SIGINT so that Ctrl+C in the parent does not produce
    KeyboardInterrupt tracebacks in workers.  The parent controls
    worker lifetime via SIGTERM/SIGKILL.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def _cleanup_worker_analyzer():
    """Ensure worker analyzer resources are released on process exit.

    Suppresses stderr during close to avoid noisy libclang cleanup
    errors (_CXString.__del__, cursor visitor assertions) that occur
    when the interpreter is shutting down and C-level objects are
    garbage-collected after libclang's shared library may already be
    partially torn down.
    """
    global _worker_analyzer
    if _worker_analyzer is not None:
        saved = sys.stderr
        sys.stderr = io.StringIO()
        try:
            _worker_analyzer.close()
        except Exception:
            pass
        finally:
            sys.stderr = saved
            _worker_analyzer = None


def process_file_worker(spec: IndexingTaskSpec):
    """
    Worker function for ProcessPoolExecutor-based parallel parsing.

    This is a module-level function (required for pickling) that uses
    a shared, process-local CppAnalyzer instance to parse a single file.
    """
    global _worker_analyzer

    # Deferred import: this module is on the composition_root import chain
    # (composition_root -> indexing_task_submitter -> worker_bootstrap), so a
    # module-level import of the facade would be circular in the parent
    # process. This line only ever executes inside a worker process.
    from .cpp_analyzer import CppAnalyzer

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
    context.call_graph_service.call_graph_analyzer.clear()

    # Set precomputed compile args
    context.compilation_env.provided_compile_args = spec.compile_args

    # Parse the file, but do not write cache here; the main process will
    # serialize all per-file cache writes to avoid SQLite contention.
    result = _worker_analyzer.index_file_with_result(spec.file_path, spec.force, write_cache=False)

    # Extract symbols from this file
    symbols: List[Any] = []
    call_sites: List[Any] = []
    processed_headers: Dict[str, str] = {}
    if result.success:
        for fpath, file_symbols in context.symbol_store.iter_file_items():
            symbols.extend(file_symbols)

        # Extract call sites collected during this file's parsing
        call_sites = context.call_graph_service.call_graph_analyzer.get_all_call_sites()

        # Extract header tracking information
        processed_headers = context.cache_orchestrator.get_processed_headers()

    # Clean up worker indexes to prevent memory leaks (Issue #14)
    context.symbol_store.clear_all_indexes()

    # Force garbage collection to free TranslationUnit objects.
    # Wrap in try/except because libclang's __del__ methods may raise
    # if the C library state is inconsistent after a partial parse.
    try:
        gc.collect()
    except Exception:
        pass

    return (
        spec.file_path,
        result.success,
        result.was_cached,
        symbols,
        call_sites,
        processed_headers,
        result.file_hash,
        result.compile_args_hash,
        result.error_message,
        result.retry_count,
    )
