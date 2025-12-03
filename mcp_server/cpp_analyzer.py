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


def _process_file_worker(args_tuple):
    """
    Worker function for ProcessPoolExecutor-based parallel parsing.

    This is a module-level function (required for pickling) that creates
    a minimal analyzer instance to parse a single file.

    Args:
        args_tuple: (project_root, file_path, force, include_dependencies)

    Returns:
        (file_path, success, was_cached, symbols)
        where symbols is a list of SymbolInfo objects or empty list on failure
    """
    project_root, file_path, force, include_dependencies = args_tuple

    # Create a minimal analyzer for this process
    # Each process gets its own analyzer instance
    analyzer = CppAnalyzer(project_root)
    analyzer.include_dependencies = include_dependencies

    # Mark this instance as isolated (no shared memory, locks not needed)
    # This is a worker process with its own memory space
    analyzer._needs_locking = False

    # Parse the file
    success, was_cached = analyzer.index_file(file_path, force)

    # Extract symbols from this file
    # No lock needed here since this process has isolated memory
    symbols = []
    if success:
        if file_path in analyzer.file_index:
            symbols = analyzer.file_index[file_path]

    return (file_path, success, was_cached, symbols)


class CppAnalyzer:
    """
    Pure Python C++ code analyzer using libclang.

    This class provides code analysis functionality including:
    - Class and struct discovery
    - Function and method discovery
    - Symbol search with regex patterns
    - File-based filtering
    """

    def __init__(self, project_root: str, config_file: Optional[str] = None):
        """
        Initialize C++ Analyzer.

        Args:
            project_root: Path to project source directory
            config_file: Optional path to configuration file for project identity

        Note:
            Project identity is determined by (source_directory, config_file) pair.
            Different config_file values create separate cache directories.
        """
        self.project_root = Path(project_root).resolve()
        self.index = Index.create()

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

        # Initialize search engine
        self.search_engine = SearchEngine(
            self.class_index,
            self.function_index,
            self.file_index,
            self.usr_index
        )

        # Track indexed files
        self.translation_units: Dict[str, TranslationUnit] = {}
        self.file_hashes: Dict[str, str] = {}

        # Threading/Processing
        self.index_lock = threading.Lock()
        self._no_op_lock = _NoOpLock()  # Reusable no-op lock for isolated processes
        self._thread_local = threading.local()
        cpu_count = os.cpu_count() or 1
        # Use cpu_count directly for CPU-bound parsing work
        # Using cpu_count * 2 causes excessive lock contention
        self.max_workers = cpu_count

        # Use ProcessPoolExecutor by default to bypass Python's GIL
        # Can be overridden via environment variable
        self.use_processes = os.environ.get('CPP_ANALYZER_USE_THREADS', '').lower() != 'true'

        # Locking strategy:
        # - True (default): Use locks for thread safety (ThreadPoolExecutor or shared instance)
        # - False: Skip locks for performance (ProcessPoolExecutor worker with isolated memory)
        # This flag is set to False by _process_file_worker for worker processes
        self._needs_locking = True

        # Initialize cache manager with project identity
        self.cache_manager = CacheManager(self.project_identity)
        self.file_scanner = FileScanner(self.project_root)
        
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

        # Initialize compile commands manager with config and cache directory
        compile_commands_config = self.config.get_compile_commands_config()
        self.compile_commands_manager = CompileCommandsManager(
            self.project_root,
            compile_commands_config,
            cache_dir=self.cache_manager.cache_dir
        )

        # Initialize header processing tracker for first-win strategy
        self.header_tracker = HeaderProcessingTracker()

        # Initialize dependency graph builder for incremental analysis
        # Note: Only initialize if using SQLite backend (has conn attribute)
        self.dependency_graph = None
        if hasattr(self.cache_manager.backend, 'conn'):
            self.dependency_graph = DependencyGraphBuilder(self.cache_manager.backend.conn)
            diagnostics.debug("Dependency graph builder initialized")
        else:
            diagnostics.debug("Dependency graph not available (non-SQLite backend)")

        # Track compile_commands.json version for header tracking invalidation
        self.compile_commands_hash = ""
        self._calculate_compile_commands_hash()

        # Restore or reset header tracking based on compile_commands.json version
        self._restore_or_reset_header_tracking()

        diagnostics.debug(f"CppAnalyzer initialized for project: {self.project_root}")
        diagnostics.debug(f"Concurrency mode: {'ProcessPool (GIL bypass)' if self.use_processes else 'ThreadPool'} with {self.max_workers} workers")

        # Print compile commands configuration status
        if self.compile_commands_manager.enabled:
            cc_path = self.project_root / compile_commands_config['compile_commands_path']
            if cc_path.exists():
                # This message will be followed by actual load message from CompileCommandsManager
                diagnostics.debug(f"Compile commands enabled: using {compile_commands_config['compile_commands_path']}")
            else:
                diagnostics.debug(f"Compile commands enabled: {compile_commands_config['compile_commands_path']} not found, will use fallback args")
        else:
            diagnostics.debug("Compile commands disabled in configuration")

    def close(self):
        """
        Close the analyzer and release all resources.

        This should be called when the CppAnalyzer is no longer needed
        to properly close database connections and avoid resource leaks.
        """
        if hasattr(self, 'cache_manager') and self.cache_manager is not None:
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
        self.close()

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
        if not self.compile_commands_manager.enabled:
            self.compile_commands_hash = ""
            return

        # Get compile_commands.json path from configuration
        compile_commands_config = self.config.get_compile_commands_config()
        cc_path = self.project_root / compile_commands_config['compile_commands_path']

        if not cc_path.exists():
            self.compile_commands_hash = ""
            return

        try:
            with open(cc_path, 'rb') as f:
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
            with open(tracker_cache_path, 'r') as f:
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

        except Exception as e:
            diagnostics.warning(f"Failed to restore header tracking from cache: {e}")
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
                "timestamp": time.time()
            }

            # Ensure cache directory exists
            tracker_cache_path.parent.mkdir(parents=True, exist_ok=True)

            # Write to file (atomic write via temp file)
            temp_path = tracker_cache_path.with_suffix('.tmp')
            with open(temp_path, 'w') as f:
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

    def _get_thread_local_buffers(self):
        """Get thread-local buffers, initializing if needed."""
        if not hasattr(self._thread_local, 'collected_symbols'):
            self._init_thread_local_buffers()
        return self._thread_local.collected_symbols, self._thread_local.collected_calls

    def _bulk_write_symbols(self):
        """
        Bulk write collected symbols to shared indexes with a single lock acquisition.

        This method takes all symbols collected in thread-local buffers during parsing
        and adds them to the shared indexes in one atomic operation, dramatically
        reducing lock contention compared to per-symbol locking.

        Returns:
            Number of symbols actually added (after deduplication)
        """
        symbols_buffer, calls_buffer = self._get_thread_local_buffers()

        if not symbols_buffer and not calls_buffer:
            return 0

        added_count = 0

        # Single lock acquisition for all symbols (conditional based on execution mode)
        with self._get_lock():
            # Add all collected symbols
            for info in symbols_buffer:
                # USR-based deduplication: check if symbol already exists
                if info.usr and info.usr in self.usr_index:
                    # Symbol already exists (from another file/thread)
                    continue

                # New symbol - add to all indexes
                if info.kind in ("class", "struct"):
                    self.class_index[info.name].append(info)
                else:
                    self.function_index[info.name].append(info)

                if info.usr:
                    self.usr_index[info.usr] = info

                if info.file:
                    if info.file not in self.file_index:
                        self.file_index[info.file] = []
                    self.file_index[info.file].append(info)

                added_count += 1

            # Add all collected call relationships
            for caller_usr, called_usr in calls_buffer:
                self.call_graph_analyzer.add_call(caller_usr, called_usr)

        # Clear buffers for next use
        symbols_buffer.clear()
        calls_buffer.clear()

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
            '/usr/include/',
            '/usr/local/include/',
            'lib/clang/',  # Clang builtin headers (e.g., arm_acle.h, arm_neon.h)
            '/Library/Developer/CommandLineTools/usr/lib/clang/',  # macOS
            '/Library/Developer/CommandLineTools/SDKs/',  # macOS SDK
            'C:\\Program Files',  # Windows system
            '/opt/homebrew/',  # macOS Homebrew
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

        if tu and hasattr(tu, 'diagnostics'):
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

    def _save_file_cache(self, file_path: str, symbols: List[SymbolInfo], file_hash: str,
                        compile_args_hash: Optional[str] = None, success: bool = True,
                        error_message: Optional[str] = None, retry_count: int = 0):
        """Save parsed symbols for a single file to cache"""
        self.cache_manager.save_file_cache(
            file_path, symbols, file_hash, compile_args_hash,
            success, error_message, retry_count
        )

    def _load_file_cache(self, file_path: str, current_hash: str,
                        compile_args_hash: Optional[str] = None) -> Optional[Dict[str, Any]]:
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
        if self.compile_commands_manager.enabled:
            compile_commands_files = self.compile_commands_manager.get_all_files()
            if compile_commands_files:
                diagnostics.debug(f"Using {len(compile_commands_files)} files from compile_commands.json")
                return compile_commands_files

        # Fall back to scanning all C++ files
        # Update file scanner with dependencies setting
        self.file_scanner.include_dependencies = include_dependencies
        return self.file_scanner.find_cpp_files()
    
    def _get_base_classes(self, cursor) -> List[str]:
        """Extract base class names from a class cursor"""
        base_classes = []
        for child in cursor.get_children():
            if child.kind == CursorKind.CXX_BASE_SPECIFIER:
                # Get the referenced class name
                base_type = child.type.spelling
                # Clean up the type name (remove "class " prefix if present)
                if base_type.startswith("class "):
                    base_type = base_type[6:]
                base_classes.append(base_type)
        return base_classes
    
    def _process_cursor(self, cursor, should_extract_from_file=None, parent_class: str = "", parent_function_usr: str = ""):
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
            - Always traverse entire AST (to discover all files)
            - Only extract symbols when should_extract_from_file returns True
            - This enables multi-file extraction (source + headers) in single pass
            - Collects symbols in thread-local buffers to avoid lock contention

        Implements:
            REQ-10.1.6: Use cursor.location.file to determine which file symbol belongs to
        """
        # Get thread-local buffers for lock-free collection
        symbols_buffer, calls_buffer = self._get_thread_local_buffers()

        # Determine if we should extract from this cursor's file
        should_extract = True
        if cursor.location.file and should_extract_from_file is not None:
            file_path = str(cursor.location.file.name)
            should_extract = should_extract_from_file(file_path)

        # Get cursor kind, handling unknown kinds from version mismatches
        try:
            kind = cursor.kind
        except ValueError as e:
            # This can happen when libclang library supports newer C++ features
            # but Python bindings have outdated cursor kind enums
            # Just skip this cursor and continue with children
            diagnostics.debug(f"Skipping cursor with unknown kind: {e}")
            for child in cursor.get_children():
                self._process_cursor(child, should_extract_from_file, parent_class, parent_function_usr)
            return

        # Process classes and structs (only if should extract)
        if kind in (CursorKind.CLASS_DECL, CursorKind.STRUCT_DECL):
            if cursor.spelling and should_extract:
                # Get base classes
                base_classes = self._get_base_classes(cursor)

                info = SymbolInfo(
                    name=cursor.spelling,
                    kind="class" if kind == CursorKind.CLASS_DECL else "struct",
                    file=cursor.location.file.name if cursor.location.file else "",
                    line=cursor.location.line,
                    column=cursor.location.column,
                    is_project=self._is_project_file(cursor.location.file.name) if cursor.location.file else False,
                    parent_class="",  # Classes don't have parent classes in this context
                    base_classes=base_classes,
                    usr=cursor.get_usr() if cursor.get_usr() else ""
                )

                # Collect symbol in thread-local buffer (no lock needed)
                symbols_buffer.append(info)

            # Always process children (even if we didn't extract this symbol)
            # Children might be in different files
            for child in cursor.get_children():
                self._process_cursor(child, should_extract_from_file, cursor.spelling if should_extract else parent_class, parent_function_usr)
            return  # Don't process children again below

        # Process functions and methods (only if should extract)
        elif kind in (CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD):
            if cursor.spelling and should_extract:
                # Get function signature
                signature = ""
                if cursor.type:
                    signature = cursor.type.spelling

                function_usr = cursor.get_usr() if cursor.get_usr() else ""

                info = SymbolInfo(
                    name=cursor.spelling,
                    kind="function" if kind == CursorKind.FUNCTION_DECL else "method",
                    file=cursor.location.file.name if cursor.location.file else "",
                    line=cursor.location.line,
                    column=cursor.location.column,
                    signature=signature,
                    is_project=self._is_project_file(cursor.location.file.name) if cursor.location.file else False,
                    parent_class=parent_class if kind == CursorKind.CXX_METHOD else "",
                    usr=function_usr
                )

                # Collect symbol in thread-local buffer (no lock needed)
                symbols_buffer.append(info)

            # Always process children (for call tracking and nested symbols)
            # Use function_usr only if we extracted this function
            current_function_usr = cursor.get_usr() if (should_extract and cursor.get_usr()) else parent_function_usr
            for child in cursor.get_children():
                self._process_cursor(child, should_extract_from_file, parent_class, current_function_usr)
            return  # Don't process children again below

        # Process function calls within function bodies
        elif kind == CursorKind.CALL_EXPR and parent_function_usr:
            # This is a function call inside a function
            referenced = cursor.referenced
            if referenced and referenced.get_usr():
                called_usr = referenced.get_usr()
                # Collect call relationship in thread-local buffer (no lock needed)
                calls_buffer.append((parent_function_usr, called_usr))

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

        # Save header tracker state to disk (implements REQ-10.5.4)
        self._save_header_tracking()

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
            "skipped": list(skipped_headers)
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
            self.cache_manager.log_parse_error(
                file_path, file_not_found_error, "", None, 0
            )

            return (False, False)

        current_hash = self._get_file_hash(file_path)

        # Get compilation arguments to compute hash (needed for cache validation)
        file_path_obj = Path(file_path)
        args = self.compile_commands_manager.get_compile_args_with_fallback(file_path_obj)

        # If compile commands are not available and we're using fallback, add vcpkg includes
        if not self.compile_commands_manager.is_file_supported(file_path_obj):
            # Add vcpkg includes if available
            vcpkg_include = self.project_root / "vcpkg_installed" / "x64-windows" / "include"
            if vcpkg_include.exists():
                args.append(f'-I{vcpkg_include}')

            # Add common vcpkg paths
            vcpkg_paths = [
                "C:/vcpkg/installed/x64-windows/include",
                "C:/dev/vcpkg/installed/x64-windows/include"
            ]
            for path in vcpkg_paths:
                if Path(path).exists():
                    args.append(f'-I{path}')
                    break

        # Compute hash of compilation arguments for cache validation
        compile_args_hash = self._compute_compile_args_hash(args)

        # Try to load from per-file cache first
        if not force:
            cache_data = self._load_file_cache(file_path, current_hash, compile_args_hash)
            if cache_data is not None:
                # Check if this file previously failed and if we should retry
                if not cache_data['success']:
                    retry_count = cache_data['retry_count']
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
                    cached_symbols = cache_data['symbols']

                    # Prepare index updates outside the lock to minimize lock duration
                    # Build updates for class_index and function_index
                    class_updates = defaultdict(list)
                    function_updates = defaultdict(list)
                    usr_updates = {}
                    call_graph_updates = []

                    for symbol in cached_symbols:
                        if symbol.kind in ("class", "struct"):
                            class_updates[symbol.name].append(symbol)
                        else:
                            function_updates[symbol.name].append(symbol)

                        if symbol.usr:
                            usr_updates[symbol.usr] = symbol

                        # Collect call graph relationships
                        if symbol.calls:
                            for called_usr in symbol.calls:
                                call_graph_updates.append((symbol.usr, called_usr))
                        if symbol.called_by:
                            for caller_usr in symbol.called_by:
                                call_graph_updates.append((caller_usr, symbol.usr))

                    # Apply all updates with a single lock acquisition
                    # Use conditional lock (no-op in ProcessPoolExecutor worker processes)
                    with self._get_lock():
                        # Clear old entries for this file
                        if file_path in self.file_index:
                            for info in self.file_index[file_path]:
                                if info.kind in ("class", "struct"):
                                    self.class_index[info.name] = [
                                        i for i in self.class_index[info.name] if i.file != file_path
                                    ]
                                else:
                                    self.function_index[info.name] = [
                                        i for i in self.function_index[info.name] if i.file != file_path
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

                        # Restore call graph relationships
                        for caller_usr, called_usr in call_graph_updates:
                            self.call_graph_analyzer.add_call(caller_usr, called_usr)

                        self.file_hashes[file_path] = current_hash

                    return (True, True)  # Successfully loaded from cache

        # Determine retry count for this attempt
        retry_count = 0
        if not force:
            cache_data = self._load_file_cache(file_path, current_hash, compile_args_hash)
            if cache_data is not None and not cache_data['success']:
                retry_count = cache_data['retry_count'] + 1  # Increment for this retry

        try:
            # Create translation unit with detailed diagnostics
            # Note: We no longer skip function bodies to enable call graph analysis
            index = self._get_thread_index()

            # Try parsing with progressive fallback if initial attempt fails
            tu = None
            parse_options_attempts = [
                # Attempt 1: Full detailed processing (best for analysis)
                (TranslationUnit.PARSE_INCOMPLETE | TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
                 "full detailed processing"),
                # Attempt 2: Just incomplete (more compatible)
                (TranslationUnit.PARSE_INCOMPLETE,
                 "incomplete parsing"),
                # Attempt 3: Minimal options (maximum compatibility)
                (0,
                 "minimal options"),
            ]

            last_error = None
            for options, description in parse_options_attempts:
                try:
                    tu = index.parse(
                        file_path,
                        args=args,
                        options=options
                    )
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
                if any('-std=c++' in arg for arg in args):
                    std_args = [arg for arg in args if '-std=c++' in arg]
                    hints.append(f"C++ standard specified: {std_args}")
                if not self.compile_commands_manager.clang_resource_dir:
                    hints.append("Clang resource directory not detected - system headers may be missing")
                if self.compile_commands_manager.is_file_supported(Path(file_path)):
                    hints.append("Using args from compile_commands.json - check if they are libclang-compatible")
                else:
                    hints.append("Using fallback compilation args - compile_commands.json may be needed")

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
                    file_path, [], current_hash, compile_args_hash,
                    success=False, error_message=error_msg[:200], retry_count=retry_count
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
                full_error_msg = f"libclang parsing errors ({len(error_diagnostics)} total):\n{formatted_errors}"

                # Truncate for cache
                cache_error_msg = full_error_msg[:200]

                # Log to centralized error log with full message
                parse_error = Exception(full_error_msg)
                self.cache_manager.log_parse_error(
                    file_path, parse_error, current_hash, compile_args_hash, retry_count
                )

                # Log as warning but continue processing
                # libclang provides a usable partial AST even with errors
                diagnostics.warning(f"{file_path}: Continuing despite {len(error_diagnostics)} error(s):\n{cache_error_msg}")

            # Log warnings at debug level but continue processing
            if warning_diagnostics:
                formatted_warnings = self._format_diagnostics(warning_diagnostics, max_count=3)
                diagnostics.debug(f"{file_path}: {len(warning_diagnostics)} warning(s):\n{formatted_warnings}")

            # Clear old entries for this file before re-parsing
            # This must be atomic to ensure index consistency
            # Use conditional lock (no-op in ProcessPoolExecutor worker processes)
            with self._get_lock():
                if file_path in self.file_index:
                    # Remove old entries from class and function indexes
                    for info in self.file_index[file_path]:
                        if info.kind in ("class", "struct"):
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
            processed_count = len(extraction_result['processed'])
            skipped_count = len(extraction_result['skipped'])
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

            # Populate call graph info OUTSIDE the lock to minimize lock duration
            # Call graph queries can be expensive for large codebases
            for symbol in collected_symbols:
                if symbol.usr and symbol.kind in ("function", "method"):
                    # Add calls list
                    # Get calls from call graph analyzer
                    calls = self.call_graph_analyzer.find_callees(symbol.usr)
                    if calls:
                        symbol.calls = list(calls)
                    # Add called_by list
                    callers = self.call_graph_analyzer.find_callers(symbol.usr)
                    if callers:
                        symbol.called_by = list(callers)
            
            # Save to per-file cache (mark as successfully parsed, even if there were errors)
            # Note: success=True means we got a usable TU and extracted symbols
            # error_message will be set if there were parsing errors (partial parse)
            self._save_file_cache(
                file_path, collected_symbols, current_hash, compile_args_hash,
                success=True, error_message=cache_error_msg, retry_count=0
            )

            # Update tracking
            # Use conditional lock (no-op in ProcessPoolExecutor worker processes)
            with self._get_lock():
                self.translation_units[file_path] = tu
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
                file_path, [], current_hash, compile_args_hash,
                success=False, error_message=error_msg, retry_count=retry_count
            )

            diagnostics.debug(f"Failed to parse {file_path}: {error_msg}")
            return (False, False)  # Failed, not from cache

    def index_project(
        self,
        force: bool = False,
        include_dependencies: bool = True,
        progress_callback: Optional[Callable] = None
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
        is_terminal = (hasattr(sys.stderr, 'isatty') and sys.stderr.isatty() and 
                      not os.environ.get('MCP_SESSION_ID') and
                      not os.environ.get('CLAUDE_CODE_SESSION'))
        
        # No special test mode needed - we'll handle Windows console properly

        # Choose executor based on configuration
        # ProcessPoolExecutor bypasses Python's GIL for true parallelism
        executor_class = ProcessPoolExecutor if self.use_processes else ThreadPoolExecutor

        if self.use_processes:
            diagnostics.debug(f"Using ProcessPoolExecutor with {self.max_workers} workers (GIL bypass)")
        else:
            diagnostics.debug(f"Using ThreadPoolExecutor with {self.max_workers} workers")

        with executor_class(max_workers=self.max_workers) as executor:
            if self.use_processes:
                # ProcessPoolExecutor: use worker function that returns symbols
                future_to_file = {
                    executor.submit(_process_file_worker,
                                  (str(self.project_root), os.path.abspath(file_path),
                                   force, include_dependencies)): os.path.abspath(file_path)
                    for file_path in files
                }
            else:
                # ThreadPoolExecutor: use index_file method directly
                future_to_file = {
                    executor.submit(self.index_file, os.path.abspath(file_path), force): os.path.abspath(file_path)
                    for file_path in files
                }

            for i, future in enumerate(as_completed(future_to_file)):
                file_path = future_to_file[future]
                try:
                    result = future.result()

                    if self.use_processes:
                        # ProcessPoolExecutor returns (file_path, success, was_cached, symbols)
                        _, success, was_cached, symbols = result

                        # Merge symbols into main process indexes
                        if success and symbols:
                            with self.index_lock:
                                for symbol in symbols:
                                    # Add to appropriate index
                                    if symbol.kind in ("class", "struct"):
                                        self.class_index[symbol.name].append(symbol)
                                    else:
                                        self.function_index[symbol.name].append(symbol)

                                    # Add to USR index
                                    if symbol.usr:
                                        self.usr_index[symbol.usr] = symbol

                                    # Add to file index
                                    if symbol.file:
                                        if symbol.file not in self.file_index:
                                            self.file_index[symbol.file] = []
                                        self.file_index[symbol.file].append(symbol)

                                    # Restore call graph
                                    if symbol.calls:
                                        for called_usr in symbol.calls:
                                            self.call_graph_analyzer.add_call(symbol.usr, called_usr)
                                    if symbol.called_by:
                                        for caller_usr in symbol.called_by:
                                            self.call_graph_analyzer.add_call(caller_usr, symbol.usr)

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
                        (processed <= 5) or
                        (processed % 5 == 0) or
                        ((current_time - last_report_time) > 2.0) or
                        (processed == len(files))
                    )
                else:
                    should_report = (
                        (processed % 50 == 0) or
                        ((current_time - last_report_time) > 5.0) or
                        (processed == len(files))
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
                        print(f"\033[2K\r{progress_str}", end='', file=sys.stderr, flush=True)
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
                                estimated_completion=estimated_completion
                            )

                            progress_callback(progress)
                        except Exception as e:
                            # Don't fail indexing if progress callback fails
                            diagnostics.debug(f"Progress callback failed: {e}")

                    last_report_time = current_time
        
        self.indexed_file_count = indexed_count
        self.last_index_time = time.time() - start_time
        
        with self.index_lock:
            class_count = len(self.class_index)
            function_count = len(self.function_index)


        # Print newline after progress to move to next line (only if using terminal progress)
        if is_terminal:
            print("", file=sys.stderr)
        diagnostics.info(f"Indexing complete in {self.last_index_time:.2f}s")
        diagnostics.info(f"Indexed {indexed_count}/{len(files)} files successfully ({cache_hits} from cache, {failed_count} failed)")
        diagnostics.info(f"Found {class_count} class names, {function_count} function names")

        if failed_count > 0:
            diagnostics.info(f"Note: {failed_count} files failed to parse - this is normal for complex projects")
        
        # Save overall cache and progress summary
        self._save_cache()
        self._save_progress_summary(indexed_count, len(files), cache_hits, failed_count)
        
        return indexed_count
    
    def _save_cache(self):
        """Save index to cache file"""
        # Get current config file info
        config_path = self.config.config_path
        config_mtime = config_path.stat().st_mtime if config_path and config_path.exists() else None

        # Get current compile_commands.json info
        cc_path = self.project_root / self.compile_commands_manager.compile_commands_path
        cc_mtime = cc_path.stat().st_mtime if cc_path.exists() else None

        self.cache_manager.save_cache(
            self.class_index,
            self.function_index,
            self.file_hashes,
            self.indexed_file_count,
            self.include_dependencies,
            config_file_path=config_path,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_path if cc_path.exists() else None,
            compile_commands_mtime=cc_mtime
        )
    
    def _load_cache(self) -> bool:
        """Load index from cache file"""
        # Get current config file info
        config_path = self.config.config_path
        config_mtime = config_path.stat().st_mtime if config_path and config_path.exists() else None

        # Get current compile_commands.json info
        cc_path = self.project_root / self.compile_commands_manager.compile_commands_path
        cc_mtime = cc_path.stat().st_mtime if cc_path.exists() else None

        cache_data = self.cache_manager.load_cache(
            self.include_dependencies,
            config_file_path=config_path,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_path if cc_path.exists() else None,
            compile_commands_mtime=cc_mtime
        )
        if not cache_data:
            self.cache_loaded = False
            return False
        
        try:
            # Load indexes
            self.class_index.clear()
            for name, infos in cache_data.get("class_index", {}).items():
                self.class_index[name] = [SymbolInfo(**info) for info in infos]

            self.function_index.clear()
            for name, infos in cache_data.get("function_index", {}).items():
                self.function_index[name] = [SymbolInfo(**info) for info in infos]

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

            diagnostics.debug(f"Loaded cache with {len(self.class_index)} classes, {len(self.function_index)} functions")
            self.cache_loaded = True
            return True

        except Exception as e:
            diagnostics.error(f"Error loading cache: {e}")
            self.cache_loaded = False
            return False
    
    def _save_progress_summary(self, indexed_count: int, total_files: int, cache_hits: int, failed_count: int = 0):
        """Save a summary of indexing progress"""
        status = "complete" if indexed_count + failed_count == total_files else "interrupted"
        self.cache_manager.save_progress(
            total_files,
            indexed_count,
            failed_count,
            cache_hits,
            self.last_index_time,
            len(self.class_index),
            len(self.function_index),
            status
        )
    
    def search_classes(self, pattern: str, project_only: bool = True) -> List[Dict[str, Any]]:
        """Search for classes matching pattern"""
        try:
            return self.search_engine.search_classes(pattern, project_only)
        except re.error as e:
            diagnostics.error(f"Invalid regex pattern: {e}")
            return []

    def search_functions(self, pattern: str, project_only: bool = True, class_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search for functions matching pattern, optionally within a specific class"""
        try:
            return self.search_engine.search_functions(pattern, project_only, class_name)
        except re.error as e:
            diagnostics.error(f"Invalid regex pattern: {e}")
            return []
    
    def get_stats(self) -> Dict[str, int]:
        """Get indexer statistics"""
        with self.index_lock:
            stats = {
                "class_count": len(self.class_index),
                "function_count": len(self.function_index),
                "file_count": self.indexed_file_count
            }
            
            # Add compile commands statistics if enabled
            if self.compile_commands_manager.enabled:
                compile_stats = self.compile_commands_manager.get_stats()
                stats.update({
                    "compile_commands_enabled": compile_stats['enabled'],
                    "compile_commands_count": compile_stats['compile_commands_count'],
                    "compile_commands_file_mapping_count": compile_stats['file_mapping_count']
                })
            
            return stats
    
    def get_compile_commands_stats(self) -> Dict[str, Any]:
        """Get compile commands statistics"""
        if not self.compile_commands_manager.enabled:
            return {"enabled": False}
        
        return self.compile_commands_manager.get_stats()
    
    def refresh_if_needed(self) -> int:
        """Refresh index for changed files and remove deleted files"""
        refreshed = 0
        deleted = 0

        # Refresh compile commands if needed
        if self.compile_commands_manager.enabled:
            compile_commands_refreshed = self.compile_commands_manager.refresh_if_needed()
            if compile_commands_refreshed:
                diagnostics.debug("Compile commands refreshed")

        # Get currently existing files
        current_files = set(self._find_cpp_files(self.include_dependencies))
        tracked_files = set(self.file_hashes.keys())
        
        # Find deleted files
        deleted_files = tracked_files - current_files
        
        # Remove deleted files from all indexes
        for file_path in deleted_files:
            self._remove_file_from_indexes(file_path)
            # Remove from tracking
            if file_path in self.file_hashes:
                del self.file_hashes[file_path]
            if file_path in self.translation_units:
                del self.translation_units[file_path]
            # Clean up per-file cache
            self.cache_manager.remove_file_cache(file_path)
            deleted += 1
        
        # Check existing tracked files for modifications
        for file_path in list(self.file_hashes.keys()):
            if not os.path.exists(file_path):
                continue  # Skip files that no longer exist (should have been caught above)
                
            current_hash = self._get_file_hash(file_path)
            if current_hash != self.file_hashes.get(file_path):
                success, _ = self.index_file(file_path, force=True)
                if success:
                    refreshed += 1
        
        # Check for new files
        new_files = current_files - tracked_files
        for file_path in new_files:
            success, _ = self.index_file(file_path, force=False)
            if success:
                refreshed += 1
        
        if refreshed > 0 or deleted > 0:
            self._save_cache()
            if deleted > 0:
                diagnostics.info(f"Removed {deleted} deleted files from indexes")

        # Keep tracked file count in sync with current state
        self.indexed_file_count = len(self.file_hashes)

        return refreshed
    
    def _remove_file_from_indexes(self, file_path: str):
        """Remove all symbols from a deleted file from all indexes"""
        with self.index_lock:
            # Get all symbols that were in this file
            symbols_to_remove = self.file_index.get(file_path, [])
            
            # Remove from class_index
            for symbol in symbols_to_remove:
                if symbol.kind in ("class", "struct"):
                    if symbol.name in self.class_index:
                        self.class_index[symbol.name] = [
                            info for info in self.class_index[symbol.name] 
                            if info.file != file_path
                        ]
                        # Remove empty entries
                        if not self.class_index[symbol.name]:
                            del self.class_index[symbol.name]
                
                # Remove from function_index
                elif symbol.kind in ("function", "method"):
                    if symbol.name in self.function_index:
                        self.function_index[symbol.name] = [
                            info for info in self.function_index[symbol.name] 
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
    
    def get_function_signature(self, function_name: str, class_name: Optional[str] = None) -> List[str]:
        """Get signature details for functions with given name, optionally within a specific class"""
        return self.search_engine.get_function_signature(function_name, class_name)
    
    def search_symbols(self, pattern: str, project_only: bool = True, symbol_types: Optional[List[str]] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Search for all symbols (classes and functions) matching pattern.

        Args:
            pattern: Regex pattern to search for
            project_only: Only include project files (exclude dependencies)
            symbol_types: List of symbol types to include. Options: ['class', 'struct', 'function', 'method']
                         If None, includes all types.

        Returns:
            Dictionary with keys 'classes' and 'functions' containing matching symbols
        """
        try:
            return self.search_engine.search_symbols(pattern, project_only, symbol_types)
        except re.error as e:
            diagnostics.error(f"Invalid regex pattern: {e}")
            return {"classes": [], "functions": []}
    
    def get_derived_classes(self, class_name: str, project_only: bool = True) -> List[Dict[str, Any]]:
        """
        Get all classes that derive from the given class.
        
        Args:
            class_name: Name of the base class
            project_only: Only include project classes (exclude dependencies)
        
        Returns:
            List of classes that inherit from the given class
        """
        derived_classes = []
        
        with self.index_lock:
            for name, infos in self.class_index.items():
                for info in infos:
                    if not project_only or info.is_project:
                        # Check if this class inherits from the target class
                        if class_name in info.base_classes:
                            derived_classes.append({
                                "name": info.name,
                                "kind": info.kind,
                                "file": info.file,
                                "line": info.line,
                                "column": info.column,
                                "is_project": info.is_project,
                                "base_classes": info.base_classes
                            })
        
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
        base_classes = []
        with self.index_lock:
            for infos in self.class_index.get(class_name, []):
                base_classes.extend(infos.base_classes)
        
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
            "derived_hierarchy": self._get_derived_hierarchy(class_name)
        }

        return hierarchy
    
    def _get_base_hierarchy(self, class_name: str, visited: Optional[Set[str]] = None) -> Dict[str, Any]:
        """Recursively get base class hierarchy"""
        if visited is None:
            visited = set()
        
        if class_name in visited:
            return {"name": class_name, "circular_reference": True}
        
        visited.add(class_name)
        
        # Get base classes for this class
        base_classes = []
        with self.index_lock:
            for infos in self.class_index.get(class_name, []):
                base_classes.extend(infos.base_classes)
        
        base_classes = list(set(base_classes))
        
        # Recursively get hierarchy for each base class
        base_hierarchies = []
        for base in base_classes:
            base_hierarchies.append(self._get_base_hierarchy(base, visited.copy()))
        
        return {
            "name": class_name,
            "base_classes": base_hierarchies
        }
    
    def _get_derived_hierarchy(self, class_name: str, visited: Optional[Set[str]] = None) -> Dict[str, Any]:
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
        
        return {
            "name": class_name,
            "derived_classes": derived_hierarchies
        }
    
    def find_callers(self, function_name: str, class_name: str = "") -> List[Dict[str, Any]]:
        """Find all functions that call the specified function"""
        results = []
        
        # Find the target function(s)
        target_functions = self.search_functions(f"^{re.escape(function_name)}$", 
                                               project_only=False, 
                                               class_name=class_name)
        
        # Collect USRs of target functions
        target_usrs = set()
        for func in target_functions:
            # Find the full symbol info with USR
            for symbol in self.function_index.get(func['name'], []):
                if symbol.usr and symbol.file == func['file'] and symbol.line == func['line']:
                    target_usrs.add(symbol.usr)
        
        # Find all callers
        for usr in target_usrs:
            callers = self.call_graph_analyzer.find_callers(usr)
            for caller_usr in callers:
                if caller_usr in self.usr_index:
                    caller_info = self.usr_index[caller_usr]
                    results.append({
                        "name": caller_info.name,
                        "kind": caller_info.kind,
                        "file": caller_info.file,
                        "line": caller_info.line,
                        "column": caller_info.column,
                        "signature": caller_info.signature,
                        "parent_class": caller_info.parent_class,
                        "is_project": caller_info.is_project
                    })
        
        return results
    
    def find_callees(self, function_name: str, class_name: str = "") -> List[Dict[str, Any]]:
        """Find all functions called by the specified function"""
        results = []
        
        # Find the target function(s)
        target_functions = self.search_functions(f"^{re.escape(function_name)}$", 
                                               project_only=False, 
                                               class_name=class_name)
        
        # Collect USRs of target functions
        target_usrs = set()
        for func in target_functions:
            # Find the full symbol info with USR
            for symbol in self.function_index.get(func['name'], []):
                if symbol.usr and symbol.file == func['file'] and symbol.line == func['line']:
                    target_usrs.add(symbol.usr)
        
        # Find all callees
        for usr in target_usrs:
            callees = self.call_graph_analyzer.find_callees(usr)
            for callee_usr in callees:
                if callee_usr in self.usr_index:
                    callee_info = self.usr_index[callee_usr]
                    results.append({
                        "name": callee_info.name,
                        "kind": callee_info.kind,
                        "file": callee_info.file,
                        "line": callee_info.line,
                        "column": callee_info.column,
                        "signature": callee_info.signature,
                        "parent_class": callee_info.parent_class,
                        "is_project": callee_info.is_project
                    })
        
        return results
    
    def get_call_path(self, from_function: str, to_function: str, max_depth: int = 10) -> List[List[str]]:
        """Find call paths from one function to another using BFS"""
        # Find source and target USRs
        from_funcs = self.search_functions(f"^{re.escape(from_function)}$", project_only=False)
        to_funcs = self.search_functions(f"^{re.escape(to_function)}$", project_only=False)
        
        if not from_funcs or not to_funcs:
            return []
        
        # Get USRs
        from_usrs = set()
        for func in from_funcs:
            for symbol in self.function_index.get(func['name'], []):
                if symbol.usr and symbol.file == func['file'] and symbol.line == func['line']:
                    from_usrs.add(symbol.usr)
        
        to_usrs = set()
        for func in to_funcs:
            for symbol in self.function_index.get(func['name'], []):
                if symbol.usr and symbol.file == func['file'] and symbol.line == func['line']:
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
                                name_path.append(f"{info.parent_class}::{info.name}" if info.parent_class else info.name)
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
    
    def find_in_file(self, file_path: str, pattern: str) -> List[Dict[str, Any]]:
        """Search for symbols within a specific file"""
        results = []
        
        # Search in both class and function results
        all_classes = self.search_classes(pattern, project_only=False)
        all_functions = self.search_functions(pattern, project_only=False)
        
        # Filter by file path
        abs_file_path = str(Path(file_path).resolve())
        
        for item in all_classes + all_functions:
            item_file = str(Path(item['file']).resolve()) if item['file'] else ""
            if item_file == abs_file_path or item['file'].endswith(file_path):
                results.append(item)

        return results

    def get_parse_errors(self, limit: Optional[int] = None,
                        file_path_filter: Optional[str] = None) -> List[Dict[str, Any]]:
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
