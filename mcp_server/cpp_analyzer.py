#!/usr/bin/env python3
"""
Pure Python C++ Analyzer using libclang

This module provides C++ code analysis functionality using libclang bindings.
It's slower than the C++ implementation but more reliable and easier to debug.
"""

import os
import sys
import re
import time
import threading
import signal
import atexit
import gc
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple, Callable
from collections import defaultdict
import hashlib
import json
from .symbol_info import SymbolInfo
from .cache_manager import CacheManager
from .file_scanner import FileScanner
from .call_graph import CallGraphAnalyzer
from .search_engine import SearchEngine
from .cpp_analyzer_config import CppAnalyzerConfig
from .compile_commands_manager import CompileCommandsManager
from .header_tracker import HeaderProcessingTracker
from .project_identity import ProjectIdentity
from .dependency_graph import DependencyGraphBuilder
from datetime import datetime, timedelta
from contextlib import contextmanager

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics

try:
    import clang.cindex
    from clang.cindex import Index, CursorKind, TranslationUnit, Config, TranslationUnitLoadError
except ImportError:
    diagnostics.fatal("clang package not found. Install with: pip install libclang")
    sys.exit(1)


class _NoOpLock:
    """A no-op context manager that doesn't actually acquire any lock."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


# Global analyzer instance for each worker process
# This is a process-local global, NOT shared between processes
_worker_analyzer = None


def _cleanup_worker_analyzer():
    """Ensure worker analyzer resources are released on process exit."""
    global _worker_analyzer
    if _worker_analyzer is not None:
        _worker_analyzer.close()
        _worker_analyzer = None


def _process_file_worker(args_tuple):
    """
    Worker function for ProcessPoolExecutor-based parallel parsing.

    This is a module-level function (required for pickling) that uses
    a shared, process-local CppAnalyzer instance to parse a single file.
    This avoids creating a new analyzer (and new DB connection) for every file.

    Args:
        args_tuple: (project_root, config_file, file_path, force, include_dependencies, compile_args)
            where compile_args is a list of compilation arguments for the file (Phase 3 Memory Optimization)

    Returns:
        (file_path, success, was_cached, symbols, call_sites, processed_headers)
        where symbols is a list of SymbolInfo objects or empty list on failure,
        call_sites is a list of call site dicts (Phase 3),
        and processed_headers is a dict mapping header paths to file hashes
    """
    project_root, config_file, file_path, force, include_dependencies, compile_args = args_tuple
    global _worker_analyzer

    # Create a single analyzer instance per worker process (process-local)
    # Use skip_schema_recreation=True to avoid race conditions with main process
    # Main process ensures schema is current before spawning workers
    # Task 3.2: use_compile_commands_manager=False to skip loading compile_commands.json (~6-10 GB savings)
    if _worker_analyzer is None:
        diagnostics.debug(f"Worker process {os.getpid()}: Creating shared CppAnalyzer instance")
        _worker_analyzer = CppAnalyzer(
            project_root,
            config_file,
            skip_schema_recreation=True,
            use_compile_commands_manager=False,
        )
        # Ensure cleanup is called when the worker process exits
        atexit.register(_cleanup_worker_analyzer)

    # Set per-call parameters
    _worker_analyzer.include_dependencies = include_dependencies
    # Reset stateful components to prevent data leakage between files
    _worker_analyzer.call_graph_analyzer = CallGraphAnalyzer()

    # Mark this instance as isolated (no shared memory, locks not needed)
    # This is a worker process with its own memory space
    _worker_analyzer._needs_locking = False

    # Task 3.2: Set precomputed compile args (avoids loading CompileCommandsManager in worker)
    _worker_analyzer._provided_compile_args = compile_args

    # Parse the file
    success, was_cached = _worker_analyzer.index_file(file_path, force)

    # Extract symbols from this file
    # No lock needed here since this process has isolated memory
    symbols = []
    call_sites = []  # Phase 3
    processed_headers = {}  # Header tracking for this file
    if success:
        # CRITICAL FIX FOR ISSUE #8: Extract symbols from ALL files processed during this
        # source file's parsing, including headers. The worker processed both the source file
        # and any headers it includes (via first-win header claiming), so we need to return
        # ALL symbols, not just the source file's symbols.
        # Before fix: only returned source file symbols → headers missing from main process
        # After fix: return all symbols from source + headers → complete symbol extraction
        for fpath, file_symbols in _worker_analyzer.file_index.items():
            symbols.extend(file_symbols)

        # Phase 3: Extract call sites collected during this file's parsing
        call_sites = _worker_analyzer.call_graph_analyzer.get_all_call_sites()

        # Extract header tracking information (need to send back to main process)
        # This is critical for incremental analysis - without it, header changes won't be detected
        processed_headers = _worker_analyzer.header_tracker.get_processed_headers()

        # Debug
        if call_sites:
            diagnostics.debug(f"Worker extracted {len(call_sites)} call sites from {file_path}")
        # Phase 4: Task 4.3 - call_graph dict removed, only call_sites tracked in memory
        diagnostics.debug(
            f"Worker call_sites count: {len(_worker_analyzer.call_graph_analyzer.call_sites)}"
        )

    # CRITICAL FIX FOR ISSUE #14: Clean up ALL worker indexes after extracting symbols
    # Previous bug: Only removed source file, leaving headers in file_index
    # This caused headers to accumulate and be returned multiple times, leading to 70+ GB memory leak
    #
    # Since we extract ALL symbols from file_index (line 124-125), we must clear ALL entries
    # to prevent accumulation across multiple files processed by the same worker.
    # Workers don't need to keep this data - it's sent back to parent process.

    # Clear ALL entries from file_index (source + all headers processed with this file)
    _worker_analyzer.file_index.clear()

    # Clear class and function indexes completely
    _worker_analyzer.class_index.clear()
    _worker_analyzer.function_index.clear()

    # Clear USR index completely
    _worker_analyzer.usr_index.clear()

    # Clear file hashes to prevent stale hash tracking
    _worker_analyzer.file_hashes.clear()

    # Force garbage collection to free TranslationUnit objects
    # TU objects hold native C++ resources (file descriptors) that Python's GC
    # doesn't clean up frequently enough, causing FD leak in long-running workers
    gc.collect()

    return (file_path, success, was_cached, symbols, call_sites, processed_headers)


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
        self.config = CppAnalyzerConfig(self.project_root)

        # Indexes for fast lookup
        self.class_index: Dict[str, List[SymbolInfo]] = defaultdict(list)
        self.function_index: Dict[str, List[SymbolInfo]] = defaultdict(list)
        self.file_index: Dict[str, List[SymbolInfo]] = defaultdict(list)
        self.usr_index: Dict[str, SymbolInfo] = {}  # USR to symbol mapping

        # Initialize call graph analyzer
        self.call_graph_analyzer = CallGraphAnalyzer()

        # Threading/Processing
        self.index_lock = threading.RLock()

        # Track indexed files
        self.translation_units: Dict[str, TranslationUnit] = {}
        self.file_hashes: Dict[str, str] = {}
        self._no_op_lock = _NoOpLock()  # Reusable no-op lock for isolated processes
        self._thread_local = threading.local()
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
        self.file_scanner = FileScanner(self.project_root)

        # Initialize search engine (Phase 1.3: needs cache_manager for type alias lookups)
        self.search_engine = SearchEngine(
            self.class_index,
            self.function_index,
            self.file_index,
            self.usr_index,
            self.index_lock,
            cache_manager=self.cache_manager,
        )

        # Memory optimization: enable lazy loading of call sites from SQLite
        # Instead of loading ALL call sites at startup (~150-200 MB for large projects),
        # call sites are queried on-demand from the database
        self.call_graph_analyzer.cache_backend = self.cache_manager.backend

        # Apply configuration to file scanner
        self.file_scanner.EXCLUDE_DIRS = set(self.config.get_exclude_directories())
        self.file_scanner.DEPENDENCY_DIRS = set(self.config.get_dependency_directories())

        # Keep cache_dir for compatibility
        self.cache_dir = self.cache_manager.cache_dir

        # Statistics
        self.last_index_time = 0
        self.indexed_file_count = 0
        self.include_dependencies = self.config.get_include_dependencies()
        self.max_parse_retries = self.config.config.get("max_parse_retries", 2)
        self.cache_loaded = False  # Track whether cache was successfully loaded

        # Task 3.2: Memory Optimization - Support for precomputed compile args
        # When set, index_file() will use these args instead of querying CompileCommandsManager
        # This allows workers to skip loading large compile_commands.json files (~6-10 GB savings)
        self._provided_compile_args = None

        # Task 3.2: Initialize compile commands manager only if needed
        # Workers skip this to save ~6-10 GB memory by using precomputed args from main process
        if use_compile_commands_manager:
            compile_commands_config = self.config.get_compile_commands_config()
            self.compile_commands_manager = CompileCommandsManager(
                self.project_root, compile_commands_config, cache_dir=self.cache_manager.cache_dir
            )
        else:
            self.compile_commands_manager = None  # Worker mode: use precomputed args

        # Initialize header processing tracker for first-win strategy
        self.header_tracker = HeaderProcessingTracker()

        # Initialize dependency graph builder for incremental analysis
        # Note: Only initialize if using SQLite backend (has conn attribute)
        # Pass a callable to get the connection dynamically, ensuring it stays valid
        # even if the cache is recreated (e.g., due to schema mismatch or corruption)
        self.dependency_graph = None
        if hasattr(self.cache_manager.backend, "conn"):
            # Use lambda to get connection dynamically, not a static reference
            # This prevents "Cannot operate on a closed database" errors when
            # cache is recreated during operation
            self.dependency_graph = DependencyGraphBuilder(lambda: self.cache_manager.backend.conn)
            diagnostics.debug("Dependency graph builder initialized with dynamic connection")
        else:
            diagnostics.debug("Dependency graph not available (non-SQLite backend)")

        # Track compile_commands.json version for header tracking invalidation
        self.compile_commands_hash = ""
        self._calculate_compile_commands_hash()

        # Restore or reset header tracking based on compile_commands.json version
        self._restore_or_reset_header_tracking()

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

    def _get_file_hash(self, file_path: str) -> str:
        """Get hash of file contents for change detection"""
        return self.cache_manager.get_file_hash(file_path)

    def _is_project_file(self, file_path: str) -> bool:
        """
        Check if a file is a project file (not system header or external dependency).

        Uses FileScanner.is_project_file() to determine if the file is:
        - Under the project root
        - NOT in excluded directories (e.g., build/, .git/)
        - NOT in dependency directories (e.g., vcpkg_installed/, third_party/)

        Args:
            file_path: Absolute or relative path to check

        Returns:
            True if file is a project file, False otherwise

        Implements:
            REQ-10.1.3: Distinguish between project headers, system headers, and external
            REQ-10.1.4: Extract symbols only from project headers
        """
        if not file_path:
            return False

        # Convert to absolute path
        if not os.path.isabs(file_path):
            file_path = os.path.abspath(file_path)

        # Use FileScanner's logic to check if it's a project file
        return self.file_scanner.is_project_file(file_path)

    def _calculate_compile_commands_hash(self):
        """
        Calculate and store MD5 hash of compile_commands.json file.

        This hash is used to detect when the compilation database changes,
        which requires invalidating all header tracking and re-analyzing headers
        with the new compilation flags.

        Sets:
            self.compile_commands_hash: MD5 hash string, or empty if file doesn't exist

        Implements:
            REQ-10.4.1: Calculate and store hash of compile_commands.json
        """
        # Task 3.2: Skip if CompileCommandsManager not initialized (worker mode)
        if self.compile_commands_manager is None or not self.compile_commands_manager.enabled:
            self.compile_commands_hash = ""
            return

        # Get compile_commands.json path from configuration
        compile_commands_config = self.config.get_compile_commands_config()
        cc_path = self.project_root / compile_commands_config["compile_commands_path"]

        if not cc_path.exists():
            self.compile_commands_hash = ""
            return

        try:
            with open(cc_path, "rb") as f:
                self.compile_commands_hash = hashlib.md5(f.read()).hexdigest()
        except Exception as e:
            diagnostics.warning(f"Failed to calculate compile_commands.json hash: {e}")
            self.compile_commands_hash = ""

    def _restore_or_reset_header_tracking(self):
        """
        Restore header tracking from cache or reset if compile_commands.json changed.

        Checks if cached compile_commands.json hash matches current hash:
        - If match: Restore processed headers from cache
        - If mismatch: Clear all header tracking (full re-analysis needed)
        - If no cache: Start fresh

        Implements:
            REQ-10.4.2: Compare current hash with cached hash
            REQ-10.4.3: Clear tracking if hash changed
            REQ-10.5.3: Restore state if hash matches
        """
        tracker_cache_path = self.cache_dir / "header_tracker.json"

        if not tracker_cache_path.exists():
            # No cache file - start fresh
            return

        try:
            with open(tracker_cache_path, "r") as f:
                cache_data = json.load(f)

            cached_cc_hash = cache_data.get("compile_commands_hash", "")

            if cached_cc_hash == self.compile_commands_hash:
                # Hash matches - restore header tracking state
                processed_headers = cache_data.get("processed_headers", {})
                self.header_tracker.restore_processed_headers(processed_headers)
                diagnostics.debug(f"Restored {len(processed_headers)} processed headers from cache")
            else:
                # Hash mismatch - compile_commands.json changed
                diagnostics.debug("compile_commands.json changed - resetting header tracking")
                self.header_tracker.clear_all()

        except (json.JSONDecodeError, IOError, OSError) as e:
            # JSON corruption or file access errors - this can happen with concurrent writes
            # in multi-process mode. Simply start fresh.
            diagnostics.debug(
                f"Header tracking cache corrupted or inaccessible, starting fresh: {e}"
            )
            # Remove corrupted cache file
            try:
                tracker_cache_path.unlink(missing_ok=True)
            except:
                pass
            # Start fresh
            self.header_tracker.clear_all()
        except Exception as e:
            diagnostics.warning(f"Unexpected error restoring header tracking from cache: {e}")
            # On error, start fresh
            self.header_tracker.clear_all()

    def _save_header_tracking(self):
        """
        Save header tracking state to disk cache.

        Persists the current state of the header tracker including:
        - compile_commands.json hash
        - Processed headers with their file hashes
        - Timestamp

        Cache file location: {cache_dir}/header_tracker.json

        Implements:
            REQ-10.5.1: Persist header processing state to disk
            REQ-10.5.2: Include version, hash, processed headers, timestamp
            REQ-10.5.4: Save after each source file analysis
            REQ-10.5.5: Store in project-specific cache directory
        """
        tracker_cache_path = self.cache_dir / "header_tracker.json"

        try:
            # Get current processed headers from tracker
            processed_headers = self.header_tracker.get_processed_headers()

            # Build cache data
            cache_data = {
                "version": "1.0",
                "compile_commands_hash": self.compile_commands_hash,
                "processed_headers": processed_headers,
                "timestamp": time.time(),
            }

            # Ensure cache directory exists
            tracker_cache_path.parent.mkdir(parents=True, exist_ok=True)

            # Write to file (atomic write via temp file)
            temp_path = tracker_cache_path.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                json.dump(cache_data, f, indent=2)

            # Atomic rename
            temp_path.replace(tracker_cache_path)

        except Exception as e:
            diagnostics.warning(f"Failed to save header tracking cache: {e}")

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
        index = getattr(self._thread_local, "index", None)
        if index is None:
            index = Index.create()
            self._thread_local.index = index
        return index

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

    def _remove_symbol_from_indexes(self, symbol: SymbolInfo):
        """
        Remove a symbol from all indexes.

        Used by definition-wins logic to replace declarations with definitions.

        Args:
            symbol: SymbolInfo to remove from indexes
        """
        # Remove from class_index or function_index
        if symbol.kind in ("class", "struct"):
            if symbol.name in self.class_index:
                try:
                    self.class_index[symbol.name].remove(symbol)
                    # Remove empty lists
                    if not self.class_index[symbol.name]:
                        del self.class_index[symbol.name]
                except ValueError:
                    # Symbol not in list (shouldn't happen, but be defensive)
                    pass
        else:
            if symbol.name in self.function_index:
                try:
                    self.function_index[symbol.name].remove(symbol)
                    # Remove empty lists
                    if not self.function_index[symbol.name]:
                        del self.function_index[symbol.name]
                except ValueError:
                    pass

        # Remove from usr_index
        if symbol.usr and symbol.usr in self.usr_index:
            del self.usr_index[symbol.usr]

        # Remove from file_index
        if symbol.file and symbol.file in self.file_index:
            try:
                self.file_index[symbol.file].remove(symbol)
                # Remove empty lists
                if not self.file_index[symbol.file]:
                    del self.file_index[symbol.file]
            except ValueError:
                pass

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

                    # Definition-wins: If new symbol is a definition and existing is not, replace
                    if info.is_definition and not existing_symbol.is_definition:
                        diagnostics.debug(
                            f"Definition-wins: Replacing declaration of {info.name} with definition "
                            f"(from {existing_symbol.file}:{existing_symbol.line} to {info.file}:{info.line})"
                        )

                        # CRITICAL FIX FOR ISSUE #8:
                        # When applying definition-wins, we want to replace in usr_index,
                        # class_index, and function_index, but KEEP the declaration in file_index
                        # so that headers remain indexed with their symbols.
                        # Remove from class_index or function_index
                        if existing_symbol.kind in ("class", "struct"):
                            if existing_symbol.name in self.class_index:
                                try:
                                    self.class_index[existing_symbol.name].remove(existing_symbol)
                                    if not self.class_index[existing_symbol.name]:
                                        del self.class_index[existing_symbol.name]
                                except ValueError:
                                    pass
                        else:
                            if existing_symbol.name in self.function_index:
                                try:
                                    self.function_index[existing_symbol.name].remove(
                                        existing_symbol
                                    )
                                    if not self.function_index[existing_symbol.name]:
                                        del self.function_index[existing_symbol.name]
                                except ValueError:
                                    pass

                        # Remove from usr_index (will be replaced with definition)
                        if existing_symbol.usr and existing_symbol.usr in self.usr_index:
                            del self.usr_index[existing_symbol.usr]

                        # NOTE: We intentionally DO NOT remove from file_index here
                        # The declaration stays in file_index under its header file
                        # The definition will be added to file_index under its source file

                        # Add new definition to all indexes (fall through to add logic below)
                        # Note: Don't increment added_count as we're replacing, not adding
                    else:
                        # Keep existing symbol (either both are declarations, or existing is already a definition)
                        continue

                # New symbol or replacement - add to all indexes
                # Issue #99: Include template kinds in class_index
                if info.kind in ("class", "struct", "class_template", "partial_specialization"):
                    self.class_index[info.name].append(info)
                else:
                    self.function_index[info.name].append(info)

                if info.usr:
                    self.usr_index[info.usr] = info

                # Add to file_index (with deduplication check for Issue #8)
                # We keep both declarations and definitions in file_index, but avoid exact duplicates
                if info.file:
                    if info.file not in self.file_index:
                        self.file_index[info.file] = []

                    # Check if this exact symbol (same USR, same file) is already in file_index
                    # This can happen when the same header is processed multiple times
                    already_in_file_index = False
                    if info.usr:
                        for existing in self.file_index[info.file]:
                            if existing.usr == info.usr:
                                already_in_file_index = True
                                break

                    if not already_in_file_index:
                        self.file_index[info.file].append(info)

                added_count += 1

            # Add all collected call relationships (Phase 3: now includes location)
            if calls_buffer:
                diagnostics.debug(f"Processing {len(calls_buffer)} calls from buffer")
                if calls_buffer:
                    diagnostics.debug(
                        f"First call format: {calls_buffer[0] if calls_buffer else 'empty'}"
                    )
            for call_info in calls_buffer:
                if len(call_info) == 5:
                    # Phase 3 format: (caller_usr, callee_usr, file, line, column)
                    caller_usr, called_usr, call_file, call_line, call_column = call_info
                    self.call_graph_analyzer.add_call(
                        caller_usr, called_usr, call_file, call_line, call_column
                    )
                elif len(call_info) == 2:
                    # Legacy format for compatibility: (caller_usr, callee_usr)
                    caller_usr, called_usr = call_info
                    self.call_graph_analyzer.add_call(caller_usr, called_usr)
                else:
                    diagnostics.warning(f"Unexpected call_info format: {call_info}")

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

    def _compute_compile_args_hash(self, args: List[str]) -> str:
        """Compute hash of compilation arguments for cache validation"""
        # Sort and join args to create a consistent hash
        args_str = " ".join(sorted(args))
        return hashlib.md5(args_str.encode()).hexdigest()

    def _is_system_header_diagnostic(self, diag) -> bool:
        """Check if a diagnostic originates from a system header.

        System headers include:
        - Compiler built-in headers (clang/*/include/)
        - SDK headers (under -isysroot paths)
        - Standard library headers

        Args:
            diag: libclang diagnostic object

        Returns:
            True if the diagnostic is from a system header, False otherwise
        """
        if not diag.location.file:
            return False

        file_path = str(diag.location.file)

        # Check for common system header patterns
        system_patterns = [
            "/usr/include/",
            "/usr/local/include/",
            "lib/clang/",  # Clang builtin headers (e.g., arm_acle.h, arm_neon.h)
            "/Library/Developer/CommandLineTools/usr/lib/clang/",  # macOS
            "/Library/Developer/CommandLineTools/SDKs/",  # macOS SDK
            "C:\\Program Files",  # Windows system
            "/opt/homebrew/",  # macOS Homebrew
        ]

        return any(pattern in file_path for pattern in system_patterns)

    def _extract_diagnostics(self, tu) -> tuple[List, List]:
        """Extract error and warning diagnostics from translation unit.

        Filters out errors from system headers to avoid false positives from
        incompatible compiler intrinsics (e.g., ARM built-ins on Mac M1).

        Returns:
            (error_diagnostics, warning_diagnostics) - Lists of diagnostic objects
        """
        error_diagnostics = []
        warning_diagnostics = []

        if tu and hasattr(tu, "diagnostics"):
            for diag in tu.diagnostics:
                severity = diag.severity
                # Severity levels: Ignored=0, Note=1, Warning=2, Error=3, Fatal=4

                # Filter out errors from system headers
                # These are often false positives due to compiler version mismatches
                if severity >= 3:  # Error or Fatal
                    if not self._is_system_header_diagnostic(diag):
                        error_diagnostics.append(diag)
                    else:
                        # Downgrade system header errors to warnings for logging
                        warning_diagnostics.append(diag)
                elif severity == 2:  # Warning
                    warning_diagnostics.append(diag)

        return error_diagnostics, warning_diagnostics

    def _format_diagnostics(self, diagnostics_list, max_count: int = 5) -> str:
        """Format libclang diagnostics into a readable string.

        Args:
            diagnostics_list: List of libclang diagnostic objects
            max_count: Maximum number of diagnostics to include

        Returns:
            Formatted string with diagnostic messages
        """
        if not diagnostics_list:
            return ""

        messages = []
        for diag in diagnostics_list[:max_count]:
            # Format location
            if diag.location.file:
                location = f"{diag.location.file}:{diag.location.line}:{diag.location.column}"
            else:
                location = "unknown location"

            # Get severity name
            severity_names = {0: "ignored", 1: "note", 2: "warning", 3: "error", 4: "fatal"}
            severity_name = severity_names.get(diag.severity, "unknown")

            messages.append(f"[{severity_name}] {location}: {diag.spelling}")

        total = len(diagnostics_list)
        if total > max_count:
            messages.append(f"... and {total - max_count} more")

        return "\n".join(messages)

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
        """Save parsed symbols for a single file to cache"""
        self.cache_manager.save_file_cache(
            file_path, symbols, file_hash, compile_args_hash, success, error_message, retry_count
        )

    def _load_file_cache(
        self, file_path: str, current_hash: str, compile_args_hash: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Load cached data for a file if still valid

        Returns:
            Dict with 'symbols', 'success', 'error_message', 'retry_count' or None
        """
        return self.cache_manager.load_file_cache(file_path, current_hash, compile_args_hash)

    def _is_project_file(self, file_path: str) -> bool:
        """Check if file is part of the project (not a dependency)"""
        return self.file_scanner.is_project_file(file_path)

    def _should_skip_file(self, file_path: str) -> bool:
        """Check if file should be skipped"""
        # Update file scanner with current dependencies setting
        self.file_scanner.include_dependencies = self.include_dependencies
        return self.file_scanner.should_skip_file(file_path)

    def _find_cpp_files(self, include_dependencies: bool = False) -> List[str]:
        """Find all C++ files in the project

        When compile_commands.json is loaded and has entries, returns ONLY the files
        listed in it. Otherwise, scans for all C++ files based on extensions.
        """
        # If compile_commands.json is loaded and has entries, use only those files
        # Task 3.2: Skip if CompileCommandsManager not initialized (worker mode)
        if self.compile_commands_manager is not None and self.compile_commands_manager.enabled:
            compile_commands_files = self.compile_commands_manager.get_all_files()
            if compile_commands_files:
                diagnostics.debug(
                    f"Using {len(compile_commands_files)} files from compile_commands.json"
                )
                return compile_commands_files

        # Fall back to scanning all C++ files
        # Update file scanner with dependencies setting
        self.file_scanner.include_dependencies = include_dependencies
        return self.file_scanner.find_cpp_files()

    def _get_qualified_name(self, cursor) -> str:
        """
        Build fully qualified name by walking up semantic parent chain.

        Handles:
        - Nested namespaces: ns1::ns2::ClassName
        - Nested classes: Outer::Inner::method
        - Anonymous namespaces: (anonymous namespace)::Internal
        - Global namespace: just the symbol name

        Args:
            cursor: libclang cursor

        Returns:
            Qualified name like "ns1::ns2::ClassName::method"
            For global namespace: just cursor.spelling
        """
        parts = []
        current = cursor
        max_depth = 100  # Safety limit to prevent infinite loops
        depth = 0
        visited = set()  # Detect circular references

        while current and depth < max_depth:
            # Check for circular reference (should never happen, but safety first)
            cursor_id = id(current)
            if cursor_id in visited:
                diagnostics.warning(
                    f"Circular reference detected in semantic parent chain for {cursor.spelling}"
                )
                break
            visited.add(cursor_id)

            if current.kind == CursorKind.TRANSLATION_UNIT:
                break

            # Add this cursor's name to the path
            if current.spelling:
                parts.append(current.spelling)
            elif current.kind == CursorKind.NAMESPACE and current.is_anonymous():
                # Represent anonymous namespaces explicitly
                parts.append("(anonymous namespace)")

            current = current.semantic_parent
            depth += 1

        if depth >= max_depth:
            diagnostics.warning(
                f"Maximum depth ({max_depth}) exceeded when building qualified name for {cursor.spelling}"
            )

        parts.reverse()
        return "::".join(parts) if parts else cursor.spelling

    def _extract_namespace(self, qualified_name: str) -> str:
        """
        Extract namespace portion from qualified name.

        Includes parent classes in namespace (Q8 decision from design).

        Examples:
            "ns1::ns2::Class" → "ns1::ns2"
            "ns1::Outer::Inner" → "ns1::Outer" (includes parent class)
            "GlobalClass" → ""

        Args:
            qualified_name: Fully qualified name

        Returns:
            Namespace portion (empty string for global namespace)
        """
        if "::" not in qualified_name:
            return ""

        parts = qualified_name.split("::")
        return "::".join(parts[:-1])

    def _get_base_classes(self, cursor) -> List[str]:
        """
        Extract base class names from a class cursor.

        Uses canonical type to ensure template arguments include qualified names.
        For example: Container<ns1::Foo> instead of Container<Foo>

        Task T3.2.1: Qualified Names Phase 1
        """
        base_classes = []
        for child in cursor.get_children():
            if child.kind == CursorKind.CXX_BASE_SPECIFIER:
                # Get the referenced class type
                base_type = child.type

                # Use canonical type for template args expansion + qualification
                # This ensures template arguments have fully qualified names
                # Example: Container<FooPtr> → Container<std::unique_ptr<ns1::Foo>>
                canonical_type = base_type.get_canonical()
                base_name_qualified = canonical_type.spelling

                # Clean up the type name (remove "class " or "struct " prefix if present)
                if base_name_qualified.startswith("class "):
                    base_name_qualified = base_name_qualified[6:]
                elif base_name_qualified.startswith("struct "):
                    base_name_qualified = base_name_qualified[7:]

                base_classes.append(base_name_qualified)
        return base_classes

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
        results = []

        with self.index_lock:
            # Check class_index for class templates and specializations
            if base_name in self.class_index:
                for symbol in self.class_index[base_name]:
                    # Include if it's a template or a specialization
                    if symbol.kind in (
                        "class_template",
                        "partial_specialization",
                        "class",
                        "struct",
                    ):
                        # For regular classes, verify they're template specializations by USR
                        if symbol.kind in ("class", "struct"):
                            # Check if USR indicates it's a template specialization
                            # Template specializations have >#... in their USR
                            if symbol.usr and ">#" in symbol.usr:
                                results.append(symbol)
                        else:
                            # Templates and partial specializations always included
                            results.append(symbol)

            # Check function_index for function templates and specializations
            if base_name in self.function_index:
                for symbol in self.function_index[base_name]:
                    if symbol.kind in ("function_template", "function", "method"):
                        # For regular functions, verify template specialization by USR or flag
                        if symbol.kind in ("function", "method"):
                            # Check is_template_specialization flag or USR pattern
                            if symbol.is_template_specialization or (
                                symbol.usr and ("<#" in symbol.usr or ">#" in symbol.usr)
                            ):
                                results.append(symbol)
                        else:
                            # Function templates always included
                            results.append(symbol)

        return results

    def _extract_line_range_info(self, cursor) -> dict:
        """
        Extract line range and location information from a cursor.
        Handles declaration/definition split for header/source files.

        Phase 1: LLM Integration - Critical bridging data

        Args:
            cursor: libclang cursor

        Returns:
            Dictionary with:
                - file: Primary location file path (uses extent.start for accurate attribution)
                - line: Primary location line
                - column: Primary location column
                - start_line: Start line of symbol extent
                - end_line: End line of symbol extent
                - header_file: Header file path (if declaration separate from definition)
                - header_line: Header declaration line
                - header_start_line: Header declaration start line
                - header_end_line: Header declaration end line
        """
        location = cursor.location

        # CRITICAL FIX FOR ISSUE #8 (ThreadPoolExecutor mode):
        # Use cursor.extent.start.file instead of cursor.location.file
        # Reason: For function declarations in headers, cursor.location points to the
        # DEFINITION location (in .cpp), not the DECLARATION location (in .h).
        # cursor.extent.start.file gives us where the cursor actually appears in the AST.
        # This ensures header symbols are correctly attributed to header files.
        primary_file = ""

        # IMPORTANT: cursor.location.file can be different from cursor.extent.start.file
        # For declarations in headers, we want extent (where cursor appears in source)
        # For definitions, both should be the same
        if cursor.extent and cursor.extent.start.file:
            primary_file = str(cursor.extent.start.file.name)
        elif location.file:
            # Fallback to location.file if extent not available
            primary_file = str(location.file.name)

        result = {
            "file": primary_file,
            "line": location.line,
            "column": location.column,
            "start_line": None,
            "end_line": None,
            "header_file": None,
            "header_line": None,
            "header_start_line": None,
            "header_end_line": None,
        }

        # Extract line range from extent
        try:
            extent = cursor.extent
            if extent and extent.start.file and extent.end.file:
                result["start_line"] = extent.start.line
                result["end_line"] = extent.end.line
        except Exception as e:
            # If extent extraction fails, fall back to single line
            diagnostics.debug(f"Could not extract extent for {cursor.spelling}: {e}")
            result["start_line"] = location.line
            result["end_line"] = location.line

        # Check for declaration/definition split
        try:
            # cursor.is_definition() tells us if this cursor IS a definition
            # cursor.get_definition() gets the definition cursor if this is a declaration
            definition_cursor = cursor.get_definition()

            if definition_cursor and definition_cursor != cursor:
                # This cursor is a declaration, definition exists elsewhere
                decl_location = cursor.location
                def_location = definition_cursor.location

                if decl_location.file and def_location.file:
                    decl_file = str(decl_location.file.name)
                    def_file = str(def_location.file.name)

                    # Check if declaration is in a header file
                    is_decl_header = decl_file.endswith((".h", ".hpp", ".hxx", ".hh"))
                    is_def_header = def_file.endswith((".h", ".hpp", ".hxx", ".hh"))

                    if is_decl_header and not is_def_header:
                        # Declaration in header, definition in source
                        # CRITICAL FIX FOR ISSUE #8:
                        # Store alternate location (definition) in header_* fields
                        # But DO NOT overwrite result["file"] - keep cursor's actual location
                        # This ensures declarations stay in file_index under their header file
                        result["header_file"] = def_file  # Store definition location
                        result["header_line"] = def_location.line
                        try:
                            def_extent = definition_cursor.extent
                            if def_extent and def_extent.start.file:
                                result["header_start_line"] = def_extent.start.line
                                result["header_end_line"] = def_extent.end.line
                        except Exception:
                            result["header_start_line"] = def_location.line
                            result["header_end_line"] = def_location.line

                        # NOTE: We intentionally do NOT overwrite result["file"] here
                        # The cursor's location (declaration in header) is the primary location

                    elif is_def_header and is_decl_header:
                        # Both in headers (e.g., template, inline)
                        # Primary location stays as declaration
                        # No separate header info needed
                        pass

        except Exception as e:
            # Declaration/definition tracking is best-effort
            diagnostics.debug(f"Could not track declaration/definition for {cursor.spelling}: {e}")

        return result

    def _extract_documentation(self, cursor) -> dict:
        """
        Extract documentation from cursor comments.

        Phase 2: LLM Integration - Documentation extraction for symbol understanding

        Args:
            cursor: libclang cursor

        Returns:
            Dictionary with:
                - brief: Brief description (first line, max 200 chars)
                - doc_comment: Full documentation comment (max 4000 chars)
        """
        result = {"brief": None, "doc_comment": None}

        try:
            # Extract brief comment (first line/sentence)
            brief_comment = cursor.brief_comment
            if brief_comment:
                brief = brief_comment.strip()
                # Truncate if too long
                if len(brief) > 200:
                    brief = brief[:200]
                result["brief"] = brief

            # Extract full documentation comment
            raw_comment = cursor.raw_comment
            if raw_comment:
                doc_comment = raw_comment.strip()
                # Truncate if too long (max 4000 chars including "..." suffix)
                if len(doc_comment) > 4000:
                    doc_comment = doc_comment[:3997] + "..."
                result["doc_comment"] = doc_comment

                # If no brief but have raw comment, extract first meaningful line
                if not result["brief"] and doc_comment:
                    lines = doc_comment.split("\n")
                    for line in lines:
                        # Skip comment markers and empty lines
                        cleaned = line.strip().lstrip("/*!/").lstrip("*").strip()
                        if cleaned and not cleaned.startswith("@"):
                            # Found first meaningful line
                            if len(cleaned) > 200:
                                cleaned = cleaned[:200]
                            result["brief"] = cleaned
                            break

        except Exception as e:
            # Documentation extraction is best-effort, failures are not critical
            diagnostics.debug(f"Could not extract documentation for {cursor.spelling}: {e}")

        return result

    def _extract_template_parameters(self, cursor) -> Optional[str]:
        """
        Extract template parameters from a template cursor (CLASS_TEMPLATE, FUNCTION_TEMPLATE, etc.).

        Task 3.2: Template Parameter Extraction - Template Search Support

        This function extracts template parameter information including:
        - name: Parameter name (e.g., "T", "N")
        - kind: "type" for typename/class params, "non_type" for value params
        - type: For non-type params, the parameter type (e.g., "int", "size_t")

        Returns:
            JSON string of template parameters, or None if no parameters found.
            Example: '[{"name": "T", "kind": "type"}, {"name": "N", "kind": "non_type", "type": "int"}]'
        """
        from clang.cindex import CursorKind

        template_params = []

        for child in cursor.get_children():
            if child.kind == CursorKind.TEMPLATE_TYPE_PARAMETER:
                # Type parameter (e.g., "typename T", "class U")
                template_params.append({"name": child.spelling, "kind": "type"})
            elif child.kind == CursorKind.TEMPLATE_NON_TYPE_PARAMETER:
                # Non-type parameter (e.g., "int N", "size_t Size")
                template_params.append(
                    {"name": child.spelling, "kind": "non_type", "type": child.type.spelling}
                )
            elif child.kind == CursorKind.TEMPLATE_TEMPLATE_PARAMETER:
                # Template template parameter (e.g., "template<typename> class Container")
                template_params.append({"name": child.spelling, "kind": "template"})

        if template_params:
            import json

            return json.dumps(template_params)
        return None

    def _get_primary_template_usr(self, cursor) -> Optional[str]:
        """
        Get the USR of the primary template for a template specialization.

        Task 3.4: Link Specializations to Primary - Template Search Support

        Uses libclang's clang_getSpecializedCursorTemplate() to find the primary template
        for partial or full template specializations.

        Args:
            cursor: libclang cursor representing a template specialization

        Returns:
            USR of the primary template, or None if cursor is not a specialization
            or if the primary template cannot be determined.
        """
        from clang import cindex

        try:
            # Call the C API directly since Python bindings don't expose this
            specialized_cursor = cindex.conf.lib.clang_getSpecializedCursorTemplate(cursor)
            if specialized_cursor and not specialized_cursor.kind.is_invalid():
                usr = specialized_cursor.get_usr()
                if usr:
                    return usr
        except Exception:
            # If the API call fails, return None gracefully
            pass

        return None

    def _extract_alias_info(self, cursor) -> dict:
        """
        Extract type alias information from TYPEDEF_DECL, TYPE_ALIAS_DECL, or TYPE_ALIAS_TEMPLATE_DECL cursor.

        Phase 1.3: Type Alias Tracking - Alias information extraction
        Phase 2.0: Template Alias Tracking - Template parameter extraction

        Args:
            cursor: libclang cursor (must be TYPEDEF_DECL, TYPE_ALIAS_DECL, or TYPE_ALIAS_TEMPLATE_DECL)

        Returns:
            Dictionary with:
                - alias_name: Short name (e.g., "WidgetAlias", "Ptr")
                - qualified_name: Fully qualified (e.g., "foo::WidgetAlias", "utils::Ptr")
                - target_type: Immediate target spelling
                - canonical_type: Final resolved type spelling
                - file: File where alias is defined
                - line: Line number
                - column: Column number
                - alias_kind: 'using' or 'typedef'
                - namespace: Namespace portion (e.g., "foo")
                - is_template_alias: True for template aliases (Phase 2.0)
                - template_params: JSON string of template parameters (Phase 2.0)
                - created_at: Unix timestamp
        """
        import time
        import json
        from clang.cindex import CursorKind

        # Detect if this is a template alias
        is_template_alias = cursor.kind == CursorKind.TYPE_ALIAS_TEMPLATE_DECL

        # Initialize template parameters
        template_params = []

        # For template aliases, extract from nested structure
        if is_template_alias:
            # TYPE_ALIAS_TEMPLATE_DECL has children:
            # - TEMPLATE_TYPE_PARAMETER cursors (one per template parameter)
            # - TEMPLATE_NON_TYPE_PARAMETER cursors (for non-type params)
            # - TYPE_ALIAS_DECL cursor (the actual alias declaration)

            type_alias_decl = None

            for child in cursor.get_children():
                if child.kind == CursorKind.TEMPLATE_TYPE_PARAMETER:
                    # Type parameter (e.g., "typename T")
                    template_params.append({"name": child.spelling, "kind": "type"})
                elif child.kind == CursorKind.TEMPLATE_NON_TYPE_PARAMETER:
                    # Non-type parameter (e.g., "int N")
                    template_params.append(
                        {"name": child.spelling, "kind": "non_type", "type": child.type.spelling}
                    )
                elif child.kind == CursorKind.TYPE_ALIAS_DECL:
                    # The nested alias declaration
                    type_alias_decl = child

            # Extract from nested TYPE_ALIAS_DECL
            if type_alias_decl:
                alias_name = type_alias_decl.spelling
                qualified_name = self._get_qualified_name(type_alias_decl)
                namespace = self._extract_namespace(qualified_name)

                try:
                    underlying_type = type_alias_decl.underlying_typedef_type
                    target_type = underlying_type.spelling
                    canonical_type = underlying_type.get_canonical().spelling
                except AttributeError:
                    target_type = type_alias_decl.type.spelling
                    canonical_type = type_alias_decl.type.get_canonical().spelling

                # Extract location from template declaration (not nested alias)
                file_path = str(cursor.location.file.name) if cursor.location.file else ""
                line = cursor.location.line
                column = cursor.location.column
            else:
                # Fallback: extract from template cursor itself
                alias_name = cursor.spelling
                qualified_name = self._get_qualified_name(cursor)
                namespace = self._extract_namespace(qualified_name)
                target_type = ""
                canonical_type = ""
                file_path = str(cursor.location.file.name) if cursor.location.file else ""
                line = cursor.location.line
                column = cursor.location.column

            alias_kind = "using"  # Template aliases use 'using' syntax

        else:
            # Simple alias (Phase 1 logic)
            alias_name = cursor.spelling
            qualified_name = self._get_qualified_name(cursor)
            namespace = self._extract_namespace(qualified_name)

            # Extract target type and canonical type
            try:
                underlying_type = cursor.underlying_typedef_type
                target_type = underlying_type.spelling
                canonical_type = underlying_type.get_canonical().spelling
            except AttributeError:
                target_type = cursor.type.spelling
                canonical_type = cursor.type.get_canonical().spelling

            # Determine alias kind
            if cursor.kind == CursorKind.TYPE_ALIAS_DECL:
                alias_kind = "using"
            elif cursor.kind == CursorKind.TYPEDEF_DECL:
                alias_kind = "typedef"
            else:
                alias_kind = "unknown"

            # Extract location info
            file_path = str(cursor.location.file.name) if cursor.location.file else ""
            line = cursor.location.line
            column = cursor.location.column

        return {
            "alias_name": alias_name,
            "qualified_name": qualified_name,
            "target_type": target_type,
            "canonical_type": canonical_type,
            "file": file_path,
            "line": line,
            "column": column,
            "alias_kind": alias_kind,
            "namespace": namespace,
            "is_template_alias": is_template_alias,
            "template_params": json.dumps(template_params) if template_params else None,
            "created_at": time.time(),
        }

    def _detect_template_specialization(self, cursor) -> bool:
        """
        Detect if cursor represents a template specialization.

        Uses cursor.kind + displayname analysis to distinguish:
        - Generic templates (FUNCTION_TEMPLATE): False
        - Explicit specializations (displayname contains '<>'): True
        - Regular overloads (no template arguments): False

        This metadata helps distinguish between:
        - template<typename T> void foo(T) → False (generic template)
        - template<> void foo<int>(int) → True (specialization)
        - void foo(double) → False (regular overload)

        Returns:
            True if this is a template specialization, False otherwise

        Implements:
            Phase 3 (T3.3.2): Function overload metadata
        """
        try:
            kind = cursor.kind
        except ValueError:
            # Unknown cursor kind (version mismatch)
            return False

        # Generic templates are not specializations
        if kind == CursorKind.FUNCTION_TEMPLATE:
            return False

        # Check for template arguments in display name
        # Works for both functions and classes
        if kind in (
            CursorKind.FUNCTION_DECL,
            CursorKind.CXX_METHOD,
            CursorKind.CLASS_DECL,
            CursorKind.STRUCT_DECL,
        ):
            try:
                displayname = cursor.displayname
                # Template specializations have '<' and '>' in their display name
                # e.g., "foo<int>" vs "foo", "Container<int>" vs "Container"
                # Check that displayname is a string (not Mock or other non-iterable)
                if isinstance(displayname, str):
                    return "<" in displayname and ">" in displayname
            except (AttributeError, TypeError):
                # Handle cases where displayname is not accessible or not iterable
                return False

        return False

    def _process_cursor(
        self,
        cursor,
        should_extract_from_file=None,
        parent_class: str = "",
        parent_function_usr: str = "",
    ):
        """
        Process a cursor and its children, extracting symbols based on file filter.

        Args:
            cursor: libclang cursor to process
            should_extract_from_file: Optional callback function(file_path) -> bool
                                     If provided, only extract symbols from files where this returns True
                                     If None, extract from all files (backward compatibility)
            parent_class: Name of parent class for nested symbols
            parent_function_usr: USR of parent function for call tracking

        Design:
            - Traverse AST of project files only (skip system headers for performance)
            - Only extract symbols when should_extract_from_file returns True
            - This enables multi-file extraction (source + headers) in single pass
            - Collects symbols in thread-local buffers to avoid lock contention
            - Early exit optimization: skip non-project file subtrees (5-7x speedup)

        Implements:
            REQ-10.1.6: Use cursor.location.file to determine which file symbol belongs to
        """
        # Get thread-local buffers for lock-free collection
        symbols_buffer, calls_buffer, aliases_buffer = self._get_thread_local_buffers()

        # Determine if we should extract from this cursor's file
        should_extract = True
        if cursor.location.file and should_extract_from_file is not None:
            file_path = str(cursor.location.file.name)
            should_extract = should_extract_from_file(file_path)

            # PERFORMANCE OPTIMIZATION: Early exit for non-project files
            # Skip traversing AST subtrees from system headers and external dependencies
            # This provides 5-7x speedup by avoiding millions of unnecessary node visits
            # Safe because:
            # - We don't extract symbols from non-project files (should_extract=False)
            # - We're not tracking calls (parent_function_usr empty means not in project function)
            # - Dependency discovery uses tu.get_includes() API (doesn't need AST traversal)
            if not should_extract and not parent_function_usr:
                return

        # Get cursor kind, handling unknown kinds from version mismatches
        try:
            kind = cursor.kind
        except ValueError as e:
            # This can happen when libclang library supports newer C++ features
            # but Python bindings have outdated cursor kind enums
            # Just skip this cursor and continue with children
            diagnostics.debug(f"Skipping cursor with unknown kind: {e}")
            for child in cursor.get_children():
                self._process_cursor(
                    child, should_extract_from_file, parent_class, parent_function_usr
                )
            return

        # Process template classes (generic and partial specializations)
        # Issue #99: Template Class Search and Specialization Discovery
        if kind in (
            CursorKind.CLASS_TEMPLATE,
            CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION,
        ):
            if cursor.spelling and should_extract:
                # Extract qualified name and namespace
                qualified_name = self._get_qualified_name(cursor)
                namespace = self._extract_namespace(qualified_name)

                # Get base classes (templates can inherit too)
                base_classes = self._get_base_classes(cursor)

                # Extract line range and location info
                loc_info = self._extract_line_range_info(cursor)

                # Extract documentation
                doc_info = self._extract_documentation(cursor)

                # Extract template parameters (Task 3.2)
                template_params = self._extract_template_parameters(cursor)

                # Determine kind and get primary template USR for specializations
                if kind == CursorKind.CLASS_TEMPLATE:
                    symbol_kind = "class_template"
                    primary_usr = None  # Primary templates don't have a parent
                else:  # CLASS_TEMPLATE_PARTIAL_SPECIALIZATION
                    symbol_kind = "partial_specialization"
                    # Task 3.4: Link to primary template
                    primary_usr = self._get_primary_template_usr(cursor)

                info = SymbolInfo(
                    name=cursor.spelling,
                    kind=symbol_kind,
                    file=loc_info["file"],
                    line=loc_info["line"],
                    column=loc_info["column"],
                    qualified_name=qualified_name,
                    is_project=(
                        self._is_project_file(loc_info["file"]) if loc_info["file"] else False
                    ),
                    namespace=namespace,
                    parent_class="",
                    base_classes=base_classes,
                    usr=cursor.get_usr() if cursor.get_usr() else "",
                    # Template tracking (Template Search Support)
                    is_template=True,  # CLASS_TEMPLATE and partial specs are templates
                    template_kind=symbol_kind,  # 'class_template' or 'partial_specialization'
                    template_parameters=template_params,  # Task 3.2: JSON array of template params
                    primary_template_usr=primary_usr,  # Task 3.4: Link to primary template
                    # Line ranges
                    start_line=loc_info["start_line"],
                    end_line=loc_info["end_line"],
                    header_file=loc_info["header_file"],
                    header_line=loc_info["header_line"],
                    header_start_line=loc_info["header_start_line"],
                    header_end_line=loc_info["header_end_line"],
                    # Definition-wins logic
                    is_definition=cursor.is_definition(),
                    # Documentation
                    brief=doc_info["brief"],
                    doc_comment=doc_info["doc_comment"],
                )

                # Collect symbol in thread-local buffer
                symbols_buffer.append(info)

            # Always process children (template members, nested types, etc.)
            for child in cursor.get_children():
                self._process_cursor(
                    child,
                    should_extract_from_file,
                    cursor.spelling if should_extract else parent_class,
                    parent_function_usr,
                )
            return  # Don't process children again below

        # Process classes and structs (only if should extract)
        if kind in (CursorKind.CLASS_DECL, CursorKind.STRUCT_DECL):
            if cursor.spelling and should_extract:
                # Extract qualified name and namespace (Qualified Names Phase 1)
                qualified_name = self._get_qualified_name(cursor)
                namespace = self._extract_namespace(qualified_name)

                # Get base classes
                base_classes = self._get_base_classes(cursor)

                # Extract line range and location info (Phase 1: LLM Integration)
                loc_info = self._extract_line_range_info(cursor)

                # Extract documentation (Phase 2: LLM Integration)
                doc_info = self._extract_documentation(cursor)

                # Detect template specialization (Template Search Support)
                is_class_template_spec = self._detect_template_specialization(cursor)

                # Task 3.4: Get primary template USR for full specializations
                primary_usr = None
                if is_class_template_spec:
                    primary_usr = self._get_primary_template_usr(cursor)

                info = SymbolInfo(
                    name=cursor.spelling,
                    kind="class" if kind == CursorKind.CLASS_DECL else "struct",
                    file=loc_info["file"],
                    line=loc_info["line"],
                    column=loc_info["column"],
                    qualified_name=qualified_name,
                    is_project=(
                        self._is_project_file(loc_info["file"]) if loc_info["file"] else False
                    ),
                    namespace=namespace,
                    parent_class="",  # Classes don't have parent classes in this context
                    base_classes=base_classes,
                    usr=cursor.get_usr() if cursor.get_usr() else "",
                    # Template tracking (Template Search Support)
                    is_template=is_class_template_spec,  # True for explicit specializations
                    template_kind="full_specialization" if is_class_template_spec else None,
                    primary_template_usr=primary_usr,  # Task 3.4: Link to primary template
                    # Phase 1: Line ranges
                    start_line=loc_info["start_line"],
                    end_line=loc_info["end_line"],
                    header_file=loc_info["header_file"],
                    header_line=loc_info["header_line"],
                    header_start_line=loc_info["header_start_line"],
                    header_end_line=loc_info["header_end_line"],
                    # Phase 1: Definition-wins logic
                    is_definition=cursor.is_definition(),
                    # Phase 2: Documentation
                    brief=doc_info["brief"],
                    doc_comment=doc_info["doc_comment"],
                )

                # Collect symbol in thread-local buffer (no lock needed)
                symbols_buffer.append(info)

            # Always process children (even if we didn't extract this symbol)
            # Children might be in different files
            for child in cursor.get_children():
                self._process_cursor(
                    child,
                    should_extract_from_file,
                    cursor.spelling if should_extract else parent_class,
                    parent_function_usr,
                )
            return  # Don't process children again below

        # Process template functions
        # Issue #99: Template Class Search and Specialization Discovery
        elif kind == CursorKind.FUNCTION_TEMPLATE:
            if cursor.spelling and should_extract:
                # Get function signature
                signature = ""
                if cursor.type:
                    signature = cursor.type.spelling

                function_usr = cursor.get_usr() if cursor.get_usr() else ""

                # Extract qualified name and namespace
                qualified_name = self._get_qualified_name(cursor)
                namespace = self._extract_namespace(qualified_name)

                # Extract line range and location info
                loc_info = self._extract_line_range_info(cursor)

                # Extract documentation
                doc_info = self._extract_documentation(cursor)

                # Extract template parameters (Task 3.2)
                template_params = self._extract_template_parameters(cursor)

                # Phase 5: Extract virtual/const/static/access for template methods
                # Check if this is a method template (has parent_class)
                is_method_template = bool(parent_class)
                is_virtual = cursor.is_virtual_method() if is_method_template else False
                is_pure_virtual = cursor.is_pure_virtual_method() if is_method_template else False
                is_const = cursor.is_const_method() if is_method_template else False
                is_static = cursor.is_static_method()
                access_spec = cursor.access_specifier
                access = access_spec.name.lower() if access_spec else "public"
                if access in ("none", "invalid"):
                    access = "public"

                info = SymbolInfo(
                    name=cursor.spelling,
                    kind="function_template",
                    file=loc_info["file"],
                    line=loc_info["line"],
                    column=loc_info["column"],
                    qualified_name=qualified_name,
                    signature=signature,
                    is_project=(
                        self._is_project_file(loc_info["file"]) if loc_info["file"] else False
                    ),
                    namespace=namespace,
                    access=access,
                    parent_class=parent_class,  # Could be template method
                    usr=function_usr,
                    # Template functions are not specializations themselves
                    is_template_specialization=False,
                    # Template tracking (Template Search Support)
                    is_template=True,  # FUNCTION_TEMPLATE is a template
                    template_kind="function_template",
                    template_parameters=template_params,  # Task 3.2: JSON array of template params
                    # Line ranges
                    start_line=loc_info["start_line"],
                    end_line=loc_info["end_line"],
                    header_file=loc_info["header_file"],
                    header_line=loc_info["header_line"],
                    header_start_line=loc_info["header_start_line"],
                    header_end_line=loc_info["header_end_line"],
                    # Phase 5: Virtual/abstract indicators
                    is_virtual=is_virtual,
                    is_pure_virtual=is_pure_virtual,
                    is_const=is_const,
                    is_static=is_static,
                    # Definition-wins logic
                    is_definition=cursor.is_definition(),
                    # Documentation
                    brief=doc_info["brief"],
                    doc_comment=doc_info["doc_comment"],
                )

                # Collect symbol in thread-local buffer
                symbols_buffer.append(info)

            # Process children for function body
            for child in cursor.get_children():
                self._process_cursor(
                    child,
                    should_extract_from_file,
                    parent_class,
                    cursor.get_usr() if cursor.get_usr() else parent_function_usr,
                )
            return  # Don't process children again below

        # Process functions and methods (only if should extract)
        elif kind in (CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD):
            if cursor.spelling and should_extract:
                # Get function signature
                signature = ""
                if cursor.type:
                    signature = cursor.type.spelling

                function_usr = cursor.get_usr() if cursor.get_usr() else ""

                # Extract qualified name and namespace (Qualified Names Phase 1)
                qualified_name = self._get_qualified_name(cursor)
                namespace = self._extract_namespace(qualified_name)

                # Extract line range and location info (Phase 1: LLM Integration)
                loc_info = self._extract_line_range_info(cursor)

                # Extract documentation (Phase 2: LLM Integration)
                doc_info = self._extract_documentation(cursor)

                # Detect template specialization (Phase 3: Qualified Names)
                is_template_spec = self._detect_template_specialization(cursor)

                # Task 3.4: Get primary template USR for full specializations
                primary_usr = None
                if is_template_spec:
                    primary_usr = self._get_primary_template_usr(cursor)

                # Phase 5: Extract virtual/const/static/access for methods
                is_method = kind == CursorKind.CXX_METHOD
                is_virtual = cursor.is_virtual_method() if is_method else False
                is_pure_virtual = cursor.is_pure_virtual_method() if is_method else False
                is_const = cursor.is_const_method() if is_method else False
                is_static = cursor.is_static_method()
                # Access specifier: PUBLIC, PRIVATE, PROTECTED, NONE, INVALID
                access_spec = cursor.access_specifier
                access = access_spec.name.lower() if access_spec else "public"
                # Normalize: treat "none" and "invalid" as "public" for functions
                if access in ("none", "invalid"):
                    access = "public"

                info = SymbolInfo(
                    name=cursor.spelling,
                    kind="function" if kind == CursorKind.FUNCTION_DECL else "method",
                    file=loc_info["file"],
                    line=loc_info["line"],
                    column=loc_info["column"],
                    qualified_name=qualified_name,
                    signature=signature,
                    is_project=(
                        self._is_project_file(loc_info["file"]) if loc_info["file"] else False
                    ),
                    namespace=namespace,
                    access=access,
                    parent_class=parent_class if is_method else "",
                    usr=function_usr,
                    # Phase 3: Overload metadata
                    is_template_specialization=is_template_spec,
                    # Template tracking (Template Search Support)
                    is_template=is_template_spec,  # True for explicit function specializations
                    template_kind="full_specialization" if is_template_spec else None,
                    primary_template_usr=primary_usr,  # Task 3.4: Link to primary template
                    # Phase 1: Line ranges
                    start_line=loc_info["start_line"],
                    end_line=loc_info["end_line"],
                    header_file=loc_info["header_file"],
                    header_line=loc_info["header_line"],
                    header_start_line=loc_info["header_start_line"],
                    header_end_line=loc_info["header_end_line"],
                    # Phase 5: Virtual/abstract indicators
                    is_virtual=is_virtual,
                    is_pure_virtual=is_pure_virtual,
                    is_const=is_const,
                    is_static=is_static,
                    # Phase 1: Definition-wins logic
                    is_definition=cursor.is_definition(),
                    # Phase 2: Documentation
                    brief=doc_info["brief"],
                    doc_comment=doc_info["doc_comment"],
                )

                # Collect symbol in thread-local buffer (no lock needed)
                symbols_buffer.append(info)

            # Always process children (for call tracking and nested symbols)
            # Use function_usr only if we extracted this function
            current_function_usr = (
                cursor.get_usr() if (should_extract and cursor.get_usr()) else parent_function_usr
            )
            for child in cursor.get_children():
                self._process_cursor(
                    child, should_extract_from_file, parent_class, current_function_usr
                )
            return  # Don't process children again below

        # Process type aliases (Phase 1.3: Type Alias Tracking, Phase 2.0: Template Alias Tracking)
        elif kind in (
            CursorKind.TYPEDEF_DECL,
            CursorKind.TYPE_ALIAS_DECL,
            CursorKind.TYPE_ALIAS_TEMPLATE_DECL,
        ):
            if cursor.spelling and should_extract:
                try:
                    # Extract alias information
                    alias_info = self._extract_alias_info(cursor)

                    # Collect alias in thread-local buffer (no lock needed)
                    aliases_buffer.append(alias_info)

                    diagnostics.debug(
                        f"Extracted alias: {alias_info['alias_name']} -> {alias_info['canonical_type']} "
                        f"(kind: {alias_info['alias_kind']}, template: {alias_info['is_template_alias']}, "
                        f"file: {alias_info['file']}:{alias_info['line']})"
                    )
                except Exception as e:
                    # Alias extraction failures are not critical, just log and continue
                    diagnostics.warning(
                        f"Failed to extract alias info for {cursor.spelling} at "
                        f"{cursor.location.file.name if cursor.location.file else 'unknown'}:"
                        f"{cursor.location.line}: {e}"
                    )

            # For template aliases, don't process children (the nested TYPE_ALIAS_DECL is handled in _extract_alias_info)
            # For simple aliases, process children (nested declarations within namespace, etc.)
            if kind != CursorKind.TYPE_ALIAS_TEMPLATE_DECL:
                for child in cursor.get_children():
                    self._process_cursor(
                        child, should_extract_from_file, parent_class, parent_function_usr
                    )
            return  # Don't process children again below

        # Process function calls within function bodies
        elif kind == CursorKind.CALL_EXPR and parent_function_usr:
            # This is a function call inside a function
            referenced = cursor.referenced
            if referenced and referenced.get_usr():
                called_usr = referenced.get_usr()

                # BUG FIX (cplusplus_mcp-y6j): Template call tracking USR mismatch
                # For template function calls, cursor.referenced returns the instantiation USR
                # (e.g., someFunction<const char[6], int>), but function_index stores the
                # generic template USR (e.g., someFunction<T...>). This causes find_callers,
                # find_callees, get_call_sites, and get_call_path to fail for templates.
                #
                # Solution: Use clang_getSpecializedCursorTemplate to get the canonical
                # template USR when the referenced cursor is a template instantiation.
                # This ensures call sites are stored with the same USR as the template
                # definition, enabling successful lookups.
                from clang import cindex

                try:
                    template_cursor = cindex.conf.lib.clang_getSpecializedCursorTemplate(referenced)
                    if template_cursor and not template_cursor.kind.is_invalid():
                        template_usr = template_cursor.get_usr()
                        if template_usr:
                            # Use canonical template USR instead of instantiation USR
                            called_usr = template_usr
                except Exception:
                    # If not a template instantiation or API fails, use original USR
                    pass

                # Phase 3: Extract call site location information
                location = cursor.location
                call_file = location.file.name if location.file else None
                call_line = location.line if location.line else None
                call_column = location.column if location.column else None

                # Collect call relationship with location in thread-local buffer
                calls_buffer.append(
                    (parent_function_usr, called_usr, call_file, call_line, call_column)
                )

        # Recurse into children (always, to traverse entire AST)
        for child in cursor.get_children():
            self._process_cursor(child, should_extract_from_file, parent_class, parent_function_usr)

    def _index_translation_unit(self, tu, source_file: str) -> Dict[str, Any]:
        """
        Process translation unit, extracting symbols from source and project headers.

        Uses first-win strategy: headers are extracted only if not already processed.
        This method is the core of header extraction functionality.

        Args:
            tu: libclang TranslationUnit (contains AST for source + all includes)
            source_file: Path to the source file being analyzed

        Returns:
            Dictionary with:
                - processed: List of files we extracted symbols from
                - skipped: List of headers already processed by other sources

        Algorithm:
            1. Define should_extract_from_file(file_path) closure that:
               - Always returns True for source file
               - For headers: tries to claim via header_tracker
               - Uses _is_project_file() to filter non-project files
            2. Traverse TU.cursor with should_extract_from_file callback
            3. Mark claimed headers as completed
            4. Save header tracker state to disk

        Implements:
            REQ-10.1.1: Extract symbols from project headers included by source
            REQ-10.1.2: Leverage libclang's TU to access already-parsed headers
            REQ-10.1.4: Extract only from project headers
            REQ-10.1.5: Support nested includes
            REQ-10.2.1: First-win strategy
            REQ-10.2.2: Skip headers already processed
            REQ-10.5.4: Save tracker after analysis
        """
        processed_files = set()
        skipped_headers = set()
        headers_to_extract = set()

        def should_extract_from_file(file_path: str) -> bool:
            """
            Decide if we should extract symbols from this file.

            Returns True if:
            - file_path is the source file (always extract)
            - file_path is a project header and we won the claim (first-win)

            Returns False if:
            - file_path is not a project file (system header, external dep)
            - file_path is a header already processed by another source
            """
            # Always extract from source file
            if file_path == source_file:
                processed_files.add(file_path)
                return True

            # Check if already decided in this TU
            if file_path in headers_to_extract:
                return True
            if file_path in skipped_headers:
                return False

            # Check if it's a project file
            if not self._is_project_file(file_path):
                # Not a project file (system header or external dependency)
                skipped_headers.add(file_path)
                return False

            # It's a project header - try to claim it (first-win)
            try:
                file_hash = self._get_file_hash(file_path)
                if self.header_tracker.try_claim_header(file_path, file_hash):
                    # We won! Extract from this header
                    headers_to_extract.add(file_path)
                    processed_files.add(file_path)
                    return True
                else:
                    # Another source already processed/processing this header
                    skipped_headers.add(file_path)
                    return False
            except Exception as e:
                # On error, skip this header
                diagnostics.warning(f"Error checking header {file_path}: {e}")
                skipped_headers.add(file_path)
                return False

        # Initialize thread-local buffers for collecting symbols
        self._init_thread_local_buffers()

        # Traverse entire TU AST with our extraction filter
        self._process_cursor(tu.cursor, should_extract_from_file)

        # Bulk write all collected symbols to shared indexes (single lock acquisition)
        self._bulk_write_symbols()

        # Mark newly processed headers as completed
        for header in headers_to_extract:
            try:
                file_hash = self._get_file_hash(header)
                self.header_tracker.mark_completed(header, file_hash)
            except Exception as e:
                diagnostics.warning(f"Error marking header {header} as completed: {e}")

        # Note: Header tracking is saved once at the end of indexing to avoid
        # race conditions in multi-process mode. See index_project() and refresh_if_needed()

        # Extract and store include dependencies for incremental analysis
        if self.dependency_graph is not None:
            try:
                includes = self.dependency_graph.extract_includes_from_tu(tu, source_file)
                self.dependency_graph.update_dependencies(source_file, includes)
            except Exception as e:
                diagnostics.warning(f"Failed to update dependencies for {source_file}: {e}")

        return {
            "source_file": source_file,
            "processed": list(processed_files),
            "skipped": list(skipped_headers),
        }

    def index_file(self, file_path: str, force: bool = False) -> tuple[bool, bool]:
        """Index a single C++ file

        Returns:
            (success, was_cached) - success indicates if indexing succeeded,
                                   was_cached indicates if it was loaded from cache
        """
        file_path = os.path.abspath(file_path)

        # Check if source file exists before attempting to parse
        # This prevents expensive libclang parse attempts on non-existent files
        if not Path(file_path).exists():
            error_msg = f"Source file does not exist: {file_path}"
            diagnostics.error(error_msg)

            # Log to centralized error log for diagnostics
            file_not_found_error = FileNotFoundError(error_msg)
            self.cache_manager.log_parse_error(file_path, file_not_found_error, "", None, 0)

            return (False, False)

        current_hash = self._get_file_hash(file_path)

        # Get compilation arguments to compute hash (needed for cache validation)
        # Task 3.2: Use precomputed args if provided (worker mode), otherwise query CompileCommandsManager
        file_path_obj = Path(file_path)
        if self._provided_compile_args is not None:
            # Worker mode: use compile args provided by main process
            args = self._provided_compile_args
        else:
            # Main process mode: query CompileCommandsManager
            args = self.compile_commands_manager.get_compile_args_with_fallback(file_path_obj)

            # If compile commands are not available and we're using fallback, add vcpkg includes
            if not self.compile_commands_manager.is_file_supported(file_path_obj):
                # Add vcpkg includes if available
                vcpkg_include = self.project_root / "vcpkg_installed" / "x64-windows" / "include"
                if vcpkg_include.exists():
                    args.append(f"-I{vcpkg_include}")

                # Add common vcpkg paths
                vcpkg_paths = [
                    "C:/vcpkg/installed/x64-windows/include",
                    "C:/dev/vcpkg/installed/x64-windows/include",
                ]
                for path in vcpkg_paths:
                    if Path(path).exists():
                        args.append(f"-I{path}")
                        break

        # Compute hash of compilation arguments for cache validation
        compile_args_hash = self._compute_compile_args_hash(args)

        # Try to load from per-file cache first
        if not force:
            cache_data = self._load_file_cache(file_path, current_hash, compile_args_hash)
            if cache_data is not None:
                # Check if this file previously failed and if we should retry
                if not cache_data["success"]:
                    retry_count = cache_data["retry_count"]
                    if retry_count >= self.max_parse_retries:
                        # File has failed too many times, skip it
                        diagnostics.debug(
                            f"Skipping {file_path} - failed {retry_count} times "
                            f"(last error: {cache_data['error_message']})"
                        )
                        return (False, True)  # Failed, but from cache (skip retry)
                    else:
                        # Retry the file
                        diagnostics.debug(
                            f"Retrying {file_path} (attempt {retry_count + 1}/{self.max_parse_retries + 1}, "
                            f"last error: {cache_data['error_message']})"
                        )
                        # Continue to parsing below (will increment retry_count on failure)
                else:
                    # Successfully cached - load symbols
                    cached_symbols = cache_data["symbols"]

                    # Prepare index updates outside the lock to minimize lock duration
                    # Build updates for class_index and function_index
                    class_updates = defaultdict(list)
                    function_updates = defaultdict(list)
                    usr_updates = {}

                    for symbol in cached_symbols:
                        if symbol.kind in ("class", "struct"):
                            class_updates[symbol.name].append(symbol)
                        else:
                            function_updates[symbol.name].append(symbol)

                        if symbol.usr:
                            usr_updates[symbol.usr] = symbol

                        # v9.0: calls/called_by removed from SymbolInfo
                        # Call graph is now loaded lazily from call_sites table

                    # Apply all updates with a single lock acquisition
                    # Use conditional lock (no-op in ProcessPoolExecutor worker processes)
                    with self._get_lock():
                        # Clear old entries for this file
                        if file_path in self.file_index:
                            for info in self.file_index[file_path]:
                                if info.kind in ("class", "struct"):
                                    self.class_index[info.name] = [
                                        i
                                        for i in self.class_index[info.name]
                                        if i.file != file_path
                                    ]
                                else:
                                    self.function_index[info.name] = [
                                        i
                                        for i in self.function_index[info.name]
                                        if i.file != file_path
                                    ]

                        # Add cached symbols
                        self.file_index[file_path] = cached_symbols

                        # Apply class updates
                        for name, symbols in class_updates.items():
                            self.class_index[name].extend(symbols)

                        # Apply function updates
                        for name, symbols in function_updates.items():
                            self.function_index[name].extend(symbols)

                        # Apply USR updates
                        self.usr_index.update(usr_updates)

                        # v9.0: call graph restored lazily from call_sites table

                        self.file_hashes[file_path] = current_hash

                    return (True, True)  # Successfully loaded from cache

        # Determine retry count for this attempt
        retry_count = 0
        if not force:
            cache_data = self._load_file_cache(file_path, current_hash, compile_args_hash)
            if cache_data is not None and not cache_data["success"]:
                retry_count = cache_data["retry_count"] + 1  # Increment for this retry

        try:
            # Create translation unit with detailed diagnostics
            # Note: We no longer skip function bodies to enable call graph analysis
            index = self._get_thread_index()

            # Try parsing with progressive fallback if initial attempt fails
            tu = None
            parse_options_attempts = [
                # Attempt 1: Full detailed processing (best for analysis)
                (
                    TranslationUnit.PARSE_INCOMPLETE
                    | TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
                    "full detailed processing",
                ),
                # Attempt 2: Just incomplete (more compatible)
                (TranslationUnit.PARSE_INCOMPLETE, "incomplete parsing"),
                # Attempt 3: Minimal options (maximum compatibility)
                (0, "minimal options"),
            ]

            last_error = None
            for options, description in parse_options_attempts:
                try:
                    tu = index.parse(file_path, args=args, options=options)
                    if tu:
                        if description != "full detailed processing":
                            diagnostics.debug(f"{file_path}: parsed with {description}")
                        break
                except TranslationUnitLoadError as e:
                    last_error = e
                    continue

            if not tu:
                # All parse attempts failed
                if last_error:
                    error_msg = f"TranslationUnitLoadError: {last_error}"
                else:
                    error_msg = "Failed to create translation unit (libclang returned None)"

                # Provide helpful diagnostic information
                diagnostics.error(f"Failed to parse {file_path}")
                diagnostics.error(f"  Error: {error_msg}")
                diagnostics.error(f"  Compilation args ({len(args)} total):")
                # Log first 10 args to avoid overwhelming output
                for i, arg in enumerate(args[:10]):
                    diagnostics.error(f"    [{i}] {arg}")
                if len(args) > 10:
                    diagnostics.error(f"    ... and {len(args) - 10} more args")

                # Check for common issues
                hints = []
                if any("-std=c++" in arg for arg in args):
                    std_args = [arg for arg in args if "-std=c++" in arg]
                    hints.append(f"C++ standard specified: {std_args}")
                # Task 3.2: Check CompileCommandsManager only if initialized
                if self.compile_commands_manager is not None:
                    if not self.compile_commands_manager.clang_resource_dir:
                        hints.append(
                            "Clang resource directory not detected - system headers may be missing"
                        )
                    if self.compile_commands_manager.is_file_supported(Path(file_path)):
                        hints.append(
                            "Using args from compile_commands.json - check if they are libclang-compatible"
                        )
                    else:
                        hints.append(
                            "Using fallback compilation args - compile_commands.json may be needed"
                        )
                else:
                    hints.append("Using precomputed compile args from main process")

                if hints:
                    diagnostics.error("  Possible issues:")
                    for hint in hints:
                        diagnostics.error(f"    - {hint}")

                # Log to centralized error log
                full_error_msg = f"{error_msg}\nArgs: {args}"
                parse_error = Exception(full_error_msg)
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
                return (False, False)

            # Extract and check libclang diagnostics for errors
            error_diagnostics, warning_diagnostics = self._extract_diagnostics(tu)

            # Track if there were errors (for logging and cache metadata)
            has_errors = bool(error_diagnostics)
            cache_error_msg = None

            # Log errors but continue processing (libclang provides usable partial AST)
            if error_diagnostics:
                # Format error messages from libclang diagnostics
                formatted_errors = self._format_diagnostics(error_diagnostics, max_count=5)
                full_error_msg = (
                    f"libclang parsing errors ({len(error_diagnostics)} total):\n{formatted_errors}"
                )

                # Truncate for cache
                cache_error_msg = full_error_msg[:200]

                # Log to centralized error log with full message
                parse_error = Exception(full_error_msg)
                self.cache_manager.log_parse_error(
                    file_path, parse_error, current_hash, compile_args_hash, retry_count
                )

                # Log as warning but continue processing
                # libclang provides a usable partial AST even with errors
                diagnostics.warning(
                    f"{file_path}: Continuing despite {len(error_diagnostics)} error(s):\n{cache_error_msg}"
                )

            # Log warnings at debug level but continue processing
            if warning_diagnostics:
                formatted_warnings = self._format_diagnostics(warning_diagnostics, max_count=3)
                diagnostics.debug(
                    f"{file_path}: {len(warning_diagnostics)} warning(s):\n{formatted_warnings}"
                )

            # Clear old entries for this file before re-parsing
            # This must be atomic to ensure index consistency
            # Use conditional lock (no-op in ProcessPoolExecutor worker processes)
            with self._get_lock():
                if file_path in self.file_index:
                    # Remove old entries from class and function indexes
                    for info in self.file_index[file_path]:
                        # Issue #99: Include template kinds in class_index
                        if info.kind in (
                            "class",
                            "struct",
                            "class_template",
                            "partial_specialization",
                        ):
                            self.class_index[info.name] = [
                                i for i in self.class_index[info.name] if i.file != file_path
                            ]
                        else:
                            self.function_index[info.name] = [
                                i for i in self.function_index[info.name] if i.file != file_path
                            ]

                    self.file_index[file_path].clear()

            # Collect symbols for this file
            collected_symbols = []

            # Process the translation unit with header extraction (modifies indexes)
            extraction_result = self._index_translation_unit(tu, file_path)

            # Log header extraction results
            processed_count = len(extraction_result["processed"])
            skipped_count = len(extraction_result["skipped"])
            if processed_count > 1:  # More than just the source file
                header_count = processed_count - 1
                diagnostics.debug(
                    f"{file_path}: processed {processed_count} files "
                    f"({header_count} headers extracted, {skipped_count} headers skipped)"
                )

            # Get the symbols we just added for this file (quick copy under lock)
            # Use conditional lock (no-op in ProcessPoolExecutor worker processes)
            with self._get_lock():
                if file_path in self.file_index:
                    collected_symbols = self.file_index[file_path].copy()
                else:
                    collected_symbols = []

            # v9.0: calls/called_by fields removed from SymbolInfo
            # Call graph data is stored in call_sites table and queried on-demand
            # No need to populate symbol.calls/called_by here anymore

            # Save to per-file cache (mark as successfully parsed, even if there were errors)
            # Note: success=True means we got a usable TU and extracted symbols
            # error_message will be set if there were parsing errors (partial parse)
            self._save_file_cache(
                file_path,
                collected_symbols,
                current_hash,
                compile_args_hash,
                success=True,
                error_message=cache_error_msg,
                retry_count=0,
            )

            # Update tracking
            # Use conditional lock (no-op in ProcessPoolExecutor worker processes)
            with self._get_lock():
                # CRITICAL: Don't store TranslationUnits at all - they're never used!
                # self.translation_units is a write-only dict that causes massive FD leak
                # TUs hold system headers open (516+ .h files from /usr/include/c++/14/)
                # We only need symbols extracted from TU, not the TU itself
                # Explicitly delete to release file descriptors immediately
                del tu
                gc.collect()
                self.file_hashes[file_path] = current_hash

            return (True, False)  # Success, not from cache

        except Exception as e:
            # Log full error details to centralized error log for developer analysis
            self.cache_manager.log_parse_error(
                file_path, e, current_hash, compile_args_hash, retry_count
            )

            # Save failure information to cache (with truncated error message)
            error_msg = str(e)[:200]  # Limit error message length for cache

            # Save failure to cache so we don't keep retrying indefinitely
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
            return (False, False)  # Failed, not from cache

    def index_project(
        self,
        force: bool = False,
        include_dependencies: bool = True,
        progress_callback: Optional[Callable] = None,
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

        # Store the include_dependencies setting BEFORE loading cache
        self.include_dependencies = include_dependencies

        # Try to load from cache if not forcing
        if not force and self._load_cache():
            refreshed = self.refresh_if_needed()
            if refreshed > 0:
                diagnostics.debug(f"Using cached index (updated {refreshed} files)")
            else:
                diagnostics.debug("Using cached index")
            return self.indexed_file_count

        diagnostics.debug(f"Finding C++ files (include_dependencies={include_dependencies})...")
        files = self._find_cpp_files(include_dependencies=include_dependencies)

        if not files:
            diagnostics.warning("No C++ files found in project")
            return 0

        diagnostics.debug(f"Found {len(files)} C++ files to index")

        # Show detailed progress
        indexed_count = 0
        cache_hits = 0
        failed_count = 0
        last_report_time = time.time()

        # Check if stderr is a terminal (for proper progress display)
        # In MCP context or when output is redirected, use less frequent reporting
        # Check multiple conditions to detect non-interactive environments
        is_terminal = (
            hasattr(sys.stderr, "isatty")
            and sys.stderr.isatty()
            and not os.environ.get("MCP_SESSION_ID")
            and not os.environ.get("CLAUDE_CODE_SESSION")
        )

        # No special test mode needed - we'll handle Windows console properly

        # CRITICAL: Ensure schema is current BEFORE creating workers
        # This prevents race conditions where multiple workers detect schema mismatch
        # and try to recreate the database simultaneously (causing "disk I/O error")
        if self.use_processes:
            self.cache_manager.ensure_schema_current()

        # Choose executor based on configuration
        # ProcessPoolExecutor bypasses Python's GIL for true parallelism
        executor_class = ProcessPoolExecutor if self.use_processes else ThreadPoolExecutor

        if self.use_processes:
            diagnostics.debug(
                f"Using ProcessPoolExecutor with {self.max_workers} workers (GIL bypass)"
            )
        else:
            diagnostics.debug(f"Using ThreadPoolExecutor with {self.max_workers} workers")

        executor = None
        try:
            executor = executor_class(max_workers=self.max_workers)

            if self.use_processes:
                # ProcessPoolExecutor: use worker function that returns symbols
                # Pass config_file to ensure workers use the same cache directory
                config_file_str = (
                    str(self.project_identity.config_file_path)
                    if self.project_identity.config_file_path
                    else None
                )

                # Task 3.2: Prepare compile args for each file in main process
                # This avoids loading CompileCommandsManager in each worker (~6-10 GB memory savings)
                file_compile_args = {}
                for file_path in files:
                    file_path_obj = Path(file_path)
                    args = self.compile_commands_manager.get_compile_args_with_fallback(
                        file_path_obj
                    )

                    # If compile commands are not available and we're using fallback, add vcpkg includes
                    if not self.compile_commands_manager.is_file_supported(file_path_obj):
                        # Add vcpkg includes if available
                        vcpkg_include = (
                            self.project_root / "vcpkg_installed" / "x64-windows" / "include"
                        )
                        if vcpkg_include.exists():
                            args.append(f"-I{vcpkg_include}")

                        # Add common vcpkg paths
                        vcpkg_paths = [
                            "C:/vcpkg/installed/x64-windows/include",
                            "C:/dev/vcpkg/installed/x64-windows/include",
                        ]
                        for path in vcpkg_paths:
                            if Path(path).exists():
                                args.append(f"-I{path}")
                                break

                    file_compile_args[file_path] = args

                future_to_file = {
                    executor.submit(
                        _process_file_worker,
                        (
                            str(self.project_root),
                            config_file_str,
                            os.path.abspath(file_path),
                            force,
                            include_dependencies,
                            file_compile_args[file_path],  # Task 3.2: Pass precomputed compile args
                        ),
                    ): os.path.abspath(file_path)
                    for file_path in files
                }
            else:
                # ThreadPoolExecutor: use index_file method directly
                future_to_file = {
                    executor.submit(
                        self.index_file, os.path.abspath(file_path), force
                    ): os.path.abspath(file_path)
                    for file_path in files
                }

            for i, future in enumerate(as_completed(future_to_file)):
                file_path = future_to_file[future]
                try:
                    result = future.result()

                    if self.use_processes:
                        # ProcessPoolExecutor returns (file_path, success, was_cached, symbols, call_sites, processed_headers)
                        _, success, was_cached, symbols, call_sites, processed_headers = result

                        # Merge symbols into main process indexes
                        if success and symbols:
                            with self.index_lock:
                                for symbol in symbols:
                                    # CRITICAL FIX FOR ISSUE #8: Apply same deduplication logic as _bulk_write_symbols
                                    # Check for duplicates before adding
                                    skip_symbol = False

                                    if symbol.usr and symbol.usr in self.usr_index:
                                        existing = self.usr_index[symbol.usr]

                                        # Definition-wins: if new is definition and existing is not, replace
                                        if symbol.is_definition and not existing.is_definition:
                                            # Remove old declaration from class/function index
                                            # Issue #99: Include template kinds in class_index
                                            if existing.kind in (
                                                "class",
                                                "struct",
                                                "class_template",
                                                "partial_specialization",
                                            ):
                                                if existing.name in self.class_index:
                                                    try:
                                                        self.class_index[existing.name].remove(
                                                            existing
                                                        )
                                                        if not self.class_index[existing.name]:
                                                            del self.class_index[existing.name]
                                                    except ValueError:
                                                        pass
                                            else:
                                                if existing.name in self.function_index:
                                                    try:
                                                        self.function_index[existing.name].remove(
                                                            existing
                                                        )
                                                        if not self.function_index[existing.name]:
                                                            del self.function_index[existing.name]
                                                    except ValueError:
                                                        pass
                                            # Will add new definition below (fall through)
                                        else:
                                            # Keep existing (both declarations or existing is already definition)
                                            skip_symbol = True

                                    if not skip_symbol:
                                        # Add to appropriate index
                                        # Issue #99: Include template kinds in class_index
                                        if symbol.kind in (
                                            "class",
                                            "struct",
                                            "class_template",
                                            "partial_specialization",
                                        ):
                                            self.class_index[symbol.name].append(symbol)
                                        else:
                                            self.function_index[symbol.name].append(symbol)

                                        # Add to USR index
                                        if symbol.usr:
                                            self.usr_index[symbol.usr] = symbol

                                        # Add to file index (with deduplication)
                                        if symbol.file:
                                            if symbol.file not in self.file_index:
                                                self.file_index[symbol.file] = []

                                            # Check for duplicates in file_index
                                            already_in_file_index = False
                                            if symbol.usr:
                                                for existing in self.file_index[symbol.file]:
                                                    if existing.usr == symbol.usr:
                                                        already_in_file_index = True
                                                        break

                                            if not already_in_file_index:
                                                self.file_index[symbol.file].append(symbol)

                                    # v9.0: calls/called_by removed from SymbolInfo
                                    # Call graph is restored from call_sites below

                                # Phase 4: Stream call sites directly to SQLite
                                # This avoids accumulating ~1.9 GB in memory for large projects
                                if call_sites:
                                    diagnostics.debug(
                                        f"Streaming {len(call_sites)} call sites from {file_path} to SQLite"
                                    )
                                    # Delete existing call sites for this file (re-indexing case)
                                    if self.cache_manager and self.cache_manager.backend:
                                        self.cache_manager.backend.delete_call_sites_by_file(
                                            file_path
                                        )
                                        # Save call sites directly to SQLite
                                        self.cache_manager.backend.save_call_sites_batch(call_sites)

                                    # Update in-memory call graph (for current session queries)
                                    # but DON'T store CallSite objects in memory
                                    for cs_dict in call_sites:
                                        self.call_graph_analyzer.add_call(
                                            cs_dict["caller_usr"],
                                            cs_dict["callee_usr"],
                                            cs_dict["file"],
                                            cs_dict["line"],
                                            cs_dict.get("column"),
                                            store_call_site=False,  # Phase 4: Don't accumulate in memory
                                        )

                                # Merge header tracking from worker (critical for incremental analysis)
                                # Workers claim headers during parsing, we need to merge that state
                                # back into the main process's header_tracker
                                if processed_headers:
                                    for header_path, header_hash in processed_headers.items():
                                        # Use mark_completed to update main process tracker
                                        # This is safe because workers already claimed these headers
                                        self.header_tracker.mark_completed(header_path, header_hash)
                                    diagnostics.debug(
                                        f"Merged {len(processed_headers)} header tracking entries from {file_path}"
                                    )

                                # Update file hash tracking
                                file_hash = self._get_file_hash(file_path)
                                self.file_hashes[file_path] = file_hash
                    else:
                        # ThreadPoolExecutor returns (success, was_cached)
                        success, was_cached = result

                except Exception as exc:
                    diagnostics.error(f"Error indexing {file_path}: {exc}")
                    success, was_cached = False, False

                if success:
                    indexed_count += 1
                    if was_cached:
                        cache_hits += 1
                else:
                    failed_count += 1

                processed = i + 1

                # Progress reporting
                current_time = time.time()

                if is_terminal:
                    should_report = (
                        (processed <= 5)
                        or (processed % 5 == 0)
                        or ((current_time - last_report_time) > 2.0)
                        or (processed == len(files))
                    )
                else:
                    should_report = (
                        (processed % 50 == 0)
                        or ((current_time - last_report_time) > 5.0)
                        or (processed == len(files))
                    )

                if should_report:
                    elapsed = current_time - start_time
                    rate = processed / elapsed if elapsed > 0 else 0
                    eta = (len(files) - processed) / rate if rate > 0 else 0

                    cache_rate = (cache_hits * 100 // processed) if processed > 0 else 0

                    if is_terminal:
                        progress_str = (
                            f"Progress: {processed}/{len(files)} files ({100 * processed // len(files)}%) - "
                            f"Success: {indexed_count} - Failed: {failed_count} - "
                            f"Cache: {cache_hits} ({cache_rate}%) - {rate:.1f} files/sec - ETA: {eta:.0f}s"
                        )
                        print(f"\033[2K\r{progress_str}", end="", file=sys.stderr, flush=True)
                    else:
                        print(
                            f"Progress: {processed}/{len(files)} files ({100 * processed // len(files)}%) - "
                            f"Success: {indexed_count} - Failed: {failed_count} - "
                            f"Cache: {cache_hits} ({cache_rate}%) - {rate:.1f} files/sec - ETA: {eta:.0f}s",
                            file=sys.stderr,
                            flush=True,
                        )

                    # Call progress callback if provided
                    if progress_callback:
                        try:
                            # Import IndexingProgress here to avoid circular dependency
                            from .state_manager import IndexingProgress

                            estimated_completion = (
                                datetime.now() + timedelta(seconds=eta) if eta > 0 else None
                            )

                            progress = IndexingProgress(
                                total_files=len(files),
                                indexed_files=indexed_count,
                                failed_files=failed_count,
                                cache_hits=cache_hits,
                                current_file=file_path if processed < len(files) else None,
                                start_time=datetime.fromtimestamp(start_time),
                                estimated_completion=estimated_completion,
                            )

                            progress_callback(progress)
                        except Exception as e:
                            # Don't fail indexing if progress callback fails
                            diagnostics.debug(f"Progress callback failed: {e}")

                    last_report_time = current_time

        except KeyboardInterrupt:
            # Gracefully handle Ctrl-C: shutdown executor and clean up
            diagnostics.info("\nIndexing interrupted by user (Ctrl-C)")
            if executor is not None:
                # Cancel all pending futures
                for future in future_to_file:
                    future.cancel()

                # CRITICAL FIX FOR ISSUE #16: Shutdown with timeout to prevent hang
                # Previous bug: executor.shutdown(wait=True) blocked indefinitely
                # if workers were stuck in libclang parsing or I/O operations
                diagnostics.info(
                    f"Cancelling pending work and stopping {self.max_workers} workers..."
                )

                # First, try graceful shutdown with cancel_futures=True
                # This cancels any pending work that hasn't started yet
                executor.shutdown(wait=False, cancel_futures=True)

                # Now wait for running workers with timeout (5 seconds)
                # Workers may be processing files and need time to finish current operation
                import threading

                shutdown_complete = threading.Event()

                def wait_for_shutdown():
                    # Wait for all worker processes to exit
                    # This happens in background thread so we can timeout
                    try:
                        executor.shutdown(wait=True)
                        shutdown_complete.set()
                    except Exception:
                        pass  # Ignore errors during shutdown

                shutdown_thread = threading.Thread(target=wait_for_shutdown, daemon=True)
                shutdown_thread.start()

                # Wait up to 5 seconds for workers to finish
                if shutdown_complete.wait(timeout=5.0):
                    diagnostics.info("All workers stopped cleanly")
                else:
                    diagnostics.warning(
                        "Workers did not exit within 5 seconds - forcefully terminating"
                    )
                    # Force terminate worker processes if they don't exit gracefully
                    # This is safe because we've cancelled pending futures
                    # and workers are isolated processes
                    if hasattr(executor, "_processes") and executor._processes:
                        import signal

                        for pid, process in executor._processes.items():
                            try:
                                if process.is_alive():
                                    diagnostics.warning(f"Forcefully terminating worker {pid}")
                                    process.terminate()  # SIGTERM first
                            except Exception:
                                pass  # Ignore errors during force terminate

                    # Give terminated processes a moment to die
                    time.sleep(0.5)

                    # SIGKILL any that are still alive
                    if hasattr(executor, "_processes") and executor._processes:
                        for pid, process in executor._processes.items():
                            try:
                                if process.is_alive():
                                    diagnostics.warning(f"Killing worker {pid} with SIGKILL")
                                    process.kill()  # SIGKILL as last resort
                            except Exception:
                                pass

                    diagnostics.info("Worker processes terminated")

            raise
        finally:
            # Always ensure executor is properly shut down
            if executor is not None:
                # This will be called even after normal completion or exception
                # shutdown() is idempotent, so safe to call multiple times
                # Use wait=False to avoid blocking on cleanup
                try:
                    executor.shutdown(wait=False, cancel_futures=False)
                except Exception:
                    pass  # Ignore errors during final cleanup

        self.indexed_file_count = indexed_count
        self.last_index_time = time.time() - start_time

        with self.index_lock:
            # Count total symbols (not just unique names)
            class_count = sum(len(infos) for infos in self.class_index.values())
            function_count = sum(len(infos) for infos in self.function_index.values())

        # Print newline after progress to move to next line (only if using terminal progress)
        if is_terminal:
            print("", file=sys.stderr)
        diagnostics.info(f"Indexing complete in {self.last_index_time:.2f}s")
        diagnostics.info(
            f"Indexed {indexed_count}/{len(files)} files successfully ({cache_hits} from cache, {failed_count} failed)"
        )
        diagnostics.info(f"Found {class_count} classes, {function_count} functions")

        if failed_count > 0:
            diagnostics.info(
                f"Note: {failed_count} files failed to parse - this is normal for complex projects"
            )

        # Save overall cache and progress summary
        self._save_cache()
        self._save_progress_summary(indexed_count, len(files), cache_hits, failed_count)

        # Save header tracking state (once at end to avoid race conditions in multi-process mode)
        self._save_header_tracking()

        return indexed_count

    def _save_cache(self):
        """Save index to cache file"""
        # Get current config file info
        config_path = self.config.config_path
        config_mtime = config_path.stat().st_mtime if config_path and config_path.exists() else None

        # Get current compile_commands.json info
        # Task 3.2: Skip if CompileCommandsManager not initialized (worker mode)
        if self.compile_commands_manager is not None:
            cc_path = self.project_root / self.compile_commands_manager.compile_commands_path
            cc_mtime = cc_path.stat().st_mtime if cc_path.exists() else None
        else:
            cc_path = None
            cc_mtime = None

        self.cache_manager.save_cache(
            self.class_index,
            self.function_index,
            self.file_hashes,
            self.indexed_file_count,
            self.include_dependencies,
            config_file_path=config_path,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_path if cc_path.exists() else None,
            compile_commands_mtime=cc_mtime,
        )

        # Phase 3/4: Save call sites to database
        # In ProcessPoolExecutor mode (default): call_sites are already streamed to SQLite
        # as they arrive from workers (Phase 4 optimization), so this set is empty.
        # In ThreadPoolExecutor mode: call_sites are accumulated in memory, so we need
        # to save them here. This is still needed for backwards compatibility.
        call_sites = self.call_graph_analyzer.get_all_call_sites()
        if call_sites:
            diagnostics.debug(
                f"Saving {len(call_sites)} call sites to database (ThreadPoolExecutor mode)"
            )
            saved_count = self.cache_manager.backend.save_call_sites_batch(call_sites)
            if saved_count != len(call_sites):
                diagnostics.warning(f"Only saved {saved_count}/{len(call_sites)} call sites")

    def _load_cache(self) -> bool:
        """Load index from cache file"""
        # Get current config file info
        config_path = self.config.config_path
        config_mtime = config_path.stat().st_mtime if config_path and config_path.exists() else None

        # Get current compile_commands.json info
        # Task 3.2: Skip if CompileCommandsManager not initialized (worker mode)
        if self.compile_commands_manager is not None:
            cc_path = self.project_root / self.compile_commands_manager.compile_commands_path
            cc_mtime = cc_path.stat().st_mtime if cc_path.exists() else None
        else:
            cc_path = None
            cc_mtime = None

        cache_data = self.cache_manager.load_cache(
            self.include_dependencies,
            config_file_path=config_path,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_path if cc_path.exists() else None,
            compile_commands_mtime=cc_mtime,
        )
        if not cache_data:
            self.cache_loaded = False
            return False

        try:
            # Load indexes - Memory optimization: SymbolInfo objects come directly
            # from SQLite backend (no dict conversion needed, saves ~500 MB peak)
            self.class_index.clear()
            for name, infos in cache_data.get("class_index", {}).items():
                # infos are already SymbolInfo objects from SQLite backend
                self.class_index[name] = infos

            self.function_index.clear()
            for name, infos in cache_data.get("function_index", {}).items():
                # infos are already SymbolInfo objects from SQLite backend
                self.function_index[name] = infos

            # Rebuild file index mapping from loaded symbols
            self.file_index.clear()
            for infos in self.class_index.values():
                for symbol in infos:
                    if symbol.file:
                        self.file_index[symbol.file].append(symbol)
            for infos in self.function_index.values():
                for symbol in infos:
                    if symbol.file:
                        self.file_index[symbol.file].append(symbol)

            self.file_hashes = cache_data.get("file_hashes", {})
            self.indexed_file_count = cache_data.get("indexed_file_count", 0)

            # Rebuild USR index and call graphs from loaded data
            self.usr_index.clear()
            self.call_graph_analyzer.clear()

            # Rebuild from all loaded symbols
            all_symbols = []
            for class_list in self.class_index.values():
                for symbol in class_list:
                    if symbol.usr:
                        self.usr_index[symbol.usr] = symbol
                        all_symbols.append(symbol)

            for func_list in self.function_index.values():
                for symbol in func_list:
                    if symbol.usr:
                        self.usr_index[symbol.usr] = symbol
                        all_symbols.append(symbol)

            # Rebuild call graph from all symbols
            self.call_graph_analyzer.rebuild_from_symbols(all_symbols)

            # Memory optimization: call sites are now loaded LAZILY on-demand
            # instead of loading all at startup (saves ~150-200 MB for large projects)
            # The call_graph_analyzer.cache_backend handles lazy loading via SQLite queries

            diagnostics.debug(
                f"Loaded cache with {len(self.class_index)} classes, {len(self.function_index)} functions"
            )
            self.cache_loaded = True
            return True

        except Exception as e:
            diagnostics.error(f"Error loading cache: {e}")
            self.cache_loaded = False
            return False

    def _save_progress_summary(
        self, indexed_count: int, total_files: int, cache_hits: int, failed_count: int = 0
    ):
        """Save a summary of indexing progress"""
        status = "complete" if indexed_count + failed_count == total_files else "interrupted"
        # Count total symbols (not just unique names)
        class_count = sum(len(infos) for infos in self.class_index.values())
        function_count = sum(len(infos) for infos in self.function_index.values())

        self.cache_manager.save_progress(
            total_files,
            indexed_count,
            failed_count,
            cache_hits,
            self.last_index_time,
            class_count,
            function_count,
            status,
        )

    def search_classes(
        self,
        pattern: str,
        project_only: bool = True,
        file_name: Optional[str] = None,
        namespace: Optional[str] = None,
        max_results: Optional[int] = None,
    ):
        """Search for classes matching pattern"""
        try:
            return self.search_engine.search_classes(
                pattern, project_only, file_name, namespace, max_results
            )
        except re.error as e:
            diagnostics.error(f"Invalid regex pattern: {e}")
            return []

    def search_functions(
        self,
        pattern: str,
        project_only: bool = True,
        class_name: Optional[str] = None,
        file_name: Optional[str] = None,
        namespace: Optional[str] = None,
        max_results: Optional[int] = None,
    ):
        """Search for functions matching pattern, optionally within a specific class"""
        try:
            return self.search_engine.search_functions(
                pattern, project_only, class_name, file_name, namespace, max_results
            )
        except re.error as e:
            diagnostics.error(f"Invalid regex pattern: {e}")
            return []

    def get_stats(self) -> Dict[str, int]:
        """Get indexer statistics"""
        with self.index_lock:
            # Count total symbols (not just unique names)
            class_count = sum(len(infos) for infos in self.class_index.values())
            function_count = sum(len(infos) for infos in self.function_index.values())

            stats = {
                "class_count": class_count,
                "function_count": function_count,
                "file_count": self.indexed_file_count,
            }

            # Add compile commands statistics if enabled
            # Task 3.2: Skip if CompileCommandsManager not initialized (worker mode)
            if self.compile_commands_manager is not None and self.compile_commands_manager.enabled:
                compile_stats = self.compile_commands_manager.get_stats()
                stats.update(
                    {
                        "compile_commands_enabled": compile_stats["enabled"],
                        "compile_commands_count": compile_stats["compile_commands_count"],
                        "compile_commands_file_mapping_count": compile_stats["file_mapping_count"],
                    }
                )

            return stats

    def get_compile_commands_stats(self) -> Dict[str, Any]:
        """Get compile commands statistics"""
        # Task 3.2: Skip if CompileCommandsManager not initialized (worker mode)
        if self.compile_commands_manager is None or not self.compile_commands_manager.enabled:
            return {"enabled": False}

        return self.compile_commands_manager.get_stats()

    def refresh_if_needed(self, progress_callback: Optional[Callable] = None) -> int:
        """
        Refresh index for changed files and remove deleted files

        Args:
            progress_callback: Optional callback for progress updates.
                             Called with IndexingProgress object during refresh.

        Returns:
            Number of files refreshed
        """
        refreshed = 0
        deleted = 0
        start_time = time.time()

        # Refresh compile commands if needed
        # Task 3.2: Skip if CompileCommandsManager not initialized (worker mode)
        if self.compile_commands_manager is not None and self.compile_commands_manager.enabled:
            compile_commands_refreshed = self.compile_commands_manager.refresh_if_needed()
            if compile_commands_refreshed:
                diagnostics.debug("Compile commands refreshed")

        # Get currently existing files
        current_files = set(self._find_cpp_files(self.include_dependencies))
        tracked_files = set(self.file_hashes.keys())

        # Find deleted files
        # CRITICAL FIX FOR ISSUE #8: When using compile_commands.json, current_files only
        # contains source files (.cpp), not headers. Headers are tracked via header_tracker
        # and dependency graph, so we must not treat them as "deleted" just because they're
        # not in compile_commands.json. Only check if source files were deleted.
        # For headers, check if they physically exist on disk.
        deleted_files = set()
        for tracked_file in tracked_files:
            if tracked_file in current_files:
                continue  # Still in current scan, not deleted

            # File not in current_files - check if it's a header
            if tracked_file.endswith((".h", ".hpp", ".hxx", ".h++")):
                # Header file - only consider deleted if it doesn't exist on disk
                if not os.path.exists(tracked_file):
                    deleted_files.add(tracked_file)
                # else: Header exists but not in compile_commands (expected), keep it
            else:
                # Source file not in scan - it was deleted
                deleted_files.add(tracked_file)

        # Remove deleted files from all indexes
        for file_path in deleted_files:
            self._remove_file_from_indexes(file_path)
            # Remove from tracking
            if file_path in self.file_hashes:
                del self.file_hashes[file_path]
            # Note: translation_units dict removed - was never used, caused FD leak
            # Clean up per-file cache
            self.cache_manager.remove_file_cache(file_path)
            deleted += 1

        # PHASE 1: Identify files that need refreshing (hash comparison)
        tracked_file_list = list(self.file_hashes.keys())
        new_files = current_files - tracked_files

        # Scan for modified files (quick hash comparison)
        modified_files = []
        for file_path in tracked_file_list:
            if not os.path.exists(file_path):
                continue  # Skip files that no longer exist (already handled in deleted_files)

            current_hash = self._get_file_hash(file_path)
            if current_hash != self.file_hashes.get(file_path):
                modified_files.append(file_path)

        # Collect all files to process: modified + new
        files_to_process = modified_files + list(new_files)
        total_files_to_check = len(files_to_process)

        if total_files_to_check == 0:
            # No files to process, just cleanup and return
            if deleted > 0:
                self._save_cache()
                self._save_header_tracking()
                diagnostics.info(f"Removed {deleted} deleted files from indexes")
            return 0

        diagnostics.debug(f"Refresh: {len(modified_files)} modified, {len(new_files)} new files")

        # PHASE 2: Process files in parallel using ProcessPoolExecutor or ThreadPoolExecutor
        # ProcessPoolExecutor provides true parallelism (GIL bypass) for 6-7x speedup
        # ThreadPoolExecutor used as fallback when use_processes=False
        from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

        # CRITICAL: Ensure schema is current BEFORE creating workers
        # This prevents race conditions where multiple workers detect schema mismatch
        # and try to recreate the database simultaneously (causing "disk I/O error")
        if self.use_processes:
            self.cache_manager.ensure_schema_current()

        executor_class = ProcessPoolExecutor if self.use_processes else ThreadPoolExecutor
        executor_type = "ProcessPoolExecutor" if self.use_processes else "ThreadPoolExecutor"

        diagnostics.debug(f"Full refresh: Using {executor_type} with {self.max_workers} workers")

        executor = None
        failed = 0
        try:
            executor = executor_class(max_workers=self.max_workers)

            # Submit all files for parallel processing
            future_to_file = {}

            if self.use_processes:
                # ProcessPoolExecutor: use worker function (same as index_project)
                # Convert config_file to string for serialization
                project_root = str(self.project_root)
                config_file_str = (
                    str(self.project_identity.config_file_path)
                    if self.project_identity.config_file_path
                    else None
                )

                # Task 3.2: Prepare compile args for all files in main process
                # This avoids loading CompileCommandsManager in each worker (~6-10 GB memory savings)
                all_files_to_process = list(modified_files) + list(new_files)
                file_compile_args = {}
                for file_path in all_files_to_process:
                    file_path_obj = Path(file_path)
                    args = self.compile_commands_manager.get_compile_args_with_fallback(
                        file_path_obj
                    )

                    # If compile commands are not available and we're using fallback, add vcpkg includes
                    if not self.compile_commands_manager.is_file_supported(file_path_obj):
                        # Add vcpkg includes if available
                        vcpkg_include = (
                            self.project_root / "vcpkg_installed" / "x64-windows" / "include"
                        )
                        if vcpkg_include.exists():
                            args.append(f"-I{vcpkg_include}")

                        # Add common vcpkg paths
                        vcpkg_paths = [
                            "C:/vcpkg/installed/x64-windows/include",
                            "C:/dev/vcpkg/installed/x64-windows/include",
                        ]
                        for path in vcpkg_paths:
                            if Path(path).exists():
                                args.append(f"-I{path}")
                                break

                    file_compile_args[file_path] = args

                # Submit modified files (force=True)
                for file_path in modified_files:
                    abs_path = os.path.abspath(file_path)
                    future = executor.submit(
                        _process_file_worker,
                        (
                            project_root,
                            config_file_str,
                            abs_path,
                            True,  # force=True for modified files
                            self.include_dependencies,
                            file_compile_args[file_path],  # Task 3.2: Pass precomputed compile args
                        ),
                    )
                    future_to_file[future] = file_path

                # Submit new files (force=False)
                for file_path in new_files:
                    abs_path = os.path.abspath(file_path)
                    future = executor.submit(
                        _process_file_worker,
                        (
                            project_root,
                            config_file_str,
                            abs_path,
                            False,  # force=False for new files
                            self.include_dependencies,
                            file_compile_args[file_path],  # Task 3.2: Pass precomputed compile args
                        ),
                    )
                    future_to_file[future] = file_path
            else:
                # ThreadPoolExecutor: use bound method (same as before)
                for file_path in modified_files:
                    future_to_file[executor.submit(self.index_file, file_path, True)] = file_path
                for file_path in new_files:
                    future_to_file[executor.submit(self.index_file, file_path, False)] = file_path

            # Process results as they complete
            for i, future in enumerate(as_completed(future_to_file)):
                file_path = future_to_file[future]
                try:
                    if self.use_processes:
                        # ProcessPoolExecutor: worker returns (file_path, success, was_cached, symbols, call_sites, processed_headers)
                        result = future.result()
                        if result is None:
                            failed += 1
                            diagnostics.warning(f"Failed to refresh: {file_path}")
                            continue

                        _, success, was_cached, symbols, call_sites, processed_headers = result

                        if success and symbols:
                            # Merge symbols into main process (same logic as index_file)
                            with self.index_lock:
                                # CRITICAL: Clear old entries for this file FIRST (before adding new symbols)
                                # This ensures that modified files don't have duplicate/stale symbols
                                if file_path in self.file_index:
                                    for old_symbol in self.file_index[file_path]:
                                        # Remove from class_index or function_index
                                        # Issue #99: Include template kinds in class_index
                                        if old_symbol.kind in (
                                            "class",
                                            "struct",
                                            "class_template",
                                            "partial_specialization",
                                        ):
                                            if old_symbol.name in self.class_index:
                                                self.class_index[old_symbol.name] = [
                                                    s
                                                    for s in self.class_index[old_symbol.name]
                                                    if s.file != file_path
                                                ]
                                        else:
                                            if old_symbol.name in self.function_index:
                                                self.function_index[old_symbol.name] = [
                                                    s
                                                    for s in self.function_index[old_symbol.name]
                                                    if s.file != file_path
                                                ]

                                # Clear the file_index for this file
                                self.file_index[file_path] = []

                                # Now add all new symbols
                                for symbol in symbols:
                                    # Add to appropriate index
                                    if symbol.kind in ("class", "struct"):
                                        self.class_index[symbol.name].append(symbol)
                                    else:
                                        self.function_index[symbol.name].append(symbol)

                                    # USR and file indexes
                                    if symbol.usr:
                                        self.usr_index[symbol.usr] = symbol
                                    self.file_index[file_path].append(symbol)

                                # Phase 4: Stream call sites directly to SQLite
                                # This avoids accumulating ~1.9 GB in memory for large projects
                                if call_sites:
                                    diagnostics.debug(
                                        f"Streaming {len(call_sites)} call sites from {file_path} to SQLite"
                                    )
                                    # Delete existing call sites for this file (re-indexing case)
                                    if self.cache_manager and self.cache_manager.backend:
                                        self.cache_manager.backend.delete_call_sites_by_file(
                                            file_path
                                        )
                                        # Save call sites directly to SQLite
                                        self.cache_manager.backend.save_call_sites_batch(call_sites)

                                    # Update in-memory call graph (for current session queries)
                                    # but DON'T store CallSite objects in memory
                                    for cs_dict in call_sites:
                                        self.call_graph_analyzer.add_call(
                                            cs_dict["caller_usr"],
                                            cs_dict["callee_usr"],
                                            cs_dict["file"],
                                            cs_dict["line"],
                                            cs_dict.get("column"),
                                            store_call_site=False,  # Phase 4: Don't accumulate in memory
                                        )

                                # Merge header tracking from worker process
                                if processed_headers:
                                    for header_path, header_hash in processed_headers.items():
                                        self.header_tracker.mark_completed(header_path, header_hash)

                            refreshed += 1
                        else:
                            failed += 1
                            diagnostics.warning(f"Failed to refresh: {file_path}")
                    else:
                        # ThreadPoolExecutor: bound method returns (success, _)
                        success, _ = future.result()

                        if success:
                            refreshed += 1
                        else:
                            failed += 1
                            diagnostics.warning(f"Failed to refresh: {file_path}")

                except Exception as e:
                    failed += 1
                    diagnostics.error(f"Error refreshing {file_path}: {e}")

                # Report progress periodically
                if progress_callback:
                    processed = i + 1
                    # Report every 10 files or at completion
                    if processed % 10 == 0 or processed == total_files_to_check:
                        self._report_refresh_progress(
                            progress_callback,
                            total_files_to_check,
                            refreshed,
                            failed,
                            file_path,
                            start_time,
                        )

        finally:
            if executor:
                executor.shutdown(wait=True)

        if refreshed > 0 or deleted > 0:
            self._save_cache()
            # Save header tracking state after refresh
            self._save_header_tracking()
            if deleted > 0:
                diagnostics.info(f"Removed {deleted} deleted files from indexes")

        # Keep tracked file count in sync with current state
        self.indexed_file_count = len(self.file_hashes)

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

    def _remove_file_from_indexes(self, file_path: str):
        """Remove all symbols from a deleted file from all indexes"""
        with self.index_lock:
            # Get all symbols that were in this file
            symbols_to_remove = self.file_index.get(file_path, [])

            # Remove from class_index
            for symbol in symbols_to_remove:
                # Issue #99: Include template kinds in class_index
                if symbol.kind in ("class", "struct", "class_template", "partial_specialization"):
                    if symbol.name in self.class_index:
                        self.class_index[symbol.name] = [
                            info for info in self.class_index[symbol.name] if info.file != file_path
                        ]
                        # Remove empty entries
                        if not self.class_index[symbol.name]:
                            del self.class_index[symbol.name]

                # Remove from function_index
                elif symbol.kind in ("function", "method"):
                    if symbol.name in self.function_index:
                        self.function_index[symbol.name] = [
                            info
                            for info in self.function_index[symbol.name]
                            if info.file != file_path
                        ]
                        # Remove empty entries
                        if not self.function_index[symbol.name]:
                            del self.function_index[symbol.name]

                # Remove from usr_index
                if symbol.usr and symbol.usr in self.usr_index:
                    del self.usr_index[symbol.usr]

                # Remove from call graph
                if symbol.usr:
                    self.call_graph_analyzer.remove_symbol(symbol.usr)

            # Remove from file_index
            if file_path in self.file_index:
                del self.file_index[file_path]

    def get_class_info(self, class_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific class"""
        return self.search_engine.get_class_info(class_name)

    def get_function_signature(
        self, function_name: str, class_name: Optional[str] = None
    ) -> List[str]:
        """Get signature details for functions with given name, optionally within a specific class"""
        return self.search_engine.get_function_signature(function_name, class_name)

    def get_type_alias_info(self, type_name: str) -> Dict[str, Any]:
        """
        Get comprehensive type alias information for a given type name.

        Phase 1.6: MCP Tool Integration

        This method resolves type aliases bidirectionally:
        - If type_name is an alias, returns canonical type + all other aliases
        - If type_name is a canonical type, returns it + all its aliases
        - Supports unqualified, partially qualified, and fully qualified names
        - Detects and reports ambiguous type names

        Args:
            type_name: Type name to query (unqualified, partially qualified, or fully qualified)
                      Examples: "Widget", "ui::Widget", "::ui::Widget"

        Returns:
            Dictionary with type alias information:
            - Success case: canonical_type, qualified_name, namespace, file, line,
                           input_was_alias, is_ambiguous, aliases[]
            - Ambiguous case: error, is_ambiguous, matches[], suggestion
            - Not found case: error, canonical_type=null, aliases=[]

        Examples:
            # Input is canonical type
            get_type_alias_info("ui::Widget")
            → {"canonical_type": "ui::Widget", "aliases": [...], "input_was_alias": false}

            # Input is alias
            get_type_alias_info("WidgetAlias")
            → {"canonical_type": "ui::Widget", "aliases": [...], "input_was_alias": true}

            # Ambiguous unqualified name
            get_type_alias_info("Widget")
            → {"error": "Ambiguous type name 'Widget'", "is_ambiguous": true, "matches": [...]}
        """
        from .search_engine import SearchEngine

        # Step 1: Check if input is an alias first
        input_was_alias = False
        input_canonical = self.cache_manager.get_canonical_for_alias(type_name)
        if input_canonical:
            input_was_alias = True
            # Resolve alias to canonical type for search
            search_type_name = input_canonical
        else:
            search_type_name = type_name

        # Step 2: Find canonical type(s) matching the pattern
        matches = []
        with self.index_lock:
            for name, infos in self.class_index.items():
                for info in infos:
                    # Use qualified pattern matching (same as search_classes)
                    qualified_name = info.qualified_name if info.qualified_name else info.name
                    if SearchEngine.matches_qualified_pattern(qualified_name, search_type_name):
                        matches.append(info)

        # Step 3: Check for ambiguity (multiple matches with different qualified names)
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

        # Step 4: Handle not found case
        if len(matches) == 0:
            return {
                "error": f"Type '{type_name}' not found",
                "canonical_type": None,
                "aliases": [],
            }

        # Step 5: We have exactly one match (or multiple with same qualified_name)
        # Use the first match (prefer definitions over declarations)
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
        aliases = []
        if alias_names:
            # Query type_aliases table for file/line info
            # Use backend's connection directly
            try:
                self.cache_manager.backend._ensure_connected()
                for alias_name in alias_names:
                    cursor = self.cache_manager.backend.conn.execute(
                        """
                        SELECT alias_name, canonical_type, file, line, namespace,
                               is_template_alias, template_params
                        FROM type_aliases
                        WHERE alias_name = ? OR qualified_name = ?
                        """,
                        (alias_name, alias_name),
                    )
                    row = cursor.fetchone()
                    if row:
                        # Build qualified name
                        qualified_alias = (
                            f"{row['namespace']}::{row['alias_name']}"
                            if row["namespace"]
                            else row["alias_name"]
                        )

                        # Build alias dictionary
                        alias_dict = {
                            "name": row["alias_name"],
                            "qualified_name": qualified_alias,
                            "file": row["file"],
                            "line": row["line"],
                        }

                        # Add template information if present (Phase 2.0)
                        if row["is_template_alias"]:
                            alias_dict["is_template_alias"] = True
                            if row["template_params"]:
                                import json

                                alias_dict["template_params"] = json.loads(row["template_params"])

                        aliases.append(alias_dict)
            except Exception as e:
                # Log error but continue
                diagnostics.debug(f"Failed to get alias details: {e}")

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
    ):
        """
        Search for all symbols (classes and functions) matching pattern.

        Args:
            pattern: Regex pattern to search for
            project_only: Only include project files (exclude dependencies)
            symbol_types: List of symbol types to include. Options: ['class', 'struct', 'function', 'method']
                         If None, includes all types.
            namespace: Optional namespace filter (exact match, case-sensitive)
            max_results: Optional maximum number of results to return

        Returns:
            Dictionary with keys 'classes' and 'functions' containing matching symbols
            (or tuple with total_count if max_results is specified)
        """
        try:
            return self.search_engine.search_symbols(
                pattern, project_only, symbol_types, namespace, max_results
            )
        except re.error as e:
            diagnostics.error(f"Invalid regex pattern: {e}")
            return {"classes": [], "functions": []}

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
        for patterns like 'type-parameter-0-0' which indicate inheritance
        from a template parameter.

        Args:
            template_name: The template name (e.g., "ns::TemplateInheritsParam")

        Returns:
            List of parameter indices that are used as base classes.
            E.g., [0] means the template inherits from its first parameter.
        """
        import re

        # Extract simple name for class_index lookup
        simple_name = template_name.split("::")[-1] if "::" in template_name else template_name

        param_indices = []
        with self.index_lock:
            infos = self.class_index.get(simple_name, [])
            for info in infos:
                # Only check class_template entries
                if info.kind != "class_template":
                    continue

                # If qualified name was specified, must match using qualified pattern matching
                # This supports partially qualified names (e.g., "ns::MyTemplate"
                # matches "outer::ns::MyTemplate")
                if "::" in template_name:
                    info_qualified = info.qualified_name if info.qualified_name else info.name
                    if not SearchEngine.matches_qualified_pattern(info_qualified, template_name):
                        continue

                # Check base_classes for template parameter patterns
                for base in info.base_classes:
                    # Pattern: "type-parameter-X-Y" where Y is the parameter index
                    match = re.match(r"type-parameter-(\d+)-(\d+)", base)
                    if match:
                        param_index = int(match.group(2))
                        if param_index not in param_indices:
                            param_indices.append(param_index)

        return param_indices

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
        template_patterns = []
        with self.index_lock:
            # Check if class_name exists in class_index (use simple_name for lookup)
            if simple_name in self.class_index:
                for symbol in self.class_index[simple_name]:
                    # If any symbol is a template, get all specializations
                    if symbol.kind in ("class_template", "partial_specialization"):
                        # Find all specializations of this template
                        specializations = self._find_template_specializations(simple_name)
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

        with self.index_lock:
            for name, infos in self.class_index.items():
                for info in infos:
                    if not project_only or info.is_project:
                        # Check if this class inherits from the target class or any specialization
                        for base_class in info.base_classes:
                            match_found = False
                            for pattern in template_patterns:
                                # Exact match or template specialization prefix match
                                if base_class == pattern or base_class.startswith(pattern):
                                    match_found = True
                                    break
                                # Handle qualified names: "ns::BaseClass" should match "BaseClass"
                                # Check if base_class ends with "::pattern" or "::pattern<"
                                if "::" in base_class:
                                    if base_class.endswith("::" + pattern):
                                        match_found = True
                                        break
                                    if base_class.split("::")[-1].startswith(pattern):
                                        match_found = True
                                        break

                            # Issue cplusplus_mcp-hnj: Check for indirect inheritance
                            # through template parameters
                            if not match_found:
                                match_found = self._check_template_param_inheritance(
                                    base_class, simple_name
                                )

                            if match_found:
                                derived_classes.append(
                                    {
                                        "name": info.name,
                                        "kind": info.kind,
                                        "file": info.file,
                                        "line": info.line,
                                        "column": info.column,
                                        "is_project": info.is_project,
                                        "base_classes": info.base_classes,
                                        # Phase 1: Line ranges
                                        "start_line": info.start_line,
                                        "end_line": info.end_line,
                                        "header_file": info.header_file,
                                        "header_line": info.header_line,
                                        "header_start_line": info.header_start_line,
                                        "header_end_line": info.header_end_line,
                                    }
                                )
                                break  # Found a match, no need to check other base classes

        return derived_classes

    def get_class_hierarchy(self, class_name: str) -> Dict[str, Any]:
        """
        Get the complete inheritance hierarchy for a class.

        Args:
            class_name: Name of the class to analyze

        Returns:
            Dictionary containing:
            - name: The class name
            - class_info: Information about the class itself
            - base_classes: Direct base classes
            - derived_classes: Direct derived classes
            - base_hierarchy: Complete base class hierarchy tree (recursive)
            - derived_hierarchy: Complete derived class hierarchy tree (recursive)
        """
        # Get the class info
        class_info = self.get_class_info(class_name)
        if not class_info:
            return {"error": f"Class '{class_name}' not found"}

        # Get direct base classes from the class info
        # class_index is keyed by simple name, so extract it from qualified input
        is_qualified = "::" in class_name
        simple_name = SearchEngine._extract_simple_name(class_name)

        base_classes = []
        with self.index_lock:
            infos = self.class_index.get(simple_name, [])
            for info in infos:
                # If qualified name was provided, filter using qualified pattern matching
                # This supports partially qualified names (e.g., "ns::MyClass"
                # matches "outer::ns::MyClass")
                if is_qualified:
                    info_qualified = info.qualified_name if info.qualified_name else info.name
                    if not SearchEngine.matches_qualified_pattern(info_qualified, class_name):
                        continue
                base_classes.extend(info.base_classes)

        # Remove duplicates
        base_classes = list(set(base_classes))

        # Get derived classes
        derived_classes = self.get_derived_classes(class_name)

        # Build the hierarchy
        hierarchy = {
            "name": class_name,
            "class_info": class_info,
            "base_classes": base_classes,
            "derived_classes": derived_classes,
            "base_hierarchy": self._get_base_hierarchy(class_name),
            "derived_hierarchy": self._get_derived_hierarchy(class_name),
        }

        return hierarchy

    def _get_base_hierarchy(
        self, class_name: str, visited: Optional[Set[str]] = None
    ) -> Dict[str, Any]:
        """Recursively get base class hierarchy"""
        if visited is None:
            visited = set()

        if class_name in visited:
            return {"name": class_name, "circular_reference": True}

        visited.add(class_name)

        # Get base classes for this class
        # class_index is keyed by simple name, so extract it from qualified input
        is_qualified = "::" in class_name
        simple_name = SearchEngine._extract_simple_name(class_name)

        base_classes = []
        with self.index_lock:
            infos = self.class_index.get(simple_name, [])
            for info in infos:
                # If qualified name was provided, filter using qualified pattern matching
                # This supports partially qualified names (e.g., "ns::MyClass"
                # matches "outer::ns::MyClass")
                if is_qualified:
                    info_qualified = info.qualified_name if info.qualified_name else info.name
                    if not SearchEngine.matches_qualified_pattern(info_qualified, class_name):
                        continue
                base_classes.extend(info.base_classes)

        base_classes = list(set(base_classes))

        # Recursively get hierarchy for each base class
        base_hierarchies = []
        for base in base_classes:
            base_hierarchies.append(self._get_base_hierarchy(base, visited.copy()))

        return {"name": class_name, "base_classes": base_hierarchies}

    def _get_derived_hierarchy(
        self, class_name: str, visited: Optional[Set[str]] = None
    ) -> Dict[str, Any]:
        """Recursively get derived class hierarchy"""
        if visited is None:
            visited = set()

        if class_name in visited:
            return {"name": class_name, "circular_reference": True}

        visited.add(class_name)

        # Get derived classes
        derived = self.get_derived_classes(class_name, project_only=False)

        # Recursively get hierarchy for each derived class
        derived_hierarchies = []
        for d in derived:
            derived_hierarchies.append(self._get_derived_hierarchy(d["name"], visited.copy()))

        return {"name": class_name, "derived_classes": derived_hierarchies}

    def find_callers(
        self, function_name: str, class_name: str = "", include_call_sites: bool = True
    ) -> Dict[str, Any]:
        """
        Find all functions that call the specified function.

        Args:
            function_name: Name of the target function
            class_name: Optional class name to disambiguate methods
            include_call_sites: Whether to include call site locations (Phase 3)

        Returns:
            Dictionary with:
                - callers: List of caller function info (backward compatible)
                - call_sites: List of call site locations (Phase 3, if include_call_sites=True)
        """
        callers_list = []
        call_sites_list = []

        # Find the target function(s)
        target_functions = self.search_functions(
            f"^{re.escape(function_name)}$", project_only=False, class_name=class_name
        )

        # Collect USRs of target functions
        target_usrs = set()
        for func in target_functions:
            # Find the full symbol info with USR
            for symbol in self.function_index.get(func["name"], []):
                if symbol.usr and symbol.file == func["file"] and symbol.line == func["line"]:
                    target_usrs.add(symbol.usr)

        # Find all callers
        for usr in target_usrs:
            callers = self.call_graph_analyzer.find_callers(usr)
            for caller_usr in callers:
                if caller_usr in self.usr_index:
                    caller_info = self.usr_index[caller_usr]
                    callers_list.append(
                        {
                            "name": caller_info.name,
                            "kind": caller_info.kind,
                            "file": caller_info.file,
                            "line": caller_info.line,
                            "column": caller_info.column,
                            "signature": caller_info.signature,
                            "parent_class": caller_info.parent_class,
                            "is_project": caller_info.is_project,
                            "start_line": caller_info.start_line,
                            "end_line": caller_info.end_line,
                        }
                    )

            # Phase 3: Get call sites with line-level precision
            if include_call_sites:
                call_sites = self.call_graph_analyzer.get_call_sites_for_callee(usr)
                for call_site in call_sites:
                    # Get caller info for each call site
                    if call_site.caller_usr in self.usr_index:
                        caller_info = self.usr_index[call_site.caller_usr]
                        call_sites_list.append(
                            {
                                "file": call_site.file,
                                "line": call_site.line,
                                "column": call_site.column,
                                "caller": caller_info.name,
                                "caller_file": caller_info.file,
                                "caller_signature": caller_info.signature,
                            }
                        )

        # Return dictionary with both callers and call_sites
        result = {"function": function_name, "callers": callers_list}

        if include_call_sites:
            # Sort call sites by file, then line
            call_sites_list.sort(key=lambda cs: (cs["file"], cs["line"]))
            result["call_sites"] = call_sites_list
            result["total_call_sites"] = len(call_sites_list)

        return result

    def get_call_sites(self, function_name: str, class_name: str = "") -> List[Dict[str, Any]]:
        """
        Get all call sites FROM a specific function with line-level precision (Phase 3).

        Args:
            function_name: Name of the source function
            class_name: Optional class name to disambiguate methods

        Returns:
            List of call site dictionaries with exact file:line:column locations
        """
        call_sites_list = []

        # Find the source function(s)
        source_functions = self.search_functions(
            f"^{re.escape(function_name)}$", project_only=False, class_name=class_name
        )

        # Collect USRs of source functions
        source_usrs = set()
        for func in source_functions:
            # Find the full symbol info with USR
            for symbol in self.function_index.get(func["name"], []):
                if symbol.usr and symbol.file == func["file"] and symbol.line == func["line"]:
                    source_usrs.add(symbol.usr)

        # Get call sites for each source function
        for usr in source_usrs:
            call_sites = self.call_graph_analyzer.get_call_sites_for_caller(usr)
            for call_site in call_sites:
                # Get target function info
                if call_site.callee_usr in self.usr_index:
                    target_info = self.usr_index[call_site.callee_usr]
                    call_sites_list.append(
                        {
                            "target": target_info.name,
                            "target_signature": target_info.signature,
                            "target_file": target_info.file,
                            "target_kind": target_info.kind,
                            "file": call_site.file,
                            "line": call_site.line,
                            "column": call_site.column,
                        }
                    )

        # Sort by file, then line
        call_sites_list.sort(key=lambda cs: (cs["file"], cs["line"]))

        return call_sites_list

    def find_callees(self, function_name: str, class_name: str = "") -> List[Dict[str, Any]]:
        """Find all functions called by the specified function"""
        results = []

        # Find the target function(s)
        target_functions = self.search_functions(
            f"^{re.escape(function_name)}$", project_only=False, class_name=class_name
        )

        # Collect USRs of target functions
        target_usrs = set()
        for func in target_functions:
            # Find the full symbol info with USR
            for symbol in self.function_index.get(func["name"], []):
                if symbol.usr and symbol.file == func["file"] and symbol.line == func["line"]:
                    target_usrs.add(symbol.usr)

        # Find all callees
        for usr in target_usrs:
            callees = self.call_graph_analyzer.find_callees(usr)
            for callee_usr in callees:
                if callee_usr in self.usr_index:
                    callee_info = self.usr_index[callee_usr]
                    results.append(
                        {
                            "name": callee_info.name,
                            "kind": callee_info.kind,
                            "file": callee_info.file,
                            "line": callee_info.line,
                            "column": callee_info.column,
                            "signature": callee_info.signature,
                            "parent_class": callee_info.parent_class,
                            "is_project": callee_info.is_project,
                        }
                    )

        return results

    def get_call_path(
        self, from_function: str, to_function: str, max_depth: int = 10
    ) -> List[List[str]]:
        """Find call paths from one function to another using BFS"""
        # Find source and target USRs
        from_funcs = self.search_functions(f"^{re.escape(from_function)}$", project_only=False)
        to_funcs = self.search_functions(f"^{re.escape(to_function)}$", project_only=False)

        if not from_funcs or not to_funcs:
            return []

        # Get USRs
        from_usrs = set()
        for func in from_funcs:
            for symbol in self.function_index.get(func["name"], []):
                if symbol.usr and symbol.file == func["file"] and symbol.line == func["line"]:
                    from_usrs.add(symbol.usr)

        to_usrs = set()
        for func in to_funcs:
            for symbol in self.function_index.get(func["name"], []):
                if symbol.usr and symbol.file == func["file"] and symbol.line == func["line"]:
                    to_usrs.add(symbol.usr)

        # BFS to find paths
        paths = []
        for from_usr in from_usrs:
            # Queue contains (current_usr, path)
            queue = [(from_usr, [from_usr])]
            visited = {from_usr}
            depth = 0

            while queue and depth < max_depth:
                next_queue = []
                for current_usr, path in queue:
                    # Check if we reached the target
                    if current_usr in to_usrs:
                        # Convert path of USRs to function names
                        name_path = []
                        for usr in path:
                            if usr in self.usr_index:
                                info = self.usr_index[usr]
                                name_path.append(
                                    f"{info.parent_class}::{info.name}"
                                    if info.parent_class
                                    else info.name
                                )
                        paths.append(name_path)
                        continue

                    # Explore callees
                    for callee_usr in self.call_graph_analyzer.find_callees(current_usr):
                        if callee_usr not in visited:
                            visited.add(callee_usr)
                            next_queue.append((callee_usr, path + [callee_usr]))

                queue = next_queue
                depth += 1

        return paths

    def find_in_file(self, file_path: str, pattern: str) -> Dict[str, Any]:
        """Search for symbols within a specific file or files matching a glob pattern.

        Phase 2 (Qualified Names): Supports qualified pattern matching.
        Phase LLM: Supports glob patterns and returns suggestions when no match.

        File path formats:
        - Absolute path: /full/path/to/file.cpp
        - Relative path: src/main.cpp (relative to project root)
        - Filename only: main.cpp (matches any file with this name)
        - Glob pattern: **/Tests/**/*.cpp, src/*.h (matches multiple files)

        Symbol pattern matching modes:
        - Empty string ("") matches ALL symbols in the file(s)
        - Unqualified ("View") matches View in any namespace (case-insensitive)
        - Qualified ("ui::View") matches with component-based suffix
        - Exact ("::View") matches only global namespace symbols
        - Regex ("test.*") uses case-insensitive regex fullmatch

        Args:
            file_path: Path to file (absolute, relative, filename, or glob pattern)
            pattern: Search pattern (qualified, unqualified, or regex)

        Returns:
            Dict with:
            - results: List of matching symbols
            - matched_files: Files that were searched (for glob patterns)
            - suggestions: Similar file paths when no exact match (for non-glob)
            - message: Helpful message about the search

        Examples:
            find_in_file("view.h", "View") - all View symbols in view.h
            find_in_file("**/tests/**/*.cpp", "") - all symbols in test files
            find_in_file("myfile", "") - suggestions if not found

        Task: T2.2.4 (Qualified Names Phase 2), LLM Integration (bd1)
        """
        import fnmatch

        # Detect if file_path is a glob pattern
        glob_chars = set("*?[]")
        is_glob = any(c in file_path for c in glob_chars)

        if is_glob:
            return self._find_in_files_glob(file_path, pattern)
        else:
            return self._find_in_file_exact(file_path, pattern)

    def _find_in_files_glob(self, glob_pattern: str, symbol_pattern: str) -> Dict[str, Any]:
        """Search for symbols in files matching a glob pattern.

        Args:
            glob_pattern: Glob pattern to match files (e.g., '**/tests/**/*.cpp')
            symbol_pattern: Symbol search pattern

        Returns:
            Dict with results, matched_files, and message
        """
        import fnmatch

        # Match glob pattern against all indexed files
        matched_files = []
        for indexed_file in self.file_index.keys():
            # Try both the pattern as-is and with **/ prefix for convenience
            if fnmatch.fnmatch(indexed_file, glob_pattern):
                matched_files.append(indexed_file)
            elif fnmatch.fnmatch(indexed_file, "**/" + glob_pattern):
                matched_files.append(indexed_file)
            # Also try matching just the relative path from project root
            elif self.project_root:
                try:
                    rel_path = str(Path(indexed_file).relative_to(self.project_root))
                    if fnmatch.fnmatch(rel_path, glob_pattern):
                        matched_files.append(indexed_file)
                except ValueError:
                    pass

        if not matched_files:
            return {
                "results": [],
                "matched_files": [],
                "suggestions": self._get_path_suggestions(glob_pattern),
                "message": f"No files found matching glob pattern '{glob_pattern}'",
            }

        # Search in both class and function results
        all_classes = self.search_classes(symbol_pattern, project_only=False)
        all_functions = self.search_functions(symbol_pattern, project_only=False)

        results = []
        matched_files_set = set(matched_files)

        for item in all_classes + all_functions:
            item_file = item.get("file", "")
            if item_file in matched_files_set:
                results.append(item)

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
            item_file = item.get("file", "")
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
        files = set()
        total_refs = 0
        kind = None

        with self.index_lock:
            # 1. Find where symbol is defined (classes)
            if symbol_kind in (None, "class"):
                for qname, infos in self.class_index.items():
                    for info in infos:
                        if info.name == symbol_name:
                            if not project_only or info.is_project:
                                files.add(info.file)
                                if info.header_file:
                                    files.add(info.header_file)
                                kind = info.kind
                                break

            # 2. Find where symbol is defined (functions/methods)
            if symbol_kind in (None, "function", "method"):
                for qname, infos in self.function_index.items():
                    for info in infos:
                        if info.name == symbol_name:
                            if not project_only or info.is_project:
                                files.add(info.file)
                                if info.header_file:
                                    files.add(info.header_file)
                                if not kind:  # Don't override if already set
                                    kind = info.kind
                                # Don't break - could be overloaded

            # 3. Find callers (for functions/methods)
            if kind in ("function", "method") or (
                not kind and symbol_kind in (None, "function", "method")
            ):
                # Get USRs for all functions with this name
                target_usrs = set()
                for infos in self.function_index.values():
                    for info in infos:
                        if info.name == symbol_name and info.usr:
                            if not project_only or info.is_project:
                                target_usrs.add(info.usr)

                # Find all callers of these functions
                for usr in target_usrs:
                    callers = self.call_graph_analyzer.find_callers(usr)
                    for caller_usr in callers:
                        if caller_usr in self.usr_index:
                            caller_info = self.usr_index[caller_usr]
                            if not project_only or caller_info.is_project:
                                files.add(caller_info.file)
                                total_refs += 1

            # 4. For classes, find files that use the class (approximate via search)
            # This catches instantiations, member access, etc. that aren't in call graph
            if kind in ("class", "struct") or (not kind and symbol_kind in (None, "class")):
                # Check file index for files that might reference the class
                for file_path, symbols in self.file_index.items():
                    if not project_only or self._is_project_file(file_path):
                        # If file has the class definition or any methods of the class
                        for symbol in symbols:
                            if symbol.name == symbol_name or symbol.parent_class == symbol_name:
                                files.add(file_path)
                                break

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
    print("Testing Python CppAnalyzer...")
    analyzer = CppAnalyzer(".")

    # Try to load from cache first
    if not analyzer._load_cache():
        analyzer.index_project()

    stats = analyzer.get_stats()
    print(f"Stats: {stats}")

    classes = analyzer.search_classes(".*", project_only=True)
    print(f"Found {len(classes)} project classes")

    functions = analyzer.search_functions(".*", project_only=True)
    print(f"Found {len(functions)} project functions")
