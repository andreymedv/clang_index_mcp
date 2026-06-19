"""
Pure Python C++ Analyzer using libclang

This module provides C++ code analysis functionality using libclang bindings.
It's slower than the C++ implementation but more reliable and easier to debug.
"""

import os
import sys
import threading
import time
from concurrent.futures import (
    Executor,
    Future,
    as_completed,
)
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .cache_manager import CacheManager
from .cache_orchestrator import CacheOrchestrator
from .call_graph_service import CallGraphService
from .clang_parser import ClangParser
from .compilation_environment import CompilationEnvironment
from .compile_commands_manager import CompileCommandsManager
from .cpp_analyzer_config import CppAnalyzerConfig
from .project_identity import ProjectIdentity
from .query_engine import QueryEngine
from .state_manager import IndexingProgress
from .symbol_extractor import SymbolExtractor
from .symbol_index_store import SymbolIndexStore
from .symbol_info import (
    CLASS_KINDS,
    SymbolInfo,
)
from .worker_pool import WorkerPoolManager, _process_file_worker

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics  # type: ignore[no-redef]

try:
    from clang.cindex import Index, TranslationUnit
except ImportError:
    diagnostics.fatal("clang package not found. Install with: pip install libclang")
    sys.exit(1)


class _NoOpLock:
    """A no-op context manager that doesn't actually acquire any lock."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


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

        # Threading/Processing
        self.index_lock = threading.RLock()

        # Track indexed files
        self.translation_units: Dict[str, TranslationUnit] = {}
        self._no_op_lock = _NoOpLock()  # Reusable no-op lock for isolated processes
        self._thread_local = threading.local()

        # Cancellation support
        self._interrupted = False
        self._interrupt_lock = threading.Lock()

        cpu_count = os.cpu_count() or 1

        # Determine max_workers from config or default to cpu_count
        # User can limit workers to reduce memory usage (~1.2 GB per worker on large projects)
        config_max_workers = self.config.get_max_workers()
        if config_max_workers is not None:
            self.max_workers = min(config_max_workers, cpu_count)
            diagnostics.info(
                f"Using max_workers={self.max_workers} from config (cpu_count={cpu_count})"
            )
        else:
            self.max_workers = cpu_count

        # Use ProcessPoolExecutor by default to bypass Python's GIL
        # Can be overridden via environment variable
        self.use_processes = os.environ.get("CPP_ANALYZER_USE_THREADS", "").lower() != "true"

        # Initialize worker pool manager
        self.worker_pool = WorkerPoolManager(self.max_workers, self.use_processes)

        # Initialize helper components (Phase 2 refactor)
        self.clang_parser = ClangParser(self)
        self.symbol_extractor = SymbolExtractor(self)

        # Locking strategy:
        # - True (default): Use locks for thread safety (ThreadPoolExecutor or shared instance)
        # - False: Skip locks for performance (ProcessPoolExecutor worker with isolated memory)
        # This flag is set to False by _process_file_worker for worker processes
        self._needs_locking = True

        # Initialize cache manager with project identity
        # Pass skip_schema_recreation for worker processes to avoid race conditions
        self.cache_manager = CacheManager(
            self.project_identity, skip_schema_recreation=self._skip_schema_recreation
        )

        # Initialize compilation environment (manages file scanner, compile commands, etc.)
        self.compilation_env = CompilationEnvironment(self)

        # Initialize query engine (manages search, hierarchy, and analysis operations)
        self.query_engine = QueryEngine(self)

        # Wire call graph service to SQLite cache backend
        self.call_graph_service.setup_cache_backend()

        # Keep cache_dir for compatibility
        self.cache_dir = self.cache_manager.cache_dir

        # Initialize cache orchestrator (manages cache operations and header tracking)
        self.cache_orchestrator = CacheOrchestrator(self)

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
            f"Concurrency mode: {'ProcessPool (GIL bypass)' if self.use_processes else 'ThreadPool'} with {self.max_workers} workers"
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
        with self._interrupt_lock:
            self._interrupted = True
        diagnostics.info("Indexing interrupt requested")

    def _is_interrupted(self) -> bool:
        """Check if indexing has been interrupted."""
        with self._interrupt_lock:
            return self._interrupted

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
        return self.index_lock if self._needs_locking else self._no_op_lock

    def _get_thread_index(self) -> Index:
        """Return a thread-local libclang Index instance."""
        return self.clang_parser._get_thread_index()

    def _init_thread_local_buffers(self):
        """Initialize thread-local buffers for collecting symbols during parsing."""
        self._thread_local.collected_symbols = []
        self._thread_local.collected_calls = []
        self._thread_local.collected_aliases = []

    def _get_thread_local_buffers(self):
        """Get thread-local buffers, initializing if needed."""
        if not hasattr(self._thread_local, "collected_symbols"):
            self._init_thread_local_buffers()
        return (
            self._thread_local.collected_symbols,
            self._thread_local.collected_calls,
            self._thread_local.collected_aliases,
        )

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

    @staticmethod
    def _get_qualified_name(cursor: Any) -> str:
        """Build fully qualified name."""
        return SymbolExtractor._get_qualified_name(cursor)

    @staticmethod
    def _extract_namespace(qualified_name: str) -> str:
        """Extract namespace portion from qualified name."""
        return SymbolExtractor._extract_namespace(qualified_name)

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

    @staticmethod
    def _extract_params_from_type_spelling(type_spelling: str) -> str:
        """Facade for SymbolExtractor._extract_params_from_type_spelling"""
        return SymbolExtractor._extract_params_from_type_spelling(type_spelling)

    @staticmethod
    def _extract_trailing_qualifiers(type_spelling: str) -> str:
        """Facade for SymbolExtractor._extract_trailing_qualifiers"""
        return SymbolExtractor._extract_trailing_qualifiers(type_spelling)

    @staticmethod
    def _extract_brief_comment(cursor: Any) -> Optional[str]:
        """Facade for SymbolExtractor._extract_brief_comment"""
        return SymbolExtractor._extract_brief_comment(cursor)

    @staticmethod
    def _extract_raw_doc_comment(cursor: Any) -> Optional[str]:
        """Facade for SymbolExtractor._extract_raw_doc_comment"""
        return SymbolExtractor._extract_raw_doc_comment(cursor)

    @staticmethod
    def _extract_brief_from_doc(doc_comment: str) -> Optional[str]:
        """Facade for SymbolExtractor._extract_brief_from_doc"""
        return SymbolExtractor._extract_brief_from_doc(doc_comment)

    @staticmethod
    def _extract_template_args_from_displayname(displayname: str) -> List[str]:
        """Facade for SymbolExtractor._extract_template_args_from_displayname"""
        return SymbolExtractor._extract_template_args_from_displayname(displayname)

    @staticmethod
    def _is_system_header_diagnostic(diag: Any) -> bool:
        """Facade for ClangParser._is_system_header_diagnostic"""
        return ClangParser._is_system_header_diagnostic(diag)

    @staticmethod
    def _format_diagnostics(diagnostics_list: List[Any], max_count: int = 5) -> str:
        """Facade for ClangParser._format_diagnostics"""
        return ClangParser._format_diagnostics(diagnostics_list, max_count)

    def _process_deferred_instantiation(self, info: SymbolInfo) -> bool:
        """Process a single deferred instantiation and return True if resolved."""
        return self.symbol_extractor._process_deferred_instantiation(info)

    def _resolve_deferred_instantiation_bases(self) -> int:
        """Resolve base_classes for template instantiations that couldn't be resolved during parsing."""
        return self.symbol_extractor._resolve_deferred_instantiation_bases()

    def _extract_template_base_name_from_usr(self, usr: str) -> Optional[str]:
        """
        Extract the base template name from a USR.

        USR Format Examples:
        - Generic Template:        c:@ST>1#T@Container
        - Explicit Specialization: c:@S@Container>#I
        - Partial Specialization:  c:@SP>1#T@Container>#*t0.0

        Args:
            usr: Unified Symbol Resolution string

        Returns:
            Base template name (e.g., "Container") or None if not a template-related USR

        Task: Issue #99 Phase 3 - Template→Specialization linkage
        """
        if not usr:
            return None

        import re

        # Pattern 1: Generic template - c:@ST>...@ClassName
        match = re.search(r"c:@ST>[^@]*@(\w+)", usr)
        if match:
            return match.group(1)

        # Pattern 2: Regular class (potential specialization) - c:@S@ClassName
        match = re.search(r"c:@S@(\w+)", usr)
        if match:
            return match.group(1)

        # Pattern 3: Partial specialization - c:@SP>...@ClassName
        match = re.search(r"c:@SP>[^@]*@(\w+)", usr)
        if match:
            return match.group(1)

        return None

    def _add_class_template_symbols(self, base_name: str, results: List[SymbolInfo]) -> None:
        """Add class template and specialization symbols to results."""
        if base_name not in self.class_index:
            return
        for symbol in self.class_index[base_name]:
            if symbol.kind in ("class_template", "partial_specialization"):
                results.append(symbol)
            elif symbol.kind in ("class", "struct"):
                if symbol.usr and ">#" in symbol.usr:
                    results.append(symbol)

    def _add_function_template_symbols(self, base_name: str, results: List[SymbolInfo]) -> None:
        """Add function template and specialization symbols to results."""
        if base_name not in self.function_index:
            return
        for symbol in self.function_index[base_name]:
            if symbol.kind == "function_template":
                results.append(symbol)
            elif symbol.kind in ("function", "method"):
                if symbol.is_template_specialization or (
                    symbol.usr and ("<#" in symbol.usr or ">#" in symbol.usr)
                ):
                    results.append(symbol)

    def _find_template_specializations(self, base_name: str) -> List[SymbolInfo]:
        """
        Find all specializations of a template by base name.

        Searches for:
        1. Generic template definition (kind=class_template, function_template)
        2. Explicit full specializations (kind=class, function with template args in USR)
        3. Partial specializations (kind=partial_specialization)

        Args:
            base_name: Template base name (e.g., "Container")

        Returns:
            List of SymbolInfo objects for template and all its specializations

        Task: Issue #99 Phase 3 - Template→Specialization linkage
        """
        results: List[SymbolInfo] = []

        with self.index_lock:
            self._add_class_template_symbols(base_name, results)
            self._add_function_template_symbols(base_name, results)

        return results

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

    def _try_parse_with_fallback(
        self, file_path: str, args: List[str]
    ) -> Tuple[Optional[Any], Optional[str]]:
        """Try parsing with progressive fallback if initial attempt fails."""
        return self.clang_parser._try_parse_with_fallback(file_path, args)

    def _handle_index_file_failure(
        self,
        file_path: str,
        error_msg: str,
        args: List[str],
        current_hash: str,
        compile_args_hash: str,
        retry_count: int,
    ) -> None:
        """Log failure and save to cache."""
        diagnostics.error(f"Failed to parse {file_path}")
        diagnostics.error(f"  Error: {error_msg}")

        # Log first 10 args to avoid overwhelming output
        diagnostics.error(f"  Compilation args ({len(args)} total):")
        for i, arg in enumerate(args[:10]):
            diagnostics.error(f"    [{i}] {arg}")

        # Log to centralized error log
        parse_error = Exception(f"{error_msg}\nArgs: {args}")
        self.cache_manager.log_parse_error(
            file_path, parse_error, current_hash, compile_args_hash, retry_count
        )

        # Save failure to cache
        self._save_file_cache(
            file_path,
            [],
            current_hash,
            compile_args_hash,
            success=False,
            error_message=error_msg[:200],
            retry_count=retry_count,
        )

    def _handle_index_file_diagnostics(
        self, file_path: str, tu: Any, current_hash: str, compile_args_hash: str, retry_count: int
    ) -> Optional[str]:
        """Extract and process diagnostics. Returns error message if any."""
        return self.clang_parser._handle_index_file_diagnostics(
            file_path, tu, current_hash, compile_args_hash, retry_count
        )

    def _compute_retry_count(
        self, file_path: str, current_hash: str, compile_args_hash: str, force: bool
    ) -> int:
        """Compute retry count based on previous failed cache entries."""
        if force:
            return 0

        cache_data = self._load_file_cache(file_path, current_hash, compile_args_hash)
        if cache_data is not None and not cache_data["success"]:
            return int(cache_data["retry_count"]) + 1
        return 0

    def _finalize_index_success(
        self,
        file_path: str,
        tu,
        current_hash: str,
        compile_args_hash: str,
        cache_error_msg: Optional[str],
    ) -> tuple[bool, bool]:
        """Clear old entries, process TU, collect symbols, and save to cache."""
        with self._get_lock():
            self.symbol_store._clear_file_index_entries(file_path)

        extraction_result = self._index_translation_unit(tu, file_path)
        processed_count = len(extraction_result["processed"])
        if processed_count > 1:
            diagnostics.debug(
                f"{file_path}: processed {processed_count} files "
                f"({processed_count - 1} headers extracted, {len(extraction_result['skipped'])} skipped)"
            )

        with self._get_lock():
            collected_symbols = self.file_index.get(file_path, []).copy()
            del tu

            self.file_hashes[file_path] = current_hash

        self._save_file_cache(
            file_path,
            collected_symbols,
            current_hash,
            compile_args_hash,
            success=True,
            error_message=cache_error_msg,
            retry_count=0,
        )
        return (True, False)

    def _finalize_index_failure(
        self,
        file_path: str,
        error: Exception,
        current_hash: str,
        compile_args_hash: str,
        retry_count: int,
    ) -> tuple[bool, bool]:
        """Log parse error and save failure state to cache."""
        self.cache_manager.log_parse_error(
            file_path, error, current_hash, compile_args_hash, retry_count
        )
        error_msg = str(error)[:200]
        self._save_file_cache(
            file_path,
            [],
            current_hash,
            compile_args_hash,
            success=False,
            error_message=error_msg,
            retry_count=retry_count,
        )
        diagnostics.debug(f"Failed to parse {file_path}: {error_msg}")
        return (False, False)

    def index_file(self, file_path: str, force: bool = False) -> tuple[bool, bool]:
        """Index a single C++ file

        Returns:
            (success, was_cached) - success indicates if indexing succeeded,
                                   was_cached indicates if it was loaded from cache
        """
        file_path = os.path.abspath(file_path)

        if not Path(file_path).exists():
            error_msg = f"Source file does not exist: {file_path}"
            diagnostics.error(error_msg)
            self.cache_manager.log_parse_error(file_path, FileNotFoundError(error_msg), "", None, 0)
            return (False, False)

        current_hash = self._get_file_hash(file_path)
        args = self.compilation_env._get_compile_args_for_file(Path(file_path))
        compile_args_hash = self.compilation_env._compute_compile_args_hash(args)

        cached = self._try_load_cached_index(file_path, current_hash, compile_args_hash, force)
        if cached is not None:
            return cached

        retry_count = self._compute_retry_count(file_path, current_hash, compile_args_hash, force)

        try:
            tu, error_msg_opt = self._try_parse_with_fallback(file_path, args)
            if not tu:
                error_msg = error_msg_opt or "Unknown libclang error"
                self._handle_index_file_failure(
                    file_path, error_msg, args, current_hash, compile_args_hash, retry_count
                )
                return (False, False)

            cache_error_msg = self._handle_index_file_diagnostics(
                file_path, tu, current_hash, compile_args_hash, retry_count
            )

            return self._finalize_index_success(
                file_path, tu, current_hash, compile_args_hash, cache_error_msg
            )

        except Exception as e:
            return self._finalize_index_failure(
                file_path, e, current_hash, compile_args_hash, retry_count
            )

    def _is_terminal(self) -> bool:
        """Check if stderr is a terminal for progress reporting."""
        return (
            hasattr(sys.stderr, "isatty")
            and sys.stderr.isatty()
            and not os.environ.get("MCP_SESSION_ID")
            and not os.environ.get("CLAUDE_CODE_SESSION")
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
        return files

    def _merge_worker_result(self, result: Tuple, file_path: str):
        """Merge symbols and call sites from a worker process result."""
        _, success, was_cached, symbols, call_sites, processed_headers = result

        if success and symbols:
            with self.index_lock:
                # CRITICAL: Clear old entries for this file FIRST (before adding new symbols)
                # This ensures that modified files don't have duplicate/stale symbols
                self.symbol_store._clear_file_index_entries(file_path)

                for symbol in symbols:
                    self.symbol_store._merge_symbol_into_indexes(symbol)

            if call_sites:
                self.call_graph_service._stream_call_sites(file_path, call_sites)

            if processed_headers:
                for header_path, header_hash in processed_headers.items():
                    self.header_tracker.mark_completed(header_path, header_hash)

            file_hash = self._get_file_hash(file_path)
            self.file_hashes[file_path] = file_hash

    def _should_report_progress(
        self,
        processed: int,
        total: int,
        current_time: float,
        last_report_time: float,
        is_terminal: bool,
    ) -> bool:
        """Determine if progress should be reported based on interval and environment."""
        if is_terminal:
            return (
                (processed <= 5)
                or (processed % 5 == 0)
                or ((current_time - last_report_time) > 2.0)
                or (processed == total)
            )
        return (
            (processed % 50 == 0)
            or ((current_time - last_report_time) > 5.0)
            or (processed == total)
        )

    def _report_indexing_progress(
        self,
        processed: int,
        total: int,
        indexed_count: int,
        failed_count: int,
        cache_hits: int,
        start_time: float,
        is_terminal: bool,
        progress_callback: Optional[Callable],
        file_path: str,
    ):
        """Log progress and invoke callback."""
        current_time = time.time()
        elapsed = current_time - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        eta = (total - processed) / rate if rate > 0 else 0
        cache_rate = (cache_hits * 100 // processed) if processed > 0 else 0

        progress_str = (
            f"Progress: {processed}/{total} files ({100 * processed // total}%) - "
            f"Success: {indexed_count} - Failed: {failed_count} - "
            f"Cache: {cache_hits} ({cache_rate}%) - {rate:.1f} files/sec - ETA: {eta:.0f}s"
        )

        if is_terminal:
            print(f"\033[2K\r{progress_str}", end="", file=sys.stderr, flush=True)
        else:
            print(progress_str, file=sys.stderr, flush=True)

        if progress_callback:
            try:
                estimated_completion = datetime.now() + timedelta(seconds=eta) if eta > 0 else None
                progress = IndexingProgress(
                    total_files=total,
                    indexed_files=indexed_count,
                    failed_files=failed_count,
                    cache_hits=cache_hits,
                    current_file=file_path if processed < total else None,
                    start_time=datetime.fromtimestamp(start_time),
                    estimated_completion=estimated_completion,
                )
                progress_callback(progress)
            except Exception as e:
                diagnostics.debug(f"Progress callback failed: {e}")

    def _submit_indexing_tasks(
        self, executor: Executor, files: List[str], force: bool, include_dependencies: bool
    ) -> Dict:
        """Submit indexing tasks to executor."""
        if self.use_processes:
            config_file_str = (
                str(self.project_identity.config_file_path)
                if self.project_identity.config_file_path
                else None
            )
            file_compile_args = self.compilation_env._prepare_worker_compile_args(files)

            return {
                executor.submit(
                    _process_file_worker,
                    (
                        str(self.project_root),
                        config_file_str,
                        os.path.abspath(f),
                        force,
                        include_dependencies,
                        file_compile_args[f],
                    ),
                ): os.path.abspath(f)
                for f in files
            }
        else:
            return {
                executor.submit(self.index_file, os.path.abspath(f), force): os.path.abspath(f)
                for f in files
            }

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

    def _get_worker_result(self, future, file_path) -> Tuple[bool, bool]:
        """Get result from future and merge into indexes."""
        try:
            result = future.result()
            if self.use_processes:
                # ProcessPoolExecutor: result is 6-tuple
                self._merge_worker_result(result, file_path)
                return bool(result[1]), bool(result[2])  # success, was_cached

            # ThreadPoolExecutor: result is (success, was_cached)
            return bool(result[0]), bool(result[1])
        except Exception as exc:
            diagnostics.error(f"Error indexing {file_path}: {exc}")
            return False, False

    @staticmethod
    def _update_indexing_counts(success: bool, was_cached: bool) -> Tuple[int, int, int]:
        """Return (indexed_delta, cache_delta, failed_delta) for a single result."""
        if success:
            return 1, 1 if was_cached else 0, 0
        return 0, 0, 1

    def _maybe_report_indexing_progress(
        self,
        processed: int,
        total: int,
        indexed_count: int,
        failed_count: int,
        cache_hits: int,
        start_time: float,
        last_report_time: float,
        is_terminal: bool,
        progress_callback: Optional[Callable],
        file_path: str,
    ) -> float:
        """Report progress if enough time has passed; return updated last_report_time."""
        if self._should_report_progress(
            processed, total, time.time(), last_report_time, is_terminal
        ):
            self._report_indexing_progress(
                processed,
                total,
                indexed_count,
                failed_count,
                cache_hits,
                start_time,
                is_terminal,
                progress_callback,
                file_path,
            )
            return time.time()
        return last_report_time

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

        with self._interrupt_lock:
            self._interrupted = False
        is_terminal = self._is_terminal()
        indexed_count, cache_hits, failed_count = 0, 0, 0
        last_report_time = start_time

        executor = self.worker_pool.setup()

        try:
            future_to_file = self._submit_indexing_tasks(
                executor, files, force, include_dependencies
            )

            for i, future in enumerate(as_completed(future_to_file)):
                if self._is_interrupted():
                    raise KeyboardInterrupt("Indexing interrupted by request")
                if wait_for_tools_callback:
                    wait_for_tools_callback()

                file_path = future_to_file[future]
                success, was_cached = self._get_worker_result(future, file_path)

                idx_d, cache_d, fail_d = self._update_indexing_counts(success, was_cached)
                indexed_count += idx_d
                cache_hits += cache_d
                failed_count += fail_d

                last_report_time = self._maybe_report_indexing_progress(
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
            self.worker_pool.shutdown(name="Indexing")
            raise
        finally:
            self.worker_pool.shutdown_nowait(name="Indexing")

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

    def _submit_refresh_tasks(
        self, executor: Executor, modified_files: List[str], new_files: List[str]
    ) -> Dict[Future, str]:
        """Submit indexing tasks for modified and new files."""
        future_to_file = {}
        if self.use_processes:
            project_root = str(self.project_root)
            config_file_str = (
                str(self.project_identity.config_file_path)
                if self.project_identity.config_file_path
                else None
            )

            all_files_to_process = list(modified_files) + list(new_files)
            file_compile_args = self.compilation_env._prepare_refresh_compile_args(
                all_files_to_process
            )

            for f in modified_files:
                future = executor.submit(
                    _process_file_worker,
                    (
                        project_root,
                        config_file_str,
                        os.path.abspath(f),
                        True,
                        self.include_dependencies,
                        file_compile_args[f],
                    ),
                )
                future_to_file[future] = f
            for f in new_files:
                future = executor.submit(
                    _process_file_worker,
                    (
                        project_root,
                        config_file_str,
                        os.path.abspath(f),
                        False,
                        self.include_dependencies,
                        file_compile_args[f],
                    ),
                )
                future_to_file[future] = f
        else:
            for f in modified_files:
                future_to_file[executor.submit(self.index_file, f, True)] = f
            for f in new_files:
                future_to_file[executor.submit(self.index_file, f, False)] = f
        return future_to_file

    def _finalize_refresh(self, refreshed: int, deleted: int) -> None:
        """Perform post-refresh cleanup and optimizations."""
        if refreshed > 0 or deleted > 0:
            self._resolve_deferred_instantiation_bases()
            self._save_cache()
            self._save_header_tracking()
            if deleted > 0:
                diagnostics.info(f"Removed {deleted} deleted files from indexes")
            if refreshed > 0:
                self.cache_manager.backend.rebuild_fts()
        self.indexed_file_count = len(self.file_hashes)

    def _process_refresh_result(self, file_path: str, res: Any) -> bool:
        """Process result from indexing worker during refresh. Returns True if successful."""
        success = res[1] if self.use_processes else res[0]
        if success:
            if self.use_processes:
                self._merge_worker_result(res, file_path)
            return True
        return False

    def _prepare_refresh_set(self) -> Tuple[List[str], List[str], int]:
        """Identify files to refresh and handle deleted files. Returns (modified, new, deleted_count)."""
        current_files = set(self.compilation_env._find_cpp_files(self.include_dependencies))
        deleted_count = self.compilation_env._handle_deleted_files(current_files)
        modified_files, new_files = self.compilation_env._identify_refresh_files(current_files)
        return modified_files, new_files, deleted_count

    def _run_refresh_loop(
        self,
        executor: Executor,
        modified_files: List[str],
        new_files: List[str],
        total_to_check: int,
        start_time: float,
        progress_callback: Optional[Callable],
        wait_for_tools_callback: Optional[Callable[[], None]],
    ) -> Tuple[int, int]:
        """Run the parallel refresh loop and return (refreshed_count, failed_count)."""
        refreshed, failed = 0, 0
        future_to_file = self._submit_refresh_tasks(executor, modified_files, new_files)
        for i, future in enumerate(as_completed(future_to_file)):
            if wait_for_tools_callback:
                wait_for_tools_callback()

            file_path = future_to_file[future]
            try:
                if self._process_refresh_result(file_path, future.result()):
                    refreshed += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                diagnostics.error(f"Error refreshing {file_path}: {e}")

            if progress_callback and ((i + 1) % 10 == 0 or (i + 1) == total_to_check):
                self._report_refresh_progress(
                    progress_callback, total_to_check, refreshed, failed, file_path, start_time
                )
        return refreshed, failed

    def refresh_if_needed(
        self,
        progress_callback: Optional[Callable] = None,
        wait_for_tools_callback: Optional[Callable[[], None]] = None,
    ) -> int:
        """
        Refresh index for changed files and remove deleted files.

        This is the legacy refresh path used during initial cache loading.
        It performs simple hash-based change detection without dependency
        graph analysis or header cascade.

        For more sophisticated incremental updates (with header dependency
        tracking and compile_commands diffing), use IncrementalAnalyzer
        via the MCP refresh_project tool with mode="incremental".

        Both paths now use shared primitives from file_utils:
        - hash_file() for consistent file content hashing
        - hash_compile_args() for consistent argument hashing

        This ensures both paths agree on whether files or arguments have
        changed, even though they process changes differently.

        Args:
            progress_callback: Optional callback for progress updates
            wait_for_tools_callback: Optional callback to wait for tool availability

        Returns:
            Number of files refreshed
        """
        refreshed, deleted, start_time = 0, 0, time.time()

        if self.compile_commands_manager is not None and self.compile_commands_manager.enabled:
            if self.compile_commands_manager.refresh_if_needed():
                diagnostics.debug("Compile commands refreshed")

        modified_files, new_files, deleted = self._prepare_refresh_set()
        total_to_check = len(modified_files) + len(new_files)

        if total_to_check == 0:
            if deleted > 0:
                self._finalize_refresh(0, deleted)
            return 0

        diagnostics.debug(f"Refresh: {len(modified_files)} modified, {len(new_files)} new files")
        if self.use_processes:
            self.cache_manager.ensure_schema_current()

        executor = self.worker_pool.setup()
        try:
            refreshed, failed = self._run_refresh_loop(
                executor,
                modified_files,
                new_files,
                total_to_check,
                start_time,
                progress_callback,
                wait_for_tools_callback,
            )
        except KeyboardInterrupt:
            diagnostics.info("\nRefresh interrupted by user (Ctrl-C)")
            self.worker_pool.shutdown(name="Refresh")
            raise
        finally:
            self.worker_pool.shutdown_nowait(name="Refresh")

        self._finalize_refresh(refreshed, deleted)
        return refreshed

    def _report_refresh_progress(
        self,
        progress_callback: Callable,
        total_files: int,
        refreshed: int,
        failed: int,
        current_file: str,
        start_time: float,
    ):
        """
        Report refresh progress via callback.

        Args:
            progress_callback: Callback to invoke with progress
            total_files: Total number of files to process
            refreshed: Number of files successfully refreshed so far
            failed: Number of files that failed
            current_file: Currently processing file
            start_time: Unix timestamp when refresh started
        """
        try:
            # Import IndexingProgress here to avoid circular dependency
            from .state_manager import IndexingProgress

            processed = refreshed + failed
            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (total_files - processed) / rate if rate > 0 else 0

            estimated_completion = datetime.now() + timedelta(seconds=eta) if eta > 0 else None

            progress = IndexingProgress(
                total_files=total_files,
                indexed_files=refreshed,
                failed_files=failed,
                cache_hits=0,  # Not tracked during refresh
                current_file=current_file if processed < total_files else None,
                start_time=datetime.fromtimestamp(start_time),
                estimated_completion=estimated_completion,
            )

            progress_callback(progress)
        except Exception as e:
            # Don't fail refresh if progress callback fails
            diagnostics.debug(f"Progress callback failed: {e}")

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
