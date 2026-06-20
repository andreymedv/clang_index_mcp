"""
Cache orchestration and header tracking management.

Extracted from CppAnalyzer as part of architecture refactoring.
Manages cache loading/saving, file caching, header tracking, and progress summaries.
"""

import hashlib
import json
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from .header_tracker import HeaderProcessingTracker

if TYPE_CHECKING:
    from .project_context import ProjectContext


class CacheOrchestrator:
    """Manages cache operations and header tracking state."""

    def __init__(self, context: "ProjectContext"):
        """
        Initialize cache orchestrator.

        Args:
            context: Shared project context with cache, config, and symbol services.
        """
        self.context = context
        assert context.cache_manager is not None
        self.cache_manager = context.cache_manager
        assert context.config is not None
        self.config = context.config
        assert context.project_root is not None
        self.project_root = context.project_root
        self.cache_dir = context.cache_manager.cache_dir
        assert context.symbol_store is not None
        self.symbol_store = context.symbol_store
        assert context.compilation_env is not None
        self.compilation_env = context.compilation_env
        assert context.call_graph_service is not None
        self.call_graph_service = context.call_graph_service

        self.cache_loaded = False
        self.last_index_time = 0.0
        self.compile_commands_hash = ""
        self.header_tracker = HeaderProcessingTracker()

    def _get_file_hash(self, file_path: str) -> str:
        """Get hash of file contents for change detection"""
        return self.cache_manager.get_file_hash(file_path)

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
        from . import diagnostics

        # Task 3.2: Skip if CompileCommandsManager not initialized (worker mode)
        if not self.compilation_env.has_active_compile_commands():
            self.compile_commands_hash = ""
            return

        # Get compile_commands.json path from configuration
        compile_commands_config = self.config.get_compile_commands_config()
        cc_path = self.project_root / compile_commands_config.compile_commands_path

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
        from . import diagnostics

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
            except Exception:
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
        from . import diagnostics

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

    def _save_file_cache(
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

    def _load_file_cache(
        self, file_path: str, current_hash: str, compile_args_hash: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Load cached data for a file if still valid

        Returns:
            Dict with 'symbols', 'success', 'error_message', 'retry_count' or None
        """
        return self.cache_manager.load_file_cache(file_path, current_hash, compile_args_hash)

    def _try_load_cached_index(
        self, file_path: str, current_hash: str, compile_args_hash: str, force: bool
    ) -> Optional[Tuple[bool, bool]]:
        """Try to load index from per-file cache. Returns result tuple or None if not cached."""
        from . import diagnostics

        if force:
            return None

        cache_data = self._load_file_cache(file_path, current_hash, compile_args_hash)
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

        self.symbol_store._apply_cached_symbols(file_path, cache_data["symbols"], current_hash)
        return (True, True)

    def _handle_cache_initial_index(self, force: bool) -> Optional[int]:
        """Try to load from cache if not forcing."""
        from . import diagnostics

        if not force and self._load_cache():
            assert self.context.refresh_pipeline is not None
            refreshed = self.context.refresh_pipeline.refresh_if_needed(
                include_dependencies=self.compilation_env.include_dependencies,
            )
            if refreshed > 0:
                diagnostics.debug(f"Using cached index (updated {refreshed} files)")
            else:
                diagnostics.debug("Using cached index")
            return int(self.symbol_store.indexed_file_count)  # type: ignore[no-any-return]
        return None

    def _save_cache(self):
        """Save index to cache file"""
        from . import diagnostics

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

        self.cache_manager.save_cache(
            self.symbol_store.class_index,
            self.symbol_store.function_index,
            self.symbol_store.file_hashes,
            self.symbol_store.indexed_file_count,
            self.compilation_env.include_dependencies,
            config_file_path=config_path,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_path if cc_path and cc_path.exists() else None,
            compile_commands_mtime=cc_mtime,
        )

        # Phase 3/4: Save call sites to database
        # In ProcessPoolExecutor mode (default): call_sites are already streamed to SQLite
        # as they arrive from workers (Phase 4 optimization), so this set is empty.
        # In ThreadPoolExecutor mode: call_sites are accumulated in memory, so we need
        # to save them here. This is still needed for backwards compatibility.
        call_sites = self.call_graph_service.call_graph_analyzer.get_all_call_sites()
        if call_sites:
            diagnostics.debug(
                f"Saving {len(call_sites)} call sites to database (ThreadPoolExecutor mode)"
            )
            saved_count = self.cache_manager.backend.save_call_sites_batch(call_sites)
            if saved_count != len(call_sites):
                diagnostics.warning(f"Only saved {saved_count}/{len(call_sites)} call sites")

    def _load_cache(self) -> bool:
        """Load index from cache file"""
        from . import diagnostics

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

        cache_data = self.cache_manager.load_cache(
            self.compilation_env.include_dependencies,
            config_file_path=config_path,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_path if cc_path and cc_path.exists() else None,
            compile_commands_mtime=cc_mtime,
        )
        if not cache_data:
            self.cache_loaded = False
            return False

        try:
            self.symbol_store._populate_indexes_from_cache(cache_data)
            self.symbol_store._rebuild_auxiliary_structures()

            # Memory optimization: call sites are now loaded LAZILY on-demand
            # instead of loading all at startup (saves ~150-200 MB for large projects)
            # The call_graph_analyzer.cache_backend handles lazy loading via SQLite queries

            diagnostics.debug(
                f"Loaded cache with {len(self.symbol_store.class_index)} classes, "
                f"{len(self.symbol_store.function_index)} functions"
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
        class_count = sum(len(infos) for infos in self.symbol_store.class_index.values())
        function_count = sum(len(infos) for infos in self.symbol_store.function_index.values())

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
