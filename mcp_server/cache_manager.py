"""Cache management for C++ analyzer."""

import json
import hashlib
import time
import os
import sys
import traceback
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from collections import defaultdict
from .symbol_info import SymbolInfo
from .cache_backend import CacheBackend
from .error_tracking import ErrorTracker, RecoveryManager
from .project_identity import ProjectIdentity

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics


class CacheManager:
    """Manages caching for the C++ analyzer with pluggable backends."""

    def __init__(
        self,
        project_root_or_identity: Union[Path, ProjectIdentity],
        skip_schema_recreation: bool = False,
    ):
        """
        Initialize CacheManager with project identity.

        Args:
            project_root_or_identity: Either a Path (backward compatibility) or ProjectIdentity
            skip_schema_recreation: If True, skip database recreation on schema mismatch.
                                   Used by worker processes to avoid race conditions.

        Backward Compatibility:
            Accepts Path for backward compatibility, automatically creates ProjectIdentity
            with no config file.
        """
        # Handle both Path and ProjectIdentity for backward compatibility
        if isinstance(project_root_or_identity, ProjectIdentity):
            self.project_identity = project_root_or_identity
            self.project_root = project_root_or_identity.source_directory
        else:
            # Backward compatibility: Path provided
            self.project_root = Path(project_root_or_identity)
            self.project_identity = ProjectIdentity(self.project_root, None)

        self._skip_schema_recreation = skip_schema_recreation
        self.cache_dir = self._get_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.error_log_path = self.cache_dir / "parse_errors.jsonl"

        # Initialize error tracking
        self.error_tracker = ErrorTracker(
            window_seconds=300.0,  # 5 minute window
            fallback_threshold=0.05,  # 5% error rate triggers fallback
        )

        # Initialize recovery manager
        self.recovery_manager = RecoveryManager()

        # Initialize SQLite cache backend
        self.backend = self._create_backend()

    def _get_cache_dir(self) -> Path:
        """
        Get the cache directory for this project.

        Uses ProjectIdentity to create unique cache directory based on:
        - Source directory path
        - Configuration file path (if provided)

        Returns:
            Path to cache directory
        """
        # Use the MCP server directory for cache, not the project being analyzed
        mcp_server_root = Path(
            __file__
        ).parent.parent  # Go up from mcp_server/cache_manager.py to root
        cache_base = mcp_server_root / ".mcp_cache"

        # Use ProjectIdentity to get unique cache directory name
        cache_dir_name = self.project_identity.get_cache_directory_name()
        cache_dir = cache_base / cache_dir_name

        return cache_dir

    def cache_exists(self) -> bool:
        """
        Check if cache directory exists for this project.

        Returns:
            True if cache directory exists, False otherwise
        """
        return self.cache_dir.exists()

    def _create_backend(self) -> CacheBackend:
        """
        Create SQLite cache backend.

        Returns:
            SqliteCacheBackend instance

        Raises:
            Exception if SQLite backend initialization fails
        """
        from .sqlite_cache_backend import SqliteCacheBackend

        db_path = self.cache_dir / "symbols.db"
        backend = SqliteCacheBackend(db_path, skip_schema_recreation=self._skip_schema_recreation)
        diagnostics.debug(f"Using SQLite cache backend: {db_path}")
        return backend

    def ensure_schema_current(self) -> bool:
        """
        Ensure database schema is current before spawning workers.

        This should be called by main process BEFORE creating ProcessPoolExecutor
        to prevent race conditions where multiple workers detect schema mismatch
        and try to recreate the database simultaneously.

        Returns:
            True if schema was recreated, False if it was already current.
        """
        from .sqlite_cache_backend import SqliteCacheBackend

        if isinstance(self.backend, SqliteCacheBackend):
            return self.backend.ensure_schema_current()
        return False

    def close(self):
        """
        Close the cache manager and release all resources.

        This should be called when the CacheManager is no longer needed
        to properly close the SQLite connection and avoid resource leaks.
        """
        if hasattr(self, "backend") and self.backend is not None:
            from .sqlite_cache_backend import SqliteCacheBackend

            if isinstance(self.backend, SqliteCacheBackend):
                self.backend._close()

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

    def _handle_backend_error(self, error: Exception, operation: str) -> bool:
        """
        Handle backend errors with tracking and recovery logic.

        Args:
            error: Exception that occurred
            operation: Operation that failed

        Returns:
            True if recovery was attempted, False otherwise
        """
        # Classify error type
        error_type = type(error).__name__
        error_message = str(error)

        # Determine if error is recoverable
        recoverable = not isinstance(
            error,
            (
                sqlite3.DatabaseError,  # Database corruption
                PermissionError,  # Permission issues
                OSError,  # Disk full, etc.
            ),
        )

        # Record error
        self.error_tracker.record_error(
            error_type, error_message, operation, recoverable=recoverable
        )

        # For critical errors (corruption, disk full), attempt recovery
        if not recoverable:
            recovery_attempted = self._attempt_recovery(error, operation)
            return recovery_attempted

        return False

    def _attempt_recovery(self, error: Exception, operation: str) -> bool:
        """
        Attempt to recover from critical error.

        Args:
            error: Exception that occurred
            operation: Operation that failed

        Returns:
            True if recovery successful, False otherwise
        """
        diagnostics.warning(f"Attempting recovery from {type(error).__name__} in {operation}")

        # For database corruption, try repair
        if isinstance(error, sqlite3.DatabaseError) and "corrupt" in str(error).lower():
            diagnostics.info("Database corruption detected, attempting repair...")

            # Create backup first
            db_path = self.cache_dir / "symbols.db"
            backup_path = self.recovery_manager.backup_database(db_path)

            if not backup_path:
                diagnostics.error("Failed to create backup before repair")
                return False

            # Attempt repair
            if self.recovery_manager.attempt_repair(db_path):
                diagnostics.info("Database repair successful")
                # Reconnect to repaired database
                try:
                    from .sqlite_cache_backend import SqliteCacheBackend

                    self.backend = SqliteCacheBackend(db_path)
                    return True
                except Exception as e:
                    diagnostics.error(f"Failed to reconnect after repair: {e}")
                    return False
            else:
                diagnostics.error("Database repair failed")
                return False

        # For permission errors or disk full, clear cache as last resort
        elif isinstance(error, (PermissionError, OSError)):
            diagnostics.warning(f"Clearing cache due to {type(error).__name__}")
            if self.recovery_manager.clear_cache(self.cache_dir):
                diagnostics.info("Cache cleared successfully")
                return True
            else:
                diagnostics.error("Failed to clear cache")
                return False

        return False

    def _safe_backend_call(self, operation: str, func, *args, **kwargs):
        """
        Safely call a backend method with error tracking.

        Args:
            operation: Operation name for tracking
            func: Backend method to call
            *args, **kwargs: Arguments to pass to method

        Returns:
            Result from backend method, or None on error
        """
        try:
            self.error_tracker.record_operation(operation)
            result = func(*args, **kwargs)
            return result

        except Exception as e:
            diagnostics.error(f"Backend error in {operation}: {e}")

            # Handle error and attempt recovery if needed
            self._handle_backend_error(e, operation)

            return None

    def get_file_hash(self, file_path: str) -> str:
        """Calculate hash of a file"""
        try:
            with open(file_path, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return ""

    def save_cache(
        self,
        class_index: Dict[str, List[SymbolInfo]],
        function_index: Dict[str, List[SymbolInfo]],
        file_hashes: Dict[str, str],
        indexed_file_count: int,
        include_dependencies: bool = False,
        config_file_path: Optional[Path] = None,
        config_file_mtime: Optional[float] = None,
        compile_commands_path: Optional[Path] = None,
        compile_commands_mtime: Optional[float] = None,
    ) -> bool:
        """Save indexes to cache file with configuration metadata"""
        result = self._safe_backend_call(
            "save_cache",
            self.backend.save_cache,
            class_index,
            function_index,
            file_hashes,
            indexed_file_count,
            include_dependencies,
            config_file_path,
            config_file_mtime,
            compile_commands_path,
            compile_commands_mtime,
        )
        return result if result is not None else False

    def load_cache(
        self,
        include_dependencies: bool = False,
        config_file_path: Optional[Path] = None,
        config_file_mtime: Optional[float] = None,
        compile_commands_path: Optional[Path] = None,
        compile_commands_mtime: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Load cache if it exists and is valid, checking for configuration changes"""
        return self._safe_backend_call(
            "load_cache",
            self.backend.load_cache,
            include_dependencies,
            config_file_path,
            config_file_mtime,
            compile_commands_path,
            compile_commands_mtime,
        )

    def save_file_cache(
        self,
        file_path: str,
        symbols: List[SymbolInfo],
        file_hash: str,
        compile_args_hash: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        retry_count: int = 0,
    ) -> bool:
        """Save parsed symbols for a single file with compilation arguments hash"""
        return self.backend.save_file_cache(
            file_path, symbols, file_hash, compile_args_hash, success, error_message, retry_count
        )

    def load_file_cache(
        self, file_path: str, current_hash: str, compile_args_hash: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Load cached data for a file if hash matches"""
        return self.backend.load_file_cache(file_path, current_hash, compile_args_hash)

    def remove_file_cache(self, file_path: str) -> bool:
        """Remove cached data for a deleted file"""
        return self.backend.remove_file_cache(file_path)

    def save_progress(
        self,
        total_files: int,
        indexed_files: int,
        failed_files: int,
        cache_hits: int,
        last_index_time: float,
        class_count: int,
        function_count: int,
        status: str = "in_progress",
    ):
        """Save indexing progress"""
        try:
            progress_file = self.cache_dir / "indexing_progress.json"
            progress_data = {
                "project_root": str(self.project_root),
                "total_files": total_files,
                "indexed_files": indexed_files,
                "failed_files": failed_files,
                "cache_hits": cache_hits,
                "last_index_time": last_index_time,
                "timestamp": time.time(),
                "class_count": class_count,
                "function_count": function_count,
                "status": status,
            }

            with open(progress_file, "w") as f:
                json.dump(progress_data, f, indent=2)
        except:
            pass  # Silently fail for progress tracking

    def load_progress(self) -> Optional[Dict[str, Any]]:
        """Load indexing progress if available"""
        try:
            progress_file = self.cache_dir / "indexing_progress.json"
            if not progress_file.exists():
                return None

            with open(progress_file, "r") as f:
                return json.load(f)
        except:
            return None

    def get_error_summary(self) -> Dict[str, Any]:
        """
        Get summary of cache errors and health status.

        Returns:
            Dict with error statistics
        """
        # Get error tracker summary for cache backend errors
        tracker_summary = self.error_tracker.get_error_summary()

        # Also include parse errors from the JSONL log
        parse_errors = self.get_parse_errors()

        # Count unique files and error types from parse errors
        unique_files = set()
        error_types = {}
        for error in parse_errors:
            unique_files.add(error["file_path"])
            error_type = error.get("error_type", "Unknown")
            error_types[error_type] = error_types.get(error_type, 0) + 1

        # Combine both sources
        summary = tracker_summary.copy()
        summary["backend_type"] = "sqlite"
        summary["total_errors"] = tracker_summary["total_errors"] + len(parse_errors)
        summary["unique_files"] = len(unique_files)
        summary["error_types"] = error_types

        return summary

    def reset_error_tracking(self):
        """Reset error tracking state (useful for testing)."""
        self.error_tracker.reset()

    def log_parse_error(
        self,
        file_path: str,
        error: Exception,
        file_hash: str,
        compile_args_hash: Optional[str],
        retry_count: int,
    ) -> bool:
        """Log a parsing error to the centralized error log for developer analysis.

        Args:
            file_path: Path to the file that failed to parse
            error: The exception that was raised
            file_hash: Hash of the file content
            compile_args_hash: Hash of compilation arguments
            retry_count: Current retry count

        Returns:
            True if logged successfully, False otherwise
        """
        try:
            error_entry = {
                "timestamp": time.time(),
                "timestamp_readable": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "file_path": file_path,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "stack_trace": traceback.format_exc() if sys.exc_info()[0] is not None else None,
                "file_hash": file_hash,
                "compile_args_hash": compile_args_hash,
                "retry_count": retry_count,
            }

            # Append to JSONL file (one JSON object per line)
            with open(self.error_log_path, "a") as f:
                f.write(json.dumps(error_entry) + "\n")

            return True
        except Exception as e:
            # Don't let error logging break the main flow
            print(f"Failed to log parse error: {e}", file=sys.stderr)
            return False

    def get_parse_errors(
        self, limit: Optional[int] = None, file_path_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get parse errors from the error log.

        Args:
            limit: Maximum number of errors to return (most recent first)
            file_path_filter: Only return errors for files matching this path (substring match)

        Returns:
            List of error entries (dicts)
        """
        errors = []
        try:
            if not self.error_log_path.exists():
                return []

            with open(self.error_log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        error_entry = json.loads(line)
                        # Filter by file path if specified
                        if file_path_filter and file_path_filter not in error_entry.get(
                            "file_path", ""
                        ):
                            continue
                        errors.append(error_entry)
                    except json.JSONDecodeError:
                        # Skip malformed lines
                        continue

            # Sort by timestamp (most recent first)
            errors.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

            # Apply limit if specified
            if limit:
                errors = errors[:limit]

            return errors
        except Exception as e:
            print(f"Failed to load parse errors: {e}", file=sys.stderr)
            return []

    def get_parse_error_summary(self) -> Dict[str, Any]:
        """Get a summary of parse errors for developer analysis.

        Returns:
            Dict with error statistics and recent errors
        """
        errors = self.get_parse_errors()

        # Count errors by type
        error_types = defaultdict(int)
        files_with_errors = set()
        for error in errors:
            error_types[error.get("error_type", "Unknown")] += 1
            files_with_errors.add(error.get("file_path"))

        # Get most recent errors
        recent_errors = errors[:10] if len(errors) > 10 else errors

        return {
            "total_errors": len(errors),
            "unique_files": len(files_with_errors),
            "error_types": dict(error_types),
            "recent_errors": recent_errors,
            "error_log_path": str(self.error_log_path),
        }

    def clear_error_log(self, older_than_days: Optional[int] = None) -> int:
        """Clear the error log, optionally keeping recent errors.

        Args:
            older_than_days: If specified, only clear errors older than this many days.
                           If None, clear all errors.

        Returns:
            Number of errors cleared
        """
        try:
            if not self.error_log_path.exists():
                return 0

            if older_than_days is None:
                # Clear all errors
                count = sum(1 for _ in open(self.error_log_path))
                self.error_log_path.unlink()
                return count
            else:
                # Keep recent errors
                cutoff_time = time.time() - (older_than_days * 86400)
                errors = self.get_parse_errors()
                kept_errors = [e for e in errors if e.get("timestamp", 0) > cutoff_time]
                cleared_count = len(errors) - len(kept_errors)

                # Rewrite file with kept errors
                with open(self.error_log_path, "w") as f:
                    for error in kept_errors:
                        f.write(json.dumps(error) + "\n")

                return cleared_count
        except Exception as e:
            print(f"Failed to clear error log: {e}", file=sys.stderr)
            return 0

    # -------------------------------------------------------------------------
    # Type Aliases (Phase 1.3: Type Alias Tracking)
    # -------------------------------------------------------------------------

    def save_type_aliases_batch(self, aliases: List[Dict[str, Any]]) -> int:
        """
        Batch save type aliases to cache.

        Phase 1.3: Type Alias Tracking - Wrapper for backend storage

        Args:
            aliases: List of alias dictionaries

        Returns:
            Number of aliases successfully saved
        """
        return self._safe_backend_call(
            "save_type_aliases_batch", lambda: self.backend.save_type_aliases_batch(aliases)
        )

    def get_aliases_for_canonical(self, canonical_type: str) -> List[str]:
        """
        Get all alias names that resolve to a canonical type.

        Phase 1.3: Type Alias Tracking - Search unification support

        Args:
            canonical_type: Canonical type to look up

        Returns:
            List of alias names
        """
        return self._safe_backend_call(
            "get_aliases_for_canonical",
            lambda: self.backend.get_aliases_for_canonical(canonical_type),
        )

    def get_canonical_for_alias(self, alias_name: str) -> Optional[str]:
        """
        Get canonical type for an alias name.

        Phase 1.3: Type Alias Tracking - Hybrid response format support

        Args:
            alias_name: Alias name to look up

        Returns:
            Canonical type string, or None if not found
        """
        return self._safe_backend_call(
            "get_canonical_for_alias", lambda: self.backend.get_canonical_for_alias(alias_name)
        )

    def get_all_alias_mappings(self) -> Dict[str, str]:
        """
        Get all alias → canonical type mappings.

        Phase 1.3: Type Alias Tracking - Bulk lookup for search expansion

        Returns:
            Dictionary mapping alias names to canonical types
        """
        return self._safe_backend_call(
            "get_all_alias_mappings", lambda: self.backend.get_all_alias_mappings()
        )
