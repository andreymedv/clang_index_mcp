"""
Pure Python C++ Analyzer using libclang

This module provides C++ code analysis functionality using libclang bindings.
It's slower than the C++ implementation but more reliable and easier to debug.
"""

import json
import os
import sys
import threading
import time
from collections import deque
from concurrent.futures import (
    Executor,
    Future,
    as_completed,
)
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .cache_manager import CacheManager
from .cache_orchestrator import CacheOrchestrator
from .call_graph_service import CallGraphService
from .clang_parser import ClangParser
from .compilation_environment import CompilationEnvironment
from .compile_commands_manager import CompileCommandsManager
from .cpp_analyzer_config import CppAnalyzerConfig
from .project_identity import ProjectIdentity
from .query_engine import QueryEngine
from .search_engine import SearchEngine
from .state_manager import IndexingProgress
from .symbol_extractor import SymbolExtractor
from .symbol_index_store import SymbolIndexStore
from .symbol_info import (
    CLASS_KINDS,
    SymbolInfo,
    build_location_objects,
    omit_empty,
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
            self.worker_pool.shutdown(name="Indexing")

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
        """Refresh index for changed files and remove deleted files."""
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

        with self.worker_pool as executor:
            refreshed, failed = self._run_refresh_loop(
                executor,
                modified_files,
                new_files,
                total_to_check,
                start_time,
                progress_callback,
                wait_for_tools_callback,
            )

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

    def _get_alias_details_from_db(self, alias_names: List[str]) -> List[Dict[str, Any]]:
        """Query type_aliases table for detailed information about a set of aliases."""
        unique_aliases = {}
        try:
            self.cache_manager.backend._ensure_connected()
            conn = self.cache_manager.backend.conn
            assert conn is not None

            for alias_name in alias_names:
                cursor = conn.execute(
                    """
                    SELECT alias_name, qualified_name, canonical_type, file, line, namespace,
                           is_template_alias, template_params
                    FROM type_aliases
                    WHERE alias_name = ? OR qualified_name = ?
                    """,
                    (alias_name, alias_name),
                )
                row = cursor.fetchone()
                if row:
                    qualified_alias = row["qualified_name"]
                    if qualified_alias not in unique_aliases:
                        alias_dict = {
                            "name": row["alias_name"],
                            "qualified_name": qualified_alias,
                            "file": row["file"],
                            "line": row["line"],
                        }
                        if row["is_template_alias"]:
                            alias_dict["is_template_alias"] = True
                            if row["template_params"]:
                                alias_dict["template_params"] = json.loads(row["template_params"])
                        unique_aliases[qualified_alias] = alias_dict
        except Exception as e:
            diagnostics.debug(f"Failed to get alias details: {e}")
        return list(unique_aliases.values())

    def _get_info_for_known_alias(self, type_name: str) -> Optional[Dict[str, Any]]:
        """Attempt to get type alias info from the database if type_name is a known alias."""
        try:
            self.cache_manager.backend._ensure_connected()
            conn = self.cache_manager.backend.conn
            assert conn is not None
            cursor = conn.execute(
                """
                SELECT alias_name, qualified_name, canonical_type, file, line, namespace,
                       is_template_alias, template_params
                FROM type_aliases
                WHERE alias_name = ? OR qualified_name = ?
                """,
                (type_name, type_name),
            )
            row = cursor.fetchone()
            if row:
                alias_names = self.cache_manager.get_aliases_for_canonical(row["canonical_type"])
                aliases = self._get_alias_details_from_db(alias_names)

                return {
                    "canonical_type": row["canonical_type"],
                    "qualified_name": row["qualified_name"],
                    "namespace": row["namespace"],
                    "file": row["file"],
                    "line": row["line"],
                    "input_was_alias": True,
                    "is_ambiguous": False,
                    "aliases": aliases,
                }
        except Exception as e:
            diagnostics.warning(f"Error querying type_aliases for '{type_name}': {e}")
        return None

    def _find_type_matches(self, type_name: str) -> List[SymbolInfo]:
        """Search class index for matching types and return list of matches."""
        matches = []
        with self.index_lock:
            for name, infos in self.class_index.items():
                for info in infos:
                    # Use qualified pattern matching (same as search_classes)
                    qualified_name = info.qualified_name if info.qualified_name else info.name
                    if SearchEngine.matches_qualified_pattern(qualified_name, type_name):
                        matches.append(info)
        return matches

    def _check_type_ambiguity(
        self, type_name: str, matches: List[SymbolInfo]
    ) -> Optional[Dict[str, Any]]:
        """Check for ambiguity among matches and return error dict if ambiguous."""
        if len(matches) > 1:
            # Check if all matches have the same qualified_name (duplicates from forward decls)
            unique_qualified_names = set(
                m.qualified_name if m.qualified_name else m.name for m in matches
            )
            if len(unique_qualified_names) > 1:
                # Ambiguous - multiple different types match
                return {
                    "error": f"Ambiguous type name '{type_name}'",
                    "is_ambiguous": True,
                    "matches": [
                        {
                            "canonical_type": m.name,
                            "qualified_name": m.qualified_name if m.qualified_name else m.name,
                            "namespace": m.namespace,
                            "file": m.file,
                            "line": m.line,
                        }
                        for m in matches
                    ],
                    "suggestion": "Use qualified name (e.g., 'ui::Widget')",
                }
        return None

    def get_type_alias_info(self, type_name: str) -> Dict[str, Any]:
        """Get comprehensive type alias information."""
        # Step 1: Check if input is a known alias in the type_aliases table
        input_canonical = self.cache_manager.get_canonical_for_alias(type_name)
        input_was_alias = False

        if input_canonical:
            input_was_alias = True
            info = self._get_info_for_known_alias(type_name)
            if info:
                return info

        # Step 2: Input is not a known alias - search class_index for matching classes
        matches = self._find_type_matches(type_name)

        # Step 3: Check for ambiguity
        ambiguity_error = self._check_type_ambiguity(type_name, matches)
        if ambiguity_error:
            return ambiguity_error

        # Step 4: Handle not found case
        if len(matches) == 0:
            return {
                "error": f"Type '{type_name}' not found",
                "canonical_type": None,
                "aliases": [],
            }

        # Step 5: Use the first match (prefer definitions over declarations)
        canonical_info = matches[0]
        for m in matches:
            if m.is_definition:
                canonical_info = m
                break

        canonical_type = (
            canonical_info.qualified_name if canonical_info.qualified_name else canonical_info.name
        )

        # Step 6: Get all aliases for the canonical type
        alias_names = self.cache_manager.get_aliases_for_canonical(canonical_type)

        # Step 7: Build detailed alias information
        aliases = self._get_alias_details_from_db(alias_names) if alias_names else []

        # Step 8: Return success result
        return {
            "canonical_type": canonical_type,
            "qualified_name": (
                canonical_info.qualified_name
                if canonical_info.qualified_name
                else canonical_info.name
            ),
            "namespace": canonical_info.namespace,
            "file": canonical_info.file,
            "line": canonical_info.line,
            "input_was_alias": input_was_alias,
            "is_ambiguous": False,
            "aliases": aliases,
        }

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

    def _check_template_param_inheritance(self, base_class: str, target_class: str) -> bool:
        """
        Check if a class indirectly inherits from target_class through template
        parameter inheritance.

        Issue: cplusplus_mcp-hnj

        Example:
            If Template<T> inherits from T, and a class has base_class="Template<BaseClass>",
            then it indirectly inherits from BaseClass.

        Args:
            base_class: The base class string (e.g., "ns::Template<ns::BaseClass>")
            target_class: The class we're looking for (e.g., "ns::BaseClass" or "BaseClass")

        Returns:
            True if there's indirect inheritance through template parameters
        """
        # Quick check: if no template instantiation, no indirect inheritance possible
        if "<" not in base_class:
            return False

        # Parse the template instantiation
        # Format: "ns::Template<arg1, arg2, ...>" or "Template<arg>"
        bracket_pos = base_class.find("<")
        if bracket_pos == -1:
            return False

        template_name = base_class[:bracket_pos]
        args_str = base_class[bracket_pos + 1 : -1]  # Remove < and >

        # Find which parameter indices the template inherits from
        # Look up the template in class_index and check its base_classes for type-parameter-X-Y
        param_indices = self._get_template_param_inheritance_indices(template_name)

        if not param_indices:
            return False

        # Parse template arguments (handle nested templates)
        template_args = self._parse_template_args(args_str)

        # Check if any of the inherited-from parameter positions match target_class
        for param_idx in param_indices:
            if param_idx < len(template_args):
                arg = template_args[param_idx]
                # Check if the argument matches target_class
                # Handle both qualified and simple names
                if arg == target_class:
                    return True
                # Check if target_class is the simple name of arg
                if "::" in arg and arg.endswith("::" + target_class):
                    return True
                # Check if arg is the simple name of target_class
                if "::" in target_class and target_class.endswith("::" + arg):
                    return True
                # Check simple name match
                arg_simple = arg.split("::")[-1] if "::" in arg else arg
                target_simple = (
                    target_class.split("::")[-1] if "::" in target_class else target_class
                )
                if arg_simple == target_simple:
                    return True

        return False

    def _get_template_param_inheritance_indices(self, template_name: str) -> List[int]:
        """
        Get the template parameter indices that a template inherits from.

        Looks up the template in class_index and analyzes its base_classes
        to find which template parameters are used as base classes.

        Supports two formats:
        1. Parameter names (new format): base_classes = ['T', 'BaseType']
        2. Legacy format: base_classes = ['type-parameter-0-0'] (for backward compatibility)

        Args:
            template_name: The template name (e.g., "ns::TemplateInheritsParam")

        Returns:
            List of parameter indices that are used as base classes.
            E.g., [0] means the template inherits from its first parameter.
        """
        simple_name = template_name.split("::")[-1] if "::" in template_name else template_name

        param_indices = []
        with self.index_lock:
            infos = self.class_index.get(simple_name, [])
            for info in infos:
                if info.kind != "class_template":
                    continue
                if not self._template_info_matches_name(info, template_name):
                    continue

                param_name_to_index = self._build_param_name_to_index(info.template_parameters)
                for base in info.base_classes:
                    param_index = self._resolve_param_index(base, param_name_to_index)
                    if param_index is not None and param_index not in param_indices:
                        param_indices.append(param_index)

        return param_indices

    @staticmethod
    def _template_info_matches_name(info, template_name: str) -> bool:
        """Check if a class info matches the requested template name."""
        if "::" not in template_name:
            return True
        info_qualified = info.qualified_name if info.qualified_name else info.name
        return SearchEngine.matches_qualified_pattern(info_qualified, template_name)

    @staticmethod
    def _build_param_name_to_index(template_parameters: Optional[str]) -> Dict[str, int]:
        """Build a mapping from template parameter names to their indices."""
        import json

        param_name_to_index: Dict[str, int] = {}
        if not template_parameters:
            return param_name_to_index

        try:
            params = json.loads(template_parameters)
            for i, param in enumerate(params):
                param_name = param.get("name", "")
                if param_name:
                    param_name_to_index[param_name] = i
        except (json.JSONDecodeError, TypeError):
            pass

        return param_name_to_index

    @staticmethod
    def _resolve_param_index(base: str, param_name_to_index: Dict[str, int]) -> Optional[int]:
        """Resolve a base class name to a template parameter index if applicable."""
        import re

        if base in param_name_to_index:
            return param_name_to_index[base]

        match = re.match(r"type-parameter-(\d+)-(\d+)", base)
        if match:
            return int(match.group(2))

        return None

    def _parse_template_args(self, args_str: str) -> List[str]:
        """
        Parse template arguments from a string like "A, B<C, D>, E".

        Handles nested templates by tracking bracket depth.

        Args:
            args_str: The string inside template brackets (without < and >)

        Returns:
            List of template argument strings
        """
        args = []
        current_arg = ""
        depth = 0

        for char in args_str:
            if char == "<":
                depth += 1
                current_arg += char
            elif char == ">":
                depth -= 1
                current_arg += char
            elif char == "," and depth == 0:
                args.append(current_arg.strip())
                current_arg = ""
            else:
                current_arg += char

        if current_arg.strip():
            args.append(current_arg.strip())

        return args

    def _get_template_patterns(self, simple_name: str) -> List[str]:
        """Get template patterns for matching derived classes."""
        template_patterns = []
        with self.index_lock:
            # Check if class_name exists in class_index (use simple_name for lookup)
            if simple_name in self.class_index:
                for symbol in self.class_index[simple_name]:
                    # If any symbol is a template, get all specializations
                    if symbol.kind in ("class_template", "partial_specialization"):
                        # Build patterns to match in base_classes
                        # Matches: "Container", "Container<int>", "Container<double>", etc.
                        # Use simple_name since base_classes matching uses suffix matching
                        template_patterns.append(simple_name)  # Exact match
                        template_patterns.append(
                            f"{simple_name}<"
                        )  # Prefix match for specializations
                        break  # Only need to detect template once

            # If not a template, just use exact match (use simple_name for matching)
            if not template_patterns:
                template_patterns = [simple_name]
        return template_patterns

    @staticmethod
    def _check_pattern_match(base_class: str, template_patterns: List[str]) -> bool:
        """Check if base_class matches any of the template patterns."""
        for pattern in template_patterns:
            # Exact match or template specialization prefix match
            if base_class == pattern or base_class.startswith(pattern):
                return True
            # Handle qualified names: "ns::BaseClass" should match "BaseClass"
            # Check if base_class ends with "::pattern" or "::pattern<"
            if "::" in base_class:
                if base_class.endswith("::" + pattern):
                    return True
                if base_class.split("::")[-1].startswith(pattern):
                    return True
        return False

    def _is_derived_from(
        self, info: SymbolInfo, template_patterns: List[str], simple_name: str
    ) -> bool:
        """Check if a symbol inherits from the target class or any specialization."""
        tparam_names: set = set()
        if info.template_parameters:
            try:
                tparams = json.loads(info.template_parameters)
                tparam_names = {p.get("name", "") for p in tparams if p.get("name")}
            except (json.JSONDecodeError, TypeError):
                pass

        for base_class in info.base_classes:
            # Skip base classes that are template parameters
            if base_class in tparam_names:
                continue

            match_found = self._check_pattern_match(base_class, template_patterns)

            # Issue cplusplus_mcp-hnj: Check for indirect inheritance
            # through template parameters
            if not match_found:
                match_found = self._check_template_param_inheritance(base_class, simple_name)

            if match_found:
                return True
        return False

    def get_derived_classes(
        self, class_name: str, project_only: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get all classes that derive from the given class.

        Issue #99 Phase 3: Template-aware derived class queries
        If class_name is a template, finds classes derived from ANY specialization:
        - Container → finds classes derived from Container<T>, Container<int>, Container<double>, etc.
        - Enables CRTP pattern discovery

        Args:
            class_name: Name of the base class (can be template name)
            project_only: Only include project classes (exclude dependencies)

        Returns:
            List of classes that inherit from the given class or any of its specializations
        """
        derived_classes = []

        # Normalize class_name: extract simple name from qualified name
        # class_index is keyed by simple name, but users may pass qualified names
        # (e.g., "myapp::builders::Widget" → "Widget")
        simple_name = SearchEngine._extract_simple_name(class_name)

        # Issue #99 Phase 3: Check if this is a template and get all specializations
        template_patterns = self._get_template_patterns(simple_name)

        with self.index_lock:
            for name, infos in self.class_index.items():
                for info in infos:
                    if not project_only or info.is_project:
                        if self._is_derived_from(info, template_patterns, simple_name):
                            derived_classes.append(
                                omit_empty(
                                    {
                                        "qualified_name": info.qualified_name or info.name,
                                        "kind": info.kind,
                                        "is_project": info.is_project,
                                        "base_classes": info.base_classes,
                                        **build_location_objects(info),
                                    }
                                )
                            )

        return derived_classes

    def _resolve_base_key(self, raw: str) -> str:
        """Resolve a raw base-class name to a canonical key (qualified name)."""
        is_dependent = raw.startswith("typename ") or (
            "<" in raw and ">" in raw and not raw.endswith(">")
        )
        if is_dependent:
            return raw
        has_targs = "<" in raw
        lookup = SearchEngine._strip_template_args(raw) if has_targs else raw
        is_qual = "::" in lookup
        simple = SearchEngine._extract_simple_name(lookup)
        with self.index_lock:
            infos = self.class_index.get(simple, [])
            for info in infos:
                if is_qual:
                    info_qn = info.qualified_name if info.qualified_name else info.name
                    if not SearchEngine.matches_qualified_pattern(info_qn, lookup):
                        continue
                qn = info.qualified_name if info.qualified_name else info.name
                return qn  # canonical key is bare qualified name (no template args)
        return raw

    def _lookup_class_infos(self, key: str) -> List[SymbolInfo]:
        """Look up SymbolInfo objects for a class name/key."""
        has_targs = "<" in key
        lookup = SearchEngine._strip_template_args(key) if has_targs else key
        is_qual = "::" in lookup
        simple = SearchEngine._extract_simple_name(lookup)
        with self.index_lock:
            infos = list(self.class_index.get(simple, []))
        if is_qual:
            infos = [
                i
                for i in infos
                if SearchEngine.matches_qualified_pattern(
                    i.qualified_name if i.qualified_name else i.name, lookup
                )
            ]
        if has_targs and not is_qual:
            specs = [i for i in infos if i.is_template_specialization]
            if specs:
                infos = specs
        return infos

    def _collect_hierarchy_node_data(self, key: str) -> Optional[Dict[str, Any]]:
        """Collect class node data for hierarchy building. Returns None if not found."""
        infos = self._lookup_class_infos(key)
        if not infos:
            # Unresolved: external lib or template-dependent name
            is_dep = key.startswith("typename ") or (
                "<" in key and ">" in key and not key.endswith(">")
            )
            node: Dict[str, Any] = {
                "qualified_name": key,
                "kind": "unknown",
                "is_project": False,
                "base_classes": [],
                "derived_classes": [],
            }
            if is_dep:
                node["is_dependent_type"] = True
            else:
                node["is_unresolved"] = True
            return node

        info = infos[0]
        info_key = info.qualified_name if info.qualified_name else info.name

        # Resolve raw base class names to canonical keys (dedup, preserve order)
        base_keys: List[str] = []
        seen_base: Set[str] = set()
        for raw_base in info.base_classes:
            bk = self._resolve_base_key(raw_base)
            if bk not in seen_base:
                seen_base.add(bk)
                base_keys.append(bk)

        # Get derived classes for this node
        derived = self.get_derived_classes(info_key, project_only=False)
        derived_keys: List[str] = []
        seen_derived: Set[str] = set()
        for d in derived:
            dk = d["qualified_name"]
            if dk not in seen_derived:
                seen_derived.add(dk)
                derived_keys.append(dk)

        return {
            "qualified_name": info_key,
            "kind": info.kind,
            "is_project": info.is_project,
            "base_classes": base_keys,
            "derived_classes": derived_keys,
        }

    def _should_skip_hierarchy_node(
        self, current: str, visited: Set[str], initial_visited: Optional[Set[str]], start_key: str
    ) -> bool:
        """Decide if a node should be skipped during BFS."""
        if current in visited:
            if initial_visited is None:
                return True
            if current != start_key:
                return True
        return False

    def _bfs_traverse_hierarchy(
        self,
        start_key: str,
        direction: str,
        max_depth: Optional[int],
        max_nodes: Optional[int],
        classes: Dict[str, Any],
        initial_visited: Optional[Set[str]] = None,
    ) -> Tuple[Set[str], bool]:
        """Perform BFS traversal in specified direction for class hierarchy.
        Returns (set of visited keys, truncated flag).
        """
        visited: Set[str] = initial_visited if initial_visited is not None else set()
        queue: deque = deque([(start_key, 0)])
        local_truncated = False
        neighbor_attr = "base_classes" if direction == "up" else "derived_classes"

        while queue:
            current, depth = queue.popleft()
            if self._should_skip_hierarchy_node(current, visited, initial_visited, start_key):
                continue
            visited.add(current)

            node_data = self._collect_hierarchy_node_data(current)
            if node_data is None:
                continue

            # Add to classes if not already there (for final collection)
            if current not in classes:
                classes[current] = node_data

            # Check node cap AFTER adding current node
            if max_nodes is not None and len(classes) >= max_nodes:
                local_truncated = True
                break

            next_depth = depth + 1
            if max_depth is not None and next_depth > max_depth:
                if any(n not in visited for n in node_data[neighbor_attr]):
                    local_truncated = True
            else:
                for neighbor in node_data[neighbor_attr]:
                    if neighbor not in visited:
                        queue.append((neighbor, next_depth))

        return visited, local_truncated

    def get_class_hierarchy(
        self,
        class_name: str,
        max_nodes: Optional[int] = 200,
        max_depth: Optional[int] = None,
        direction: str = "both",
    ) -> Dict[str, Any]:
        """Get the inheritance graph for a class as a flat adjacency list."""
        if direction not in ("up", "down", "both"):
            return {"error": f"Invalid direction '{direction}'. Must be one of: up, down, both"}

        start_infos = self._lookup_class_infos(class_name)
        if not start_infos:
            return {"error": f"Class '{class_name}' not found"}

        start_info = start_infos[0]
        start_key = start_info.qualified_name or start_info.name
        classes: Dict[str, Any] = {}
        truncated = False

        if direction == "up":
            _, truncated = self._bfs_traverse_hierarchy(
                start_key, "up", max_depth, max_nodes, classes
            )
        elif direction == "down":
            _, truncated = self._bfs_traverse_hierarchy(
                start_key, "down", max_depth, max_nodes, classes
            )
        else:  # both
            v_up, trunc_up = self._bfs_traverse_hierarchy(
                start_key, "up", max_depth, max_nodes, classes
            )
            trunc_down = False
            if max_nodes is None or len(classes) < max_nodes:
                _, trunc_down = self._bfs_traverse_hierarchy(
                    start_key, "down", max_depth, max_nodes, classes, initial_visited=v_up
                )
            truncated = trunc_up or trunc_down

        result: Dict[str, Any] = {
            "queried_class": start_key,
            "direction": direction,
            "classes": classes,
        }
        if truncated:
            result.update(
                {"truncated": True, "nodes_returned": len(classes), "completeness": "partial"}
            )
            result["completeness_note"] = (
                "Hierarchy was truncated due to max_nodes or max_depth limit."
            )
        else:
            result.update({"completeness": "complete"})
            result["completeness_note"] = (
                "Full inheritance hierarchy including all ancestors and descendants."
            )
        return result

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
        """Search for symbols within a specific file or files matching a glob pattern."""
        # Detect if file_path is a glob pattern
        glob_chars = set("*?[]")
        is_glob = any(c in file_path for c in glob_chars)

        if is_glob:
            return self._find_in_files_glob(file_path, pattern)
        else:
            return self._find_in_file_exact(file_path, pattern)

    def _matches_glob(self, indexed_file: str, glob_pattern: str) -> bool:
        """Check if an indexed file matches a glob pattern using multiple strategies."""
        import fnmatch

        if fnmatch.fnmatch(indexed_file, glob_pattern):
            return True
        if fnmatch.fnmatch(indexed_file, "**/" + glob_pattern):
            return True
        if self.project_root:
            try:
                rel_path = str(Path(indexed_file).relative_to(self.project_root))
                return fnmatch.fnmatch(rel_path, glob_pattern)
            except ValueError:
                pass
        return False

    def _filter_results_by_files(
        self, items: List[Dict[str, Any]], matched_files: set
    ) -> List[Dict[str, Any]]:
        """Filter search results to only include items from specified files."""
        results = []
        for item in items:
            _item_loc = item.get("definition") or item.get("declaration") or {}
            item_file = _item_loc.get("file") or item.get("file", "")
            if item_file in matched_files:
                results.append(item)
        return results

    def _find_in_files_glob(self, glob_pattern: str, symbol_pattern: str) -> Dict[str, Any]:
        """Search for symbols in files matching a glob pattern.

        Args:
            glob_pattern: Glob pattern to match files (e.g., '**/tests/**/*.cpp')
            symbol_pattern: Symbol search pattern

        Returns:
            Dict with results, matched_files, and message
        """
        matched_files = [f for f in self.file_index.keys() if self._matches_glob(f, glob_pattern)]

        if not matched_files:
            return {
                "results": [],
                "matched_files": [],
                "suggestions": self._get_path_suggestions(glob_pattern),
                "message": f"No files found matching glob pattern '{glob_pattern}'",
            }

        all_classes = self.search_classes(symbol_pattern, project_only=False)
        all_functions = self.search_functions(symbol_pattern, project_only=False)
        matched_files_set = set(matched_files)
        results = self._filter_results_by_files(all_classes + all_functions, matched_files_set)

        return {
            "results": results,
            "matched_files": sorted(matched_files),
            "message": f"Found {len(results)} symbols in {len(matched_files)} files matching '{glob_pattern}'",
        }

    def _find_in_file_exact(self, file_path: str, pattern: str) -> Dict[str, Any]:
        """Search for symbols in a specific file (exact or suffix match).

        Args:
            file_path: Path to file (absolute, relative, or filename)
            pattern: Symbol search pattern

        Returns:
            Dict with results, matched_files, suggestions (if empty), and message
        """
        results = []

        # Search in both class and function results
        all_classes = self.search_classes(pattern, project_only=False)
        all_functions = self.search_functions(pattern, project_only=False)

        # Try to resolve file path
        abs_file_path = None
        matched_file = None

        # First, try exact absolute path match
        if Path(file_path).is_absolute():
            abs_file_path = str(Path(file_path).resolve())
        else:
            # Try relative to project root
            if self.project_root:
                potential_path = Path(self.project_root) / file_path
                if potential_path.exists():
                    abs_file_path = str(potential_path.resolve())

        # Filter by file path
        for item in all_classes + all_functions:
            # Extract file from nested location object (definition or declaration)
            _item_loc = item.get("definition") or item.get("declaration") or {}
            item_file = _item_loc.get("file") or item.get("file", "")
            if not item_file:
                continue

            # Match by absolute path or suffix
            item_abs = str(Path(item_file).resolve()) if item_file else ""

            if abs_file_path and item_abs == abs_file_path:
                results.append(item)
                matched_file = item_file
            elif item_file.endswith(file_path) or item_abs.endswith(file_path):
                results.append(item)
                matched_file = item_file

        if results:
            return {
                "results": results,
                "matched_files": [matched_file] if matched_file else [],
                "message": f"Found {len(results)} symbols in '{file_path}'",
            }
        else:
            # No results - provide suggestions
            suggestions = self._get_path_suggestions(file_path)
            return {
                "results": [],
                "matched_files": [],
                "suggestions": suggestions,
                "message": f"No file found matching '{file_path}'. See suggestions for similar paths.",
            }

    def _get_path_suggestions(self, partial_path: str, max_suggestions: int = 5) -> List[str]:
        """Get suggestions for similar file paths based on partial input.

        Args:
            partial_path: Partial path or filename to match
            max_suggestions: Maximum number of suggestions to return

        Returns:
            List of suggested file paths
        """
        suggestions = []
        partial_lower = partial_path.lower()

        # Extract just the filename/basename for matching
        partial_basename = Path(partial_path).name.lower()

        # Also extract any path components for better matching
        path_parts = [p.lower() for p in Path(partial_path).parts if p]

        for indexed_file in self.file_index.keys():
            indexed_lower = indexed_file.lower()
            indexed_basename = Path(indexed_file).name.lower()

            score = 0

            # Exact basename match (highest priority)
            if indexed_basename == partial_basename:
                score += 100

            # Basename contains partial
            elif partial_basename in indexed_basename:
                score += 50

            # Path contains partial string
            elif partial_lower in indexed_lower:
                score += 30

            # Check if path components match
            for part in path_parts:
                if part in indexed_lower:
                    score += 10

            if score > 0:
                suggestions.append((score, indexed_file))

        # Sort by score (descending) and take top suggestions
        suggestions.sort(key=lambda x: (-x[0], x[1]))
        return [path for _, path in suggestions[:max_suggestions]]

    def _find_class_definition_files(
        self,
        symbol_name: str,
        symbol_kind: Optional[str],
        simple_name: str,
        project_only: bool,
        files: Set[str],
    ) -> Optional[str]:
        """Find files where the class is defined and return its kind."""
        if symbol_kind in (None, "class"):
            for info in self.class_index.get(simple_name, []):
                if SearchEngine.matches_qualified_pattern(
                    info.qualified_name or info.name, symbol_name
                ):
                    if not project_only or info.is_project:
                        files.add(info.file)
                        if info.header_file:
                            files.add(info.header_file)
                        return info.kind
        return None

    def _find_function_definition_files(
        self,
        symbol_name: str,
        symbol_kind: Optional[str],
        simple_name: str,
        project_only: bool,
        files: Set[str],
    ) -> Optional[str]:
        """Find files where the function/method is defined and return its kind."""
        kind = None
        if symbol_kind in (None, "function", "method"):
            for info in self.function_index.get(simple_name, []):
                if SearchEngine.matches_qualified_pattern(
                    info.qualified_name or info.name, symbol_name
                ):
                    if not project_only or info.is_project:
                        files.add(info.file)
                        if info.header_file:
                            files.add(info.header_file)
                        if not kind:
                            kind = info.kind
        return kind

    def _find_symbol_definition_files(
        self,
        symbol_name: str,
        symbol_kind: Optional[str],
        simple_name: str,
        project_only: bool,
        files: Set[str],
    ) -> Optional[str]:
        """Find files where the symbol is defined and return the first found kind."""
        kind = self._find_class_definition_files(
            symbol_name, symbol_kind, simple_name, project_only, files
        )

        func_kind = self._find_function_definition_files(
            symbol_name, symbol_kind, simple_name, project_only, files
        )

        return kind or func_kind

    def _find_symbol_caller_files(
        self,
        symbol_name: str,
        symbol_kind: Optional[str],
        simple_name: str,
        project_only: bool,
        kind: Optional[str],
        files: Set[str],
    ) -> int:
        """Find files that call the symbol and return the reference count."""
        total_refs = 0
        if kind in ("function", "method") or (
            not kind and symbol_kind in (None, "function", "method")
        ):

            def _name_matches(info) -> bool:
                return SearchEngine.matches_qualified_pattern(
                    info.qualified_name or info.name, symbol_name
                )

            # Get USRs for all functions with this name
            target_usrs = set()
            for info in self.function_index.get(simple_name, []):
                if _name_matches(info) and info.usr:
                    if not project_only or info.is_project:
                        target_usrs.add(info.usr)

            # Find all callers of these functions
            for usr in target_usrs:
                callers = self.call_graph_analyzer.find_incoming_calls(usr)
                for caller_usr in callers:
                    if caller_usr in self.usr_index:
                        caller_info = self.usr_index[caller_usr]
                        if not project_only or caller_info.is_project:
                            files.add(caller_info.file)
                            total_refs += 1
        return total_refs

    def _find_class_reference_files(
        self,
        symbol_name: str,
        symbol_kind: Optional[str],
        project_only: bool,
        kind: Optional[str],
        files: Set[str],
    ) -> None:
        """Find files that reference a class and add them to the set."""
        if kind in ("class", "struct") or (not kind and symbol_kind in (None, "class")):
            # Check file index for files that might reference the class
            for file_path, symbols in self.file_index.items():
                if not project_only or self.compilation_env._is_project_file(file_path):
                    # If file has the class definition or any methods of the class
                    for symbol in symbols:
                        sym_qname = symbol.qualified_name or symbol.name
                        parent_qname = symbol.parent_class or ""
                        if SearchEngine.matches_qualified_pattern(
                            sym_qname, symbol_name
                        ) or SearchEngine.matches_qualified_pattern(parent_qname, symbol_name):
                            files.add(file_path)
                            break

    async def get_files_containing_symbol(
        self, symbol_name: str, symbol_kind: Optional[str] = None, project_only: bool = True
    ) -> Dict[str, Any]:
        """
        Get all files that contain references to or define a symbol.

        Phase 1: LLM Integration - Enables targeted code search by narrowing down
        which files to examine with filesystem or ripgrep MCP tools.

        Args:
            symbol_name: Name of the symbol (exact match, case-sensitive)
            symbol_kind: Optional filter: "class", "function", or "method"
            project_only: If True, exclude dependency/system files

        Returns:
            Dictionary with:
                - symbol: The symbol name searched
                - kind: The symbol kind if found (class, function, method)
                - files: Sorted list of file paths containing the symbol
                - total_references: Approximate count of references
        """
        # Note: Indexing should be complete before calling this method
        files: Set[str] = set()
        total_refs = 0
        kind = None

        # Support partially qualified names (e.g. "ClassName::method") by using the
        # simple (unqualified) name for index keying and matches_qualified_pattern for
        # the full match check.  This mirrors the approach used in find_incoming_calls/find_callees.
        simple_name = symbol_name.split("::")[-1]

        with self.index_lock:
            # 1 & 2. Find where symbol is defined
            kind = self._find_symbol_definition_files(
                symbol_name, symbol_kind, simple_name, project_only, files
            )

            # 3. Find callers (for functions/methods)
            total_refs = self._find_symbol_caller_files(
                symbol_name, symbol_kind, simple_name, project_only, kind, files
            )

            # 4. For classes, find files that use the class
            self._find_class_reference_files(symbol_name, symbol_kind, project_only, kind, files)

        # Filter and sort files
        file_list = sorted(list(files))

        # If no references found via call graph, use file count as estimate
        if total_refs == 0:
            total_refs = len(file_list)

        return {
            "symbol": symbol_name,
            "kind": kind,
            "files": file_list,
            "total_references": total_refs,
        }

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
