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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple
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

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics

try:
    import clang.cindex
    from clang.cindex import Index, CursorKind, TranslationUnit, Config
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
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self.index = Index.create()
        
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
        
        # Threading
        self.index_lock = threading.Lock()
        self._thread_local = threading.local()
        cpu_count = os.cpu_count() or 1
        self.max_workers = max(1, min(16, cpu_count * 2))
        
        # Initialize cache manager and file scanner with config
        self.cache_manager = CacheManager(self.project_root)
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

        # Initialize compile commands manager with config
        compile_commands_config = self.config.get_compile_commands_config()
        self.compile_commands_manager = CompileCommandsManager(self.project_root, compile_commands_config)

        diagnostics.info(f"CppAnalyzer initialized for project: {self.project_root}")

        # Print compile commands configuration status
        if self.compile_commands_manager.enabled:
            cc_path = self.project_root / compile_commands_config['compile_commands_path']
            if cc_path.exists():
                # This message will be followed by actual load message from CompileCommandsManager
                diagnostics.info(f"Compile commands enabled: using {compile_commands_config['compile_commands_path']}")
            else:
                diagnostics.info(f"Compile commands enabled: {compile_commands_config['compile_commands_path']} not found, will use fallback args")
        else:
            diagnostics.info("Compile commands disabled in configuration")
    
    def _get_file_hash(self, file_path: str) -> str:
        """Get hash of file contents for change detection"""
        return self.cache_manager.get_file_hash(file_path)

    def _get_thread_index(self) -> Index:
        """Return a thread-local libclang Index instance."""
        index = getattr(self._thread_local, "index", None)
        if index is None:
            index = Index.create()
            self._thread_local.index = index
        return index

    def _compute_compile_args_hash(self, args: List[str]) -> str:
        """Compute hash of compilation arguments for cache validation"""
        # Sort and join args to create a consistent hash
        args_str = " ".join(sorted(args))
        return hashlib.md5(args_str.encode()).hexdigest()

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
        """Find all C++ files in the project"""
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
    
    def _process_cursor(self, cursor, file_filter: Optional[str] = None, parent_class: str = "", parent_function_usr: str = ""):
        """Process a cursor and its children"""
        # Skip if in different file than we're indexing
        if cursor.location.file and file_filter:
            if cursor.location.file.name != file_filter:
                return
        
        kind = cursor.kind
        
        # Process classes and structs
        if kind in (CursorKind.CLASS_DECL, CursorKind.STRUCT_DECL):
            if cursor.spelling:
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
                
                with self.index_lock:
                    self.class_index[info.name].append(info)
                    if info.usr:
                        self.usr_index[info.usr] = info
                    if info.file:
                        # Ensure file_index list exists
                        if info.file not in self.file_index:
                            self.file_index[info.file] = []
                        self.file_index[info.file].append(info)
                
                # Process children of this class with the class as parent
                for child in cursor.get_children():
                    self._process_cursor(child, file_filter, cursor.spelling)
                return  # Don't process children again below
        
        # Process functions and methods
        elif kind in (CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD):
            if cursor.spelling:
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
                
                with self.index_lock:
                    self.function_index[info.name].append(info)
                    if info.usr:
                        self.usr_index[info.usr] = info
                    if info.file:
                        # Ensure file_index list exists
                        if info.file not in self.file_index:
                            self.file_index[info.file] = []
                        self.file_index[info.file].append(info)
                
                # Process function body to find calls
                for child in cursor.get_children():
                    self._process_cursor(child, file_filter, parent_class, function_usr)
                return  # Don't process children again below
        
        # Process function calls within function bodies
        elif kind == CursorKind.CALL_EXPR and parent_function_usr:
            # This is a function call inside a function
            referenced = cursor.referenced
            if referenced and referenced.get_usr():
                called_usr = referenced.get_usr()
                # Track the call relationship
                with self.index_lock:
                    self.call_graph_analyzer.add_call(parent_function_usr, called_usr)
        
        # Recurse into children (with current parent_class and parent_function context)
        for child in cursor.get_children():
            self._process_cursor(child, file_filter, parent_class, parent_function_usr)
    
    def index_file(self, file_path: str, force: bool = False) -> tuple[bool, bool]:
        """Index a single C++ file

        Returns:
            (success, was_cached) - success indicates if indexing succeeded,
                                   was_cached indicates if it was loaded from cache
        """
        file_path = os.path.abspath(file_path)
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
                        diagnostics.info(
                            f"Retrying {file_path} (attempt {retry_count + 1}/{self.max_parse_retries + 1}, "
                            f"last error: {cache_data['error_message']})"
                        )
                        # Continue to parsing below (will increment retry_count on failure)
                else:
                    # Successfully cached - load symbols
                    cached_symbols = cache_data['symbols']

                    # Apply cached symbols to indexes
                    with self.index_lock:
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
                        for symbol in cached_symbols:
                            if symbol.kind in ("class", "struct"):
                                self.class_index[symbol.name].append(symbol)
                            else:
                                self.function_index[symbol.name].append(symbol)

                            # Also update USR index
                            if symbol.usr:
                                self.usr_index[symbol.usr] = symbol

                            # Restore call graph relationships
                            if symbol.calls:
                                for called_usr in symbol.calls:
                                    self.call_graph_analyzer.add_call(symbol.usr, called_usr)
                            if symbol.called_by:
                                for caller_usr in symbol.called_by:
                                    self.call_graph_analyzer.add_call(caller_usr, symbol.usr)
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
            tu = index.parse(
                file_path, 
                args=args,
                options=TranslationUnit.PARSE_INCOMPLETE |
                       TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
            )


            if not tu:
                diagnostics.error(f"Failed to parse {file_path}")
                return False
            
            # Don't print diagnostics - too noisy for universal analyzer
            # Just continue processing what we can parse
            
            # Clear old entries for this file
            with self.index_lock:
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
            
            # Process the translation unit (modifies indexes)
            self._process_cursor(tu.cursor, file_path)
            
            # Get the symbols we just added for this file
            with self.index_lock:
                if file_path in self.file_index:
                    collected_symbols = self.file_index[file_path].copy()
                    
                    # Populate call graph info in symbols before caching
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
            
            # Save to per-file cache (mark as successfully parsed)
            self._save_file_cache(
                file_path, collected_symbols, current_hash, compile_args_hash,
                success=True, error_message=None, retry_count=0
            )

            # Update tracking
            with self.index_lock:
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

    def index_project(self, force: bool = False, include_dependencies: bool = True) -> int:
        """Index all C++ files in the project"""
        start_time = time.time()

        # Store the include_dependencies setting BEFORE loading cache
        self.include_dependencies = include_dependencies

        # Try to load from cache if not forcing
        if not force and self._load_cache():
            refreshed = self.refresh_if_needed()
            if refreshed > 0:
                diagnostics.info(f"Using cached index (updated {refreshed} files)")
            else:
                diagnostics.info("Using cached index")
            return self.indexed_file_count

        diagnostics.info(f"Finding C++ files (include_dependencies={include_dependencies})...")
        files = self._find_cpp_files(include_dependencies=include_dependencies)

        if not files:
            diagnostics.warning("No C++ files found in project")
            return 0

        diagnostics.info(f"Found {len(files)} C++ files to index")
        
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
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_file = {
                executor.submit(self.index_file, os.path.abspath(file_path), force): os.path.abspath(file_path)
                for file_path in files
            }

            for i, future in enumerate(as_completed(future_to_file)):
                file_path = future_to_file[future]
                try:
                    success, was_cached = future.result()
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
            return True

        except Exception as e:
            diagnostics.error(f"Error loading cache: {e}")
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
                diagnostics.info("Compile commands refreshed")

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
            - class_info: Information about the class itself
            - base_classes: Direct base classes
            - derived_classes: Direct derived classes
            - full_hierarchy: Complete hierarchy tree (recursive)
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
