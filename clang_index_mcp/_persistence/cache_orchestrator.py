"""
Cache orchestration and header tracking management.

Extracted from CppAnalyzer as part of architecture refactoring.
Manages cache loading/saving, file caching, header tracking, and progress summaries.
"""

import json
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from .._core import diagnostics
from .._persistence.cache_validation_context import CacheValidationContext
from .._persistence.header_tracker import HeaderProcessingTracker

if TYPE_CHECKING:
    from .._compilation.compilation_environment import CompilationEnvironment
    from .._persistence.cache_manager import CacheManager
    from .._search.call_graph_service import CallGraphService
    from .._symbols.symbol_index_store import SymbolIndexStore
    from ..cpp_analyzer_config import CppAnalyzerConfig
    from pathlib import Path


class CacheOrchestrator:
    """Manages cache operations and header tracking state."""

    def __init__(
        self,
        cache_manager: "CacheManager",
        config: "CppAnalyzerConfig",
        project_root: "Path",
        symbol_store: "SymbolIndexStore",
        compilation_env: "CompilationEnvironment",
        call_graph_service: "CallGraphService",
    ):
        """
        Initialize cache orchestrator.

        Args:
            cache_manager: SQLite-backed cache and persistence.
            config: Project configuration.
            project_root: Project root directory.
            symbol_store: In-memory symbol indexes.
            compilation_env: Compilation environment for file scanning.
            call_graph_service: Call graph and dependency tracking.
        """
        self.cache_manager = cache_manager
        self.config = config
        self.project_root = project_root
        self.cache_dir = cache_manager.cache_dir
        self.symbol_store = symbol_store
        self.compilation_env = compilation_env
        self.call_graph_service = call_graph_service

        self.cache_loaded = False
        self.last_index_time = 0.0
        self.compile_commands_hash = ""
        self.header_tracker = HeaderProcessingTracker()

    # ------------------------------------------------------------------
    # Header tracker facade
    # ------------------------------------------------------------------
    def try_claim_header(self, header_path: str, current_file_hash: str) -> bool:
        """Try to claim a header for processing (first-win strategy)."""
        return self.header_tracker.try_claim_header(header_path, current_file_hash)

    def mark_header_completed(self, header_path: str, file_hash: str) -> None:
        """Mark a header as fully processed."""
        self.header_tracker.mark_completed(header_path, file_hash)

    def invalidate_header(self, header_path: str) -> None:
        """Invalidate a header, forcing re-processing on next access."""
        self.header_tracker.invalidate_header(header_path)

    def clear_header_tracker(self) -> None:
        """Clear all header tracking state."""
        self.header_tracker.clear_all()

    def is_header_processed(self, header_path: str, file_hash: str) -> bool:
        """Check if a header has been processed with the given hash."""
        return self.header_tracker.is_processed(header_path, file_hash)

    def get_processed_header_count(self) -> int:
        """Return the number of headers currently tracked as processed."""
        return self.header_tracker.get_processed_count()

    def get_processed_headers(self) -> Dict[str, str]:
        """Return a snapshot of all processed headers and their file hashes."""
        return self.header_tracker.get_processed_headers()

    def restore_processed_headers(self, processed_headers: Dict[str, str]) -> None:
        """Restore processed headers from a previously saved snapshot."""
        self.header_tracker.restore_processed_headers(processed_headers)

    def remove_deleted_file(self, file_path: str) -> None:
        """
        Remove a deleted file from all indexes, cache, dependency graph, and header tracker.

        This is the single coordination point for deleted-file cleanup.
        """
        self._remove_deleted_file_from_indexes(file_path)
        self._remove_deleted_file_from_cache(file_path)
        self._remove_deleted_file_from_dependency_graph(file_path)
        self._remove_deleted_file_from_header_tracker(file_path)

    def _remove_deleted_file_from_indexes(self, file_path: str) -> None:
        """Remove a deleted file from the in-memory symbol indexes."""
        try:
            self.symbol_store.remove_file(file_path)
        except Exception as e:
            diagnostics.warning(f"Failed to remove {file_path} from indexes: {e}")

    def _remove_deleted_file_from_cache(self, file_path: str) -> None:
        """Remove a deleted file from the persistent cache."""
        try:
            self.cache_manager.remove_file_cache(file_path)
        except Exception as e:
            diagnostics.warning(f"Failed to remove {file_path} from cache: {e}")

    def _remove_deleted_file_from_dependency_graph(self, file_path: str) -> None:
        """Remove a deleted file from the dependency graph."""
        if not self.call_graph_service.dependency_graph:
            return
        try:
            self.call_graph_service.dependency_graph.remove_file_dependencies(file_path)
        except Exception as e:
            diagnostics.warning(f"Failed to remove {file_path} from dependency graph: {e}")

    def _remove_deleted_file_from_header_tracker(self, file_path: str) -> None:
        """Remove a deleted header from the header tracker."""
        from .._core.file_scanner import FileScanner

        if not file_path.endswith(tuple(FileScanner.HEADER_EXTENSIONS)):
            return
        try:
            self.invalidate_header(file_path)
        except Exception as e:
            diagnostics.warning(f"Failed to remove {file_path} from header tracker: {e}")

    def get_file_hash(self, file_path: str) -> str:
        """Get hash of file contents for change detection"""
        return self.cache_manager.get_file_hash(file_path)

    def calculate_compile_commands_hash(self):
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
        if not self.compilation_env.has_active_compile_commands():
            self.compile_commands_hash = ""
            return

        assert self.compilation_env.compile_commands_manager is not None
        self.compile_commands_hash = (
            self.compilation_env.compile_commands_manager.get_compile_commands_hash()
        )

    def restore_or_reset_header_tracking(self):
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
        from .._core import diagnostics

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
                self.restore_processed_headers(processed_headers)
                diagnostics.debug(f"Restored {len(processed_headers)} processed headers from cache")
            else:
                # Hash mismatch - compile_commands.json changed
                diagnostics.debug("compile_commands.json changed - resetting header tracking")
                self.clear_header_tracker()

        except (json.JSONDecodeError, IOError, OSError) as e:
            # JSON corruption or file access errors - this can happen with concurrent writes
            # in multi-process mode. Simply start fresh.
            diagnostics.debug(
                f"Header tracking cache corrupted or inaccessible, starting fresh: {e}"
            )
            # Remove corrupted cache file
            try:
                tracker_cache_path.unlink(missing_ok=True)
            except Exception:
                pass
            # Start fresh
            self.clear_header_tracker()
        except Exception as e:
            diagnostics.warning(f"Unexpected error restoring header tracking from cache: {e}")
            # On error, start fresh
            self.clear_header_tracker()

    def save_header_tracking(self):
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
        from .._core import diagnostics

        tracker_cache_path = self.cache_dir / "header_tracker.json"

        try:
            # Get current processed headers from tracker
            processed_headers = self.get_processed_headers()

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

    def save_file_cache(
        self,
        file_path: str,
        symbols: List[Any],
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

    def load_file_cache(
        self, file_path: str, current_hash: str, compile_args_hash: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Load cached data for a file if still valid

        Returns:
            Dict with 'symbols', 'success', 'error_message', 'retry_count' or None
        """
        return self.cache_manager.load_file_cache(file_path, current_hash, compile_args_hash)

    def try_load_cached_index(
        self, file_path: str, current_hash: str, compile_args_hash: str, force: bool
    ) -> Optional[Tuple[bool, bool]]:
        """Try to load index from per-file cache. Returns result tuple or None if not cached."""
        from .._core import diagnostics

        if force:
            return None

        cache_data = self.load_file_cache(file_path, current_hash, compile_args_hash)
        if cache_data is None:
            return None

        if not cache_data["success"]:
            retry_count = cache_data["retry_count"]
            if retry_count >= self.compilation_env.max_parse_retries:
                diagnostics.debug(
                    f"Skipping {file_path} - failed {retry_count} times "
                    f"(last error: {cache_data['error_message']})"
                )
                return (False, True)
            return None

        self.symbol_store.apply_cached_symbols(file_path, cache_data["symbols"], current_hash)
        return (True, True)

    def handle_cache_initial_index(
        self,
        force: bool,
        refresh_fn: Optional[Callable[[bool], int]] = None,
    ) -> Optional[int]:
        """Try to load from cache if not forcing.

        Args:
            force: If True, skip cache loading.
            refresh_fn: Optional callable that performs incremental refresh.
                       Accepts include_dependencies flag, returns number of refreshed files.
        """
        from .._core import diagnostics

        if not force and self.load_cache():
            if refresh_fn is not None:
                refreshed = refresh_fn(self.compilation_env.include_dependencies)
                if refreshed > 0:
                    diagnostics.debug(f"Using cached index (updated {refreshed} files)")
                else:
                    diagnostics.debug("Using cached index")
            else:
                diagnostics.debug("Using cached index")
            return int(self.symbol_store.indexed_file_count)  # type: ignore[no-any-return]
        return None

    def save_cache(self):
        """Save index to cache file"""
        # Get current config file info
        config_path = self.config.config_path
        config_mtime = config_path.stat().st_mtime if config_path and config_path.exists() else None

        # Get current compile_commands.json info
        # Task 3.2: Skip if CompileCommandsManager not initialized (worker mode)
        if self.compilation_env.compile_commands_manager is not None:
            cc_path = (
                self.project_root
                / self.compilation_env.compile_commands_manager.compile_commands_path
            )
            cc_mtime = cc_path.stat().st_mtime if cc_path.exists() else None
        else:
            cc_path = None
            cc_mtime = None

        validation_context = CacheValidationContext(
            config_file_path=config_path,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_path if cc_path and cc_path.exists() else None,
            compile_commands_mtime=cc_mtime,
        )
        self.cache_manager.save_cache(
            self.symbol_store.class_index,
            self.symbol_store.function_index,
            self.symbol_store.file_hashes,
            self.symbol_store.indexed_file_count,
            self.compilation_env.include_dependencies,
            validation_context=validation_context,
        )

    def load_cache(self) -> bool:
        """Load index from cache file"""
        # Get current config file info
        config_path = self.config.config_path
        config_mtime = config_path.stat().st_mtime if config_path and config_path.exists() else None

        # Get current compile_commands.json info
        # Task 3.2: Skip if CompileCommandsManager not initialized (worker mode)
        if self.compilation_env.compile_commands_manager is not None:
            cc_path = (
                self.project_root
                / self.compilation_env.compile_commands_manager.compile_commands_path
            )
            cc_mtime = cc_path.stat().st_mtime if cc_path.exists() else None
        else:
            cc_path = None
            cc_mtime = None

        validation_context = CacheValidationContext(
            config_file_path=config_path,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_path if cc_path and cc_path.exists() else None,
            compile_commands_mtime=cc_mtime,
        )
        cache_data = self.cache_manager.load_cache(
            self.compilation_env.include_dependencies,
            validation_context=validation_context,
        )
        if not cache_data:
            self.cache_loaded = False
            return False

        try:
            self.symbol_store.populate_indexes_from_cache(cache_data)
            self.symbol_store.rebuild_auxiliary_structures()

            # Memory optimization: call sites are now loaded LAZILY on-demand
            # instead of loading all at startup (saves ~150-200 MB for large projects)
            # The call_graph_analyzer.cache_backend handles lazy loading via SQLite queries

            diagnostics.debug(
                f"Loaded cache with {self.symbol_store.class_name_count()} classes, "
                f"{self.symbol_store.function_name_count()} functions"
            )
            self.cache_loaded = True
            return True

        except Exception as e:
            diagnostics.error(f"Error loading cache: {e}")
            self.cache_loaded = False
            return False

    def save_progress_summary(
        self, indexed_count: int, total_files: int, cache_hits: int, failed_count: int = 0
    ):
        """Save a summary of indexing progress"""
        status = "complete" if indexed_count + failed_count == total_files else "interrupted"
        # Count total symbols (not just unique names)
        class_count = self.symbol_store.total_class_symbols()
        function_count = self.symbol_store.total_function_symbols()

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
