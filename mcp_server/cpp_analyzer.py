"""
Pure Python C++ Analyzer using libclang

This module provides C++ code analysis functionality using libclang bindings.
It's slower than the C++ implementation but more reliable and easier to debug.
"""

import sys
import time
from concurrent.futures import as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .cache_manager import CacheManager
from .cache_orchestrator import CacheOrchestrator
from .call_graph_service import CallGraphService
from .cancellation_coordinator import CancellationCoordinator
from .clang_parser import ClangParser
from .compilation_environment import CompilationEnvironment
from .compile_commands_manager import CompileCommandsManager
from .concurrency_context import ConcurrencyContext
from .cpp_analyzer_config import CppAnalyzerConfig
from .execution_config import ExecutionConfig
from .indexing_pipeline import SingleFileIndexingPipeline
from .indexing_progress_reporter import IndexingProgressReporter
from .indexing_task_submitter import IndexingTaskSubmitter
from .project_identity import ProjectIdentity
from .worker_result_merger import WorkerResultMerger
from .query_engine import QueryEngine
from .refresh_pipeline import RefreshPipeline
from .symbol_extractor import SymbolExtractor
from .symbol_index_store import SymbolIndexStore
from .symbol_info import (
    CLASS_KINDS,
    SymbolInfo,
)

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics  # type: ignore[no-redef]

try:
    from clang.cindex import Index
except ImportError:
    diagnostics.fatal("clang package not found. Install with: pip install libclang")
    sys.exit(1)


class CppAnalyzer:
    """
    Pure Python C++ code analyzer using libclang.

    This class provides code analysis functionality including:
    - Class and struct discovery
    - Function and method discovery
    - Symbol search with regex patterns
    - File-based filtering
    """

    def __init__(
        self,
        project_root: str,
        config_file: Optional[str] = None,
        skip_schema_recreation: bool = False,
        use_compile_commands_manager: bool = True,
    ):
        """
        Initialize C++ Analyzer.

        Args:
            project_root: Path to project source directory
            config_file: Optional path to configuration file for project identity
            skip_schema_recreation: If True, skip database recreation on schema mismatch.
                                   Used by worker processes to avoid race conditions.
                                   Workers should rely on main process to ensure schema is current.
            use_compile_commands_manager: If False, skip CompileCommandsManager initialization.
                                         Used by worker processes that receive precomputed compile args (Task 3.2).

        Note:
            Project identity is determined by (source_directory, config_file) pair.
            Different config_file values create separate cache directories.
        """
        self.project_root = Path(project_root).resolve()
        self.index = Index.create()
        self._skip_schema_recreation = skip_schema_recreation

        # Create project identity
        config_path = Path(config_file).resolve() if config_file else None
        self.project_identity = ProjectIdentity(self.project_root, config_path)

        # Load project configuration
        self.config = CppAnalyzerConfig(self.project_root, config_path=config_path)

        # Initialize core components
        self.clang_parser = ClangParser(self)
        self.symbol_extractor = SymbolExtractor(self)

        # Initialize call graph service (manages CallGraphAnalyzer + DependencyGraphBuilder)
        self.call_graph_service = CallGraphService(self)

        # Initialize symbol index store (manages class/function/file/USR indexes)
        self.symbol_store = SymbolIndexStore(self)

        # Concurrency context (locks, thread-local buffers, locking strategy)
        self.concurrency = ConcurrencyContext()

        # Cancellation support
        self.cancellation = CancellationCoordinator()

        # Execution configuration (worker pool strategy)
        self.execution = ExecutionConfig(config_max_workers=self.config.get_max_workers())

        # Progress reporter (extracted helper for indexing/refresh progress)
        self.progress_reporter = IndexingProgressReporter()

        # Initialize cache manager with project identity
        # Pass skip_schema_recreation for worker processes to avoid race conditions
        self.cache_manager = CacheManager(
            self.project_identity, skip_schema_recreation=self._skip_schema_recreation
        )

        # Initialize compilation environment (manages file scanner, compile commands, etc.)
        self.compilation_env = CompilationEnvironment(self)

        # Task submitter (extracted helper for submitting work to the executor)
        self.task_submitter = IndexingTaskSubmitter(
            self.project_root,
            self.project_identity,
            self.execution,
            self.compilation_env,
            self.index_file,
        )

        # Initialize query engine (manages search, hierarchy, and analysis operations)
        self.query_engine = QueryEngine(self)

        # Wire call graph service to SQLite cache backend
        self.call_graph_service.setup_cache_backend()

        # Keep cache_dir for compatibility
        self.cache_dir = self.cache_manager.cache_dir

        # Initialize cache orchestrator (manages cache operations and header tracking)
        self.cache_orchestrator = CacheOrchestrator(self)

        # Worker result merger (extracted helper for merging worker results)
        self.worker_result_merger = WorkerResultMerger(
            self.concurrency,
            self.symbol_store,
            self.call_graph_service,
            self.cache_orchestrator,
        )

        # Single-file indexing pipeline
        self.indexing_pipeline = SingleFileIndexingPipeline(
            self.clang_parser,
            self.symbol_extractor,
            self.compilation_env,
            self.cache_orchestrator,
            self.cache_manager,
            self.concurrency,
            self.symbol_store,
        )

        # Refresh pipeline
        self.refresh_pipeline = RefreshPipeline(
            self.compilation_env,
            self.execution,
            self.cache_manager,
            self.cache_orchestrator,
            self.symbol_extractor,
            self.symbol_store,
            self.task_submitter,
            self.worker_result_merger,
            self.progress_reporter,
        )

        # Task 3.2: Initialize compile commands manager only if needed
        # Workers skip this to save ~6-10 GB memory by using precomputed args from main process
        if use_compile_commands_manager:
            compile_commands_config = self.config.get_compile_commands_config()
            self.compilation_env.compile_commands_manager = CompileCommandsManager(
                self.project_root, compile_commands_config, cache_dir=self.cache_manager.cache_dir
            )

        # Initialize dependency graph builder for incremental analysis
        self.call_graph_service.init_dependency_graph()

        # Calculate compile_commands.json hash and restore header tracking
        self.cache_orchestrator._calculate_compile_commands_hash()
        self.cache_orchestrator._restore_or_reset_header_tracking()

        diagnostics.debug(f"CppAnalyzer initialized for project: {self.project_root}")
        diagnostics.debug(
            f"Concurrency mode: {'ProcessPool (GIL bypass)' if self.execution.use_processes else 'ThreadPool'} with {self.max_workers} workers"
        )

        # Print compile commands configuration status
        # Task 3.2: Skip if CompileCommandsManager not initialized (worker mode)
        if self.compile_commands_manager is not None:
            if self.compile_commands_manager.enabled:
                compile_commands_config = self.config.get_compile_commands_config()
                cc_path = self.project_root / compile_commands_config["compile_commands_path"]
                if cc_path.exists():
                    # This message will be followed by actual load message from CompileCommandsManager
                    diagnostics.debug(
                        f"Compile commands enabled: using {compile_commands_config['compile_commands_path']}"
                    )
                else:
                    diagnostics.debug(
                        f"Compile commands enabled: {compile_commands_config['compile_commands_path']} not found, will use fallback args"
                    )
            else:
                diagnostics.debug("Compile commands disabled in configuration")
        else:
            diagnostics.debug("Worker mode: using precomputed compile args from main process")

    def interrupt(self):
        """
        Interrupt any ongoing indexing operations.
        Sets the interrupted flag which is checked by indexing loops.
        """
        self.cancellation.interrupt()

    def _is_interrupted(self) -> bool:
        """Check if indexing has been interrupted."""
        return self.cancellation.is_interrupted()

    def close(self):
        """
        Close the analyzer and release all resources.

        This should be called when the CppAnalyzer is no longer needed
        to properly close database connections and avoid resource leaks.
        """
        if hasattr(self, "cache_manager") and self.cache_manager is not None:
            self.cache_manager.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False

    def __del__(self):
        """Destructor to ensure resources are released on garbage collection."""
        # During Python shutdown, modules may be None. Suppress all errors.
        try:
            # Check if we're shutting down - skip cleanup if so
            if sys is None or sys.meta_path is None:
                return
            self.close()
        except (ImportError, AttributeError, TypeError):
            # Suppress errors during shutdown - resources will be cleaned up by OS
            pass

    @property
    def call_graph_analyzer(self):
        """Backward-compatible access to the CallGraphAnalyzer instance."""
        return self.call_graph_service.call_graph_analyzer

    @call_graph_analyzer.setter
    def call_graph_analyzer(self, value):
        """Allow resetting the CallGraphAnalyzer (used by worker processes)."""
        self.call_graph_service.call_graph_analyzer = value

    @property
    def dependency_graph(self):
        """Backward-compatible access to the DependencyGraphBuilder."""
        return self.call_graph_service.dependency_graph

    @property
    def class_index(self):
        """Backward-compatible access to the class index."""
        return self.symbol_store.class_index

    @property
    def function_index(self):
        """Backward-compatible access to the function index."""
        return self.symbol_store.function_index

    @property
    def file_index(self):
        """Backward-compatible access to the file index."""
        return self.symbol_store.file_index

    @property
    def usr_index(self):
        """Backward-compatible access to the USR index."""
        return self.symbol_store.usr_index

    @property
    def file_hashes(self):
        """Backward-compatible access to file hashes."""
        return self.symbol_store.file_hashes

    @property
    def indexed_file_count(self):
        """Backward-compatible access to indexed file count."""
        return self.symbol_store.indexed_file_count

    @indexed_file_count.setter
    def indexed_file_count(self, value):
        """Allow setting indexed file count (used by finalize_indexing)."""
        self.symbol_store.indexed_file_count = value

    @property
    def compile_commands_manager(self):
        """Backward-compatible access to the compile commands manager."""
        return self.compilation_env.compile_commands_manager

    @property
    def file_scanner(self):
        """Backward-compatible access to the file scanner."""
        return self.compilation_env.file_scanner

    @property
    def include_dependencies(self):
        """Backward-compatible access to include_dependencies setting."""
        return self.compilation_env.include_dependencies

    @include_dependencies.setter
    def include_dependencies(self, value):
        """Allow setting include_dependencies (used by worker processes)."""
        self.compilation_env.include_dependencies = value

    @property
    def max_parse_retries(self):
        """Backward-compatible access to max_parse_retries setting."""
        return self.compilation_env.max_parse_retries

    @property
    def _provided_compile_args(self):
        """Backward-compatible access to precomputed compile args."""
        return self.compilation_env._provided_compile_args

    @_provided_compile_args.setter
    def _provided_compile_args(self, value):
        """Allow setting precomputed compile args (used by worker processes)."""
        self.compilation_env._provided_compile_args = value

    @property
    def cache_loaded(self):
        """Backward-compatible access to cache_loaded flag."""
        return self.cache_orchestrator.cache_loaded

    @property
    def last_index_time(self):
        """Backward-compatible access to last_index_time."""
        return self.cache_orchestrator.last_index_time

    @last_index_time.setter
    def last_index_time(self, value):
        """Allow setting last_index_time."""
        self.cache_orchestrator.last_index_time = value

    @property
    def compile_commands_hash(self):
        """Backward-compatible access to compile_commands_hash."""
        return self.cache_orchestrator.compile_commands_hash

    @compile_commands_hash.setter
    def compile_commands_hash(self, value):
        """Allow setting compile_commands_hash."""
        self.cache_orchestrator.compile_commands_hash = value

    @property
    def header_tracker(self):
        """Backward-compatible access to header_tracker."""
        return self.cache_orchestrator.header_tracker

    @property
    def search_engine(self):
        """Backward-compatible access to search_engine."""
        return self.query_engine.search_engine

    @property
    def smart_fallback(self):
        """Backward-compatible access to smart_fallback."""
        return self.query_engine.smart_fallback

    @property
    def _last_fallback(self):
        """Backward-compatible access to _last_fallback."""
        return self.query_engine._last_fallback

    @_last_fallback.setter
    def _last_fallback(self, value):
        """Allow setting _last_fallback."""
        self.query_engine._last_fallback = value

    @property
    def max_workers(self):
        """Backward-compatible access to max_workers."""
        return self.execution.max_workers

    @property
    def use_processes(self):
        """Backward-compatible access to use_processes."""
        return self.execution.use_processes

    @property
    def worker_pool(self):
        """Backward-compatible access to worker_pool."""
        return self.execution.worker_pool

    @property
    def index_lock(self):
        """Backward-compatible access to index_lock."""
        return self.concurrency.index_lock

    @property
    def _needs_locking(self):
        """Backward-compatible access to _needs_locking."""
        return self.concurrency._needs_locking

    @_needs_locking.setter
    def _needs_locking(self, value):
        """Allow setting _needs_locking (used by worker processes)."""
        self.concurrency._needs_locking = value

    def _get_file_hash(self, file_path: str) -> str:
        """Get hash of file contents for change detection (delegates to cache_orchestrator)."""
        return self.cache_orchestrator._get_file_hash(file_path)

    def _calculate_compile_commands_hash(self):
        """Calculate and store MD5 hash of compile_commands.json (delegates to cache_orchestrator)."""
        self.cache_orchestrator._calculate_compile_commands_hash()

    def _restore_or_reset_header_tracking(self):
        """Restore or reset header tracking (delegates to cache_orchestrator)."""
        self.cache_orchestrator._restore_or_reset_header_tracking()

    def _save_header_tracking(self):
        """Save header tracking state (delegates to cache_orchestrator)."""
        self.cache_orchestrator._save_header_tracking()

    def _save_file_cache(
        self,
        file_path: str,
        symbols: List[SymbolInfo],
        file_hash: str,
        compile_args_hash: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        retry_count: int = 0,
    ):
        """Save parsed symbols for a single file to cache (delegates to cache_orchestrator)."""
        self.cache_orchestrator._save_file_cache(
            file_path, symbols, file_hash, compile_args_hash, success, error_message, retry_count
        )

    def _load_file_cache(
        self, file_path: str, current_hash: str, compile_args_hash: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Load cached data for a file (delegates to cache_orchestrator)."""
        return self.cache_orchestrator._load_file_cache(file_path, current_hash, compile_args_hash)

    def _try_load_cached_index(
        self, file_path: str, current_hash: str, compile_args_hash: str, force: bool
    ) -> Optional[Tuple[bool, bool]]:
        """Try to load index from per-file cache (delegates to cache_orchestrator)."""
        return self.cache_orchestrator._try_load_cached_index(
            file_path, current_hash, compile_args_hash, force
        )

    def _handle_cache_initial_index(self, force: bool) -> Optional[int]:
        """Try to load from cache if not forcing (delegates to cache_orchestrator)."""
        return self.cache_orchestrator._handle_cache_initial_index(force)

    def _save_cache(self):
        """Save index to cache file (delegates to cache_orchestrator)."""
        self.cache_orchestrator._save_cache()

    def _load_cache(self) -> bool:
        """Load index from cache file (delegates to cache_orchestrator)."""
        return self.cache_orchestrator._load_cache()

    def _save_progress_summary(
        self, indexed_count: int, total_files: int, cache_hits: int, failed_count: int = 0
    ):
        """Save a summary of indexing progress (delegates to cache_orchestrator)."""
        self.cache_orchestrator._save_progress_summary(
            indexed_count, total_files, cache_hits, failed_count
        )

    def _is_project_file(self, file_path: str) -> bool:
        """Check if a file is a project file (delegates to compilation_env)."""
        return self.compilation_env._is_project_file(file_path)

    def _should_skip_file(self, file_path: str) -> bool:
        """Check if file should be skipped (delegates to compilation_env)."""
        return self.compilation_env._should_skip_file(file_path)

    def get_compile_commands_stats(self) -> Dict[str, Any]:
        """Get compile commands statistics (delegates to compilation_env)."""
        return self.compilation_env.get_compile_commands_stats()

    def _find_cpp_files(self, include_dependencies: bool = False) -> List[str]:
        """Find all C++ files in the project (delegates to compilation_env)."""
        return self.compilation_env._find_cpp_files(include_dependencies)

    def _extract_template_call_info(self, referenced, called_usr: str):
        """Extract display_name and project-type template args from a template call."""
        return self.symbol_extractor._extract_template_call_info(referenced, called_usr)

    def _get_lock(self):
        """
        Return appropriate lock based on execution context.

        Returns:
            - self.index_lock: When locks are needed (ThreadPoolExecutor or shared instance)
            - self._no_op_lock: When locks are unnecessary (ProcessPoolExecutor worker)

        Performance optimization:
        In ProcessPoolExecutor mode, each worker process has isolated memory,
        so locking is unnecessary overhead. This method returns a no-op lock
        to skip synchronization in that case while maintaining correctness
        in ThreadPoolExecutor mode where memory is actually shared.
        """
        return self.concurrency.get_lock()

    def _get_thread_index(self) -> Index:
        """Return a thread-local libclang Index instance."""
        return self.clang_parser._get_thread_index()

    def _init_thread_local_buffers(self):
        """Initialize thread-local buffers for collecting symbols during parsing."""
        self.concurrency.init_thread_local_buffers()

    def _get_thread_local_buffers(self):
        """Get thread-local buffers, initializing if needed."""
        return self.concurrency.get_thread_local_buffers()

    def _bulk_write_symbols(self):
        """
        Bulk write collected symbols to shared indexes with a single lock acquisition.

        This method takes all symbols collected in thread-local buffers during parsing
        and adds them to the shared indexes in one atomic operation, dramatically
        reducing lock contention compared to per-symbol locking.

        Returns:
            Number of symbols actually added (after deduplication)
        """
        symbols_buffer, calls_buffer, aliases_buffer = self._get_thread_local_buffers()

        if not symbols_buffer and not calls_buffer and not aliases_buffer:
            return 0

        added_count = 0

        # Single lock acquisition for all symbols (conditional based on execution mode)
        with self._get_lock():
            # Add all collected symbols
            for info in symbols_buffer:
                # USR-based deduplication with definition-wins logic (Phase 1)
                if info.usr and info.usr in self.usr_index:
                    existing_symbol = self.usr_index[info.usr]
                    resolved_info = self.symbol_store._handle_symbol_definition_wins(
                        info, existing_symbol
                    )
                    if resolved_info is None:
                        continue
                    info = resolved_info

                # New symbol or replacement - add to all indexes
                if info.kind in CLASS_KINDS:
                    self.class_index[info.name].append(info)
                else:
                    self.function_index[info.name].append(info)

                if info.usr:
                    self.usr_index[info.usr] = info

                self.symbol_store._add_symbol_to_file_index(info)
                added_count += 1

            # Add all collected call relationships (Phase 3: now includes location)
            self.call_graph_service._process_call_buffer(calls_buffer)

            # Add all collected type aliases (Phase 1.3: Type Alias Tracking)
            if aliases_buffer:
                diagnostics.debug(f"Processing {len(aliases_buffer)} type aliases from buffer")
                saved_count = self.cache_manager.save_type_aliases_batch(aliases_buffer)
                diagnostics.debug(f"Saved {saved_count} type aliases to cache")

        # Clear buffers for next use
        symbols_buffer.clear()
        calls_buffer.clear()
        aliases_buffer.clear()

        return added_count

    def _extract_diagnostics(self, tu: Any) -> Tuple[List[Any], List[Any]]:
        """Extract diagnostics from translation unit."""
        return self.clang_parser._extract_diagnostics(tu)

    def _build_human_readable_signature(self, cursor: Any) -> str:
        """Build human readable signature."""
        return self.symbol_extractor._build_human_readable_signature(cursor)

    def _get_base_classes(self, cursor: Any) -> List[str]:
        """Get base classes for a class/struct."""
        return self.symbol_extractor._get_base_classes(cursor)

    def _extract_documentation(self, cursor: Any) -> dict:
        """Extract documentation."""
        return self.symbol_extractor._extract_documentation(cursor)

    def _get_return_type(self, cursor: Any) -> str:
        """Get return type."""
        return self.symbol_extractor._get_return_type(cursor)

    def _detect_template_specialization(self, cursor: Any) -> bool:
        """Detect if cursor is a template specialization."""
        return self.symbol_extractor._detect_template_specialization(cursor)

    def _extract_alias_info(self, cursor: Any) -> dict:
        """Extract type alias info."""
        return self.symbol_extractor._extract_alias_info(cursor)

    def _get_primary_template_usr(self, cursor: Any) -> Optional[str]:
        """Get primary template USR."""
        return self.symbol_extractor._get_primary_template_usr(cursor)

    def _resolve_instantiation_base_classes(
        self, cursor: Any, primary_template_usr: str
    ) -> List[str]:
        """Resolve base classes for an instantiation."""
        return self.symbol_extractor._resolve_instantiation_base_classes(
            cursor, primary_template_usr
        )

    def _process_deferred_instantiation(self, info: SymbolInfo) -> bool:
        """Process a single deferred instantiation and return True if resolved."""
        return self.symbol_extractor._process_deferred_instantiation(info)

    def _resolve_deferred_instantiation_bases(self) -> int:
        """Resolve base_classes for template instantiations that couldn't be resolved during parsing."""
        return self.symbol_extractor._resolve_deferred_instantiation_bases()

    def _extract_template_base_name_from_usr(self, usr: str) -> Optional[str]:
        """Extract the base template name from a USR (delegates to SymbolIndexStore)."""
        return SymbolIndexStore.extract_template_base_name_from_usr(usr)

    def _find_template_specializations(self, base_name: str) -> List[SymbolInfo]:
        """Find all specializations of a template by base name (delegates to SymbolIndexStore)."""
        return self.symbol_store.find_template_specializations(base_name)

    def _process_cursor(
        self,
        cursor: Any,
        should_extract_from_file: Optional[Callable[[str], bool]] = None,
        parent_class: str = "",
        parent_function_usr: str = "",
    ) -> None:
        """Process a cursor and its children, extracting symbols based on file filter."""
        self.symbol_extractor._process_cursor(
            cursor, should_extract_from_file, parent_class, parent_function_usr
        )

    def _index_translation_unit(self, tu, source_file: str) -> Dict[str, Any]:
        """Process translation unit, extracting symbols from source and project headers."""
        return self.symbol_extractor._index_translation_unit(tu, source_file)

    def index_file(self, file_path: str, force: bool = False) -> tuple[bool, bool]:
        """Index a single C++ file.

        Returns:
            (success, was_cached) - success indicates if indexing succeeded,
                                   was_cached indicates if it was loaded from cache
        """
        return self.indexing_pipeline.index_file(file_path, force)

    def _prepare_indexing_files(self, include_dependencies: bool) -> List[str]:
        """Find C++ files to index and log compilation environment."""
        diagnostics.debug(f"Finding C++ files (include_dependencies={include_dependencies})...")
        files = self.compilation_env._find_cpp_files(include_dependencies=include_dependencies)

        if not files:
            diagnostics.warning("No C++ files found in project")
            return []

        diagnostics.debug(f"Found {len(files)} C++ files to index")
        self.compilation_env._log_compilation_environment(files)
        return files

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
        self.indexed_file_count = indexed_count
        self.last_index_time = time.time() - start_time

        if is_terminal:
            print("", file=sys.stderr)

        with self.index_lock:
            class_count = sum(len(infos) for infos in self.class_index.values())
            function_count = sum(len(infos) for infos in self.function_index.values())

        diagnostics.info(f"Indexing complete in {self.last_index_time:.2f}s")
        diagnostics.info(
            f"Indexed {indexed_count}/{total_files} files successfully "
            f"({cache_hits} from cache, {failed_count} failed)"
        )
        diagnostics.info(f"Found {class_count} classes, {function_count} functions")

        if failed_count > 0:
            diagnostics.info(
                f"Note: {failed_count} files failed to parse - this is normal for complex projects"
            )

        self._resolve_deferred_instantiation_bases()
        self._save_cache()
        self._save_progress_summary(indexed_count, total_files, cache_hits, failed_count)
        self._save_header_tracking()
        self.cache_manager.backend.rebuild_fts()

        return indexed_count

    @staticmethod
    def _update_indexing_counts(success: bool, was_cached: bool) -> Tuple[int, int, int]:
        """Return (indexed_delta, cache_delta, failed_delta) for a single result."""
        if success:
            return 1, 1 if was_cached else 0, 0
        return 0, 0, 1

    def index_project(
        self,
        force: bool = False,
        include_dependencies: bool = True,
        progress_callback: Optional[Callable] = None,
        wait_for_tools_callback: Optional[Callable[[], None]] = None,
    ) -> int:
        """
        Index all C++ files in the project

        Args:
            force: Force re-indexing even if cache exists
            include_dependencies: Include dependency files in indexing
            progress_callback: Optional callback for progress updates.
                             Called with IndexingProgress object during indexing.

        Returns:
            Number of files indexed
        """
        start_time = time.time()
        self.include_dependencies = include_dependencies

        cached_count = self._handle_cache_initial_index(force)
        if cached_count is not None:
            return cached_count

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
                if self._is_interrupted():
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

    def pop_last_fallback(self):
        """Return and clear the last fallback result (delegates to query_engine)."""
        return self.query_engine.pop_last_fallback()

    def search_classes(
        self,
        pattern: str,
        project_only: bool = True,
        file_name: Optional[str] = None,
        namespace: Optional[str] = None,
        max_results: Optional[int] = None,
        include_base_classes: bool = True,
    ):
        """Search for classes matching pattern (delegates to query_engine)."""
        return self.query_engine.search_classes(
            pattern, project_only, file_name, namespace, max_results, include_base_classes
        )

    def search_functions(
        self,
        pattern: str,
        project_only: bool = True,
        class_name: Optional[str] = None,
        file_name: Optional[str] = None,
        namespace: Optional[str] = None,
        max_results: Optional[int] = None,
        signature_pattern: Optional[str] = None,
        include_attributes: bool = False,
    ):
        """Search for functions matching pattern (delegates to query_engine)."""
        return self.query_engine.search_functions(
            pattern,
            project_only,
            class_name,
            file_name,
            namespace,
            max_results,
            signature_pattern,
            include_attributes,
        )

    def get_stats(self) -> Dict[str, int]:
        """Get indexer statistics (delegates to query_engine)."""
        return self.query_engine.get_stats()

    def refresh_if_needed(
        self,
        progress_callback: Optional[Callable] = None,
        wait_for_tools_callback: Optional[Callable[[], None]] = None,
    ) -> int:
        """
        Refresh index for changed files and remove deleted files.

        Args:
            progress_callback: Optional callback for progress updates
            wait_for_tools_callback: Optional callback to wait for tool availability

        Returns:
            Number of files refreshed
        """
        return self.refresh_pipeline.refresh_if_needed(
            self.include_dependencies,
            self.compile_commands_manager,
            progress_callback,
            wait_for_tools_callback,
        )

    def get_class_info(self, class_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific class (delegates to query_engine)."""
        return self.query_engine.get_class_info(class_name)

    def get_function_signature(
        self, function_name: str, class_name: Optional[str] = None
    ) -> List[str]:
        """Get signature details for functions (delegates to query_engine)."""
        return self.query_engine.get_function_signature(function_name, class_name)

    def get_type_alias_info(self, type_name: str) -> Dict[str, Any]:
        """Get comprehensive type alias information (delegates to query_engine)."""
        return self.query_engine.get_type_alias_info(type_name)

    def search_symbols(
        self,
        pattern: str,
        project_only: bool = True,
        symbol_types: Optional[List[str]] = None,
        namespace: Optional[str] = None,
        max_results: Optional[int] = None,
        signature_pattern: Optional[str] = None,
    ):
        """Search for all symbols (classes and functions) matching pattern (delegates to query_engine)."""
        return self.query_engine.search_symbols(
            pattern, project_only, symbol_types, namespace, max_results, signature_pattern
        )

    def get_derived_classes(
        self, class_name: str, project_only: bool = True
    ) -> List[Dict[str, Any]]:
        """Get all classes that derive from the given class (delegates to query_engine)."""
        return self.query_engine.get_derived_classes(class_name, project_only)

    def _check_template_param_inheritance(self, base_class: str, target_class: str) -> bool:
        """Check indirect inheritance through template parameters (delegates to query_engine)."""
        return self.query_engine._check_template_param_inheritance(base_class, target_class)

    def _get_template_param_inheritance_indices(self, template_name: str) -> List[int]:
        """Get template parameter indices that a template inherits from (delegates to query_engine)."""
        return self.query_engine._get_template_param_inheritance_indices(template_name)

    def _parse_template_args(self, args_str: str) -> List[str]:
        """Parse template arguments from a string (delegates to query_engine)."""
        return self.query_engine._parse_template_args(args_str)

    def get_class_hierarchy(
        self,
        class_name: str,
        max_nodes: Optional[int] = 200,
        max_depth: Optional[int] = None,
        direction: str = "both",
    ) -> Dict[str, Any]:
        """Get the inheritance graph for a class as a flat adjacency list (delegates to query_engine)."""
        return self.query_engine.get_class_hierarchy(class_name, max_nodes, max_depth, direction)

    def find_incoming_calls(
        self,
        function_name: str,
        class_name: str = "",
        include_call_sites: bool = True,
        project_only: bool = True,
    ) -> Dict[str, Any]:
        """Find all functions that call the specified function."""
        return self.call_graph_service.find_incoming_calls(
            function_name, class_name, include_call_sites, project_only
        )

    def find_callees(
        self, function_name: str, class_name: str = "", project_only: bool = True
    ) -> Dict[str, Any]:
        """Find all functions called by the specified function."""
        return self.call_graph_service.find_callees(function_name, class_name, project_only)

    def get_call_sites(self, function_name: str, class_name: str = "") -> List[Dict[str, Any]]:
        """Get all call sites FROM a specific function."""
        return self.call_graph_service.get_call_sites(function_name, class_name)

    def get_call_path(
        self, from_function: str, to_function: str, max_depth: int = 10
    ) -> List[List[str]]:
        """Find call paths from one function to another using BFS."""
        return self.call_graph_service.get_call_path(from_function, to_function, max_depth)

    def find_in_file(self, file_path: str, pattern: str) -> Dict[str, Any]:
        """Search for symbols within a specific file or files matching a glob pattern (delegates to query_engine)."""
        return self.query_engine.find_in_file(file_path, pattern)

    async def get_files_containing_symbol(
        self, symbol_name: str, symbol_kind: Optional[str] = None, project_only: bool = True
    ) -> Dict[str, Any]:
        """Get all files that contain references to or define a symbol (delegates to query_engine)."""
        return await self.query_engine.get_files_containing_symbol(
            symbol_name, symbol_kind, project_only
        )

    def get_parse_errors(
        self, limit: Optional[int] = None, file_path_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get parse errors from the error log (for developer analysis).

        Args:
            limit: Maximum number of errors to return (most recent first)
            file_path_filter: Only return errors for files matching this path

        Returns:
            List of error entries
        """
        return self.cache_manager.get_parse_errors(limit, file_path_filter)

    def get_error_summary(self) -> Dict[str, Any]:
        """Get a summary of parse errors for developer analysis.

        Returns:
            Dict with error statistics and recent errors
        """
        return self.cache_manager.get_error_summary()

    def clear_error_log(self, older_than_days: Optional[int] = None) -> int:
        """Clear the error log, optionally keeping recent errors.

        Args:
            older_than_days: If specified, only clear errors older than this many days

        Returns:
            Number of errors cleared
        """
        return self.cache_manager.clear_error_log(older_than_days)


# Create factory function for compatibility
def create_analyzer(project_root: str) -> CppAnalyzer:
    """Factory function to create a C++ analyzer"""
    return CppAnalyzer(project_root)


# Test function
if __name__ == "__main__":
    diagnostics.debug("Testing Python CppAnalyzer...")
    analyzer = CppAnalyzer(".")

    # Try to load from cache first
    if not analyzer._load_cache():
        analyzer.index_project()

    stats = analyzer.get_stats()
    diagnostics.debug(f"Stats: {stats}")

    classes = analyzer.search_classes(".*", project_only=True)
    diagnostics.debug(f"Found {len(classes)} project classes")

    functions = analyzer.search_functions(".*", project_only=True)
    diagnostics.debug(f"Found {len(functions)} project functions")
