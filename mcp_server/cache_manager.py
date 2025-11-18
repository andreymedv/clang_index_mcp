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
from .json_cache_backend import JsonCacheBackend
from .error_tracking import ErrorTracker, RecoveryManager
from .project_identity import ProjectIdentity

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics


class CacheManager:
    """Manages caching for the C++ analyzer with pluggable backends."""

    def __init__(self, project_root_or_identity: Union[Path, ProjectIdentity]):
        """
        Initialize CacheManager with project identity.

        Args:
            project_root_or_identity: Either a Path (backward compatibility) or ProjectIdentity

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

        self.cache_dir = self._get_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.error_log_path = self.cache_dir / "parse_errors.jsonl"

        # Initialize error tracking
        self.error_tracker = ErrorTracker(
            window_seconds=300.0,  # 5 minute window
            fallback_threshold=0.05  # 5% error rate triggers fallback
        )

        # Initialize recovery manager
        self.recovery_manager = RecoveryManager()

        # Track initial backend type for fallback detection
        self.initial_backend_type: Optional[str] = None
        self.fallback_active = False

        # Initialize cache backend based on feature flag
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
        mcp_server_root = Path(__file__).parent.parent  # Go up from mcp_server/cache_manager.py to root
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

    def _maybe_migrate_from_json(self) -> bool:
        """
        Automatically migrate from JSON cache to SQLite if needed.

        Checks for existing JSON cache and migration marker. If JSON cache exists
        and migration hasn't been done, performs automatic migration with backup.

        Returns:
            True if migration was performed or not needed, False if migration failed
        """
        try:
            from .cache_migration import (
                should_migrate,
                create_migration_backup,
                migrate_json_to_sqlite,
                verify_migration,
                create_migration_marker
            )

            db_path = self.cache_dir / "symbols.db"
            marker_path = self.cache_dir / ".migrated_to_sqlite"

            # Check if migration is needed
            if not should_migrate(self.cache_dir, marker_path):
                return True

            diagnostics.info("Starting automatic JSON → SQLite migration...")

            # Create backup before migration
            backup_success, backup_msg, backup_path = create_migration_backup(self.cache_dir)
            if not backup_success:
                diagnostics.error(f"Failed to create backup: {backup_msg}")
                return False

            diagnostics.info(f"Backup created: {backup_path}")

            # Perform migration
            migrate_success, migrate_msg = migrate_json_to_sqlite(self.cache_dir, db_path)
            if not migrate_success:
                diagnostics.error(f"Migration failed: {migrate_msg}")
                return False

            diagnostics.info(f"Migration completed: {migrate_msg}")

            # Verify migration
            verify_success, verify_msg = verify_migration(self.cache_dir, db_path)
            if not verify_success:
                diagnostics.error(f"Migration verification failed: {verify_msg}")
                return False

            diagnostics.info(f"Migration verified: {verify_msg}")

            # Create marker file to prevent re-migration
            migration_info = {
                "backup_path": str(backup_path) if backup_path else None,
                "message": migrate_msg
            }
            create_migration_marker(marker_path, migration_info)

            diagnostics.info("Migration successful! SQLite cache is now active.")
            return True

        except Exception as e:
            diagnostics.error(f"Migration failed with exception: {e}")
            import traceback
            diagnostics.error(traceback.format_exc())
            return False

    def _create_backend(self) -> CacheBackend:
        """
        Create appropriate cache backend based on feature flag.

        Feature flag: CLANG_INDEX_USE_SQLITE (default: "1")
        - "1" or "true" -> Use SQLite backend
        - "0" or "false" -> Use JSON backend

        Falls back to JSON on SQLite initialization errors.

        Returns:
            CacheBackend instance (SQLite or JSON)
        """
        use_sqlite = os.environ.get("CLANG_INDEX_USE_SQLITE", "1").lower()

        if use_sqlite in ("1", "true"):
            try:
                # Attempt automatic migration from JSON if needed
                migration_ok = self._maybe_migrate_from_json()
                if not migration_ok:
                    diagnostics.warning("Migration failed, falling back to JSON backend")
                    self.initial_backend_type = "json"
                    return JsonCacheBackend(self.cache_dir)

                # Import SQLite backend dynamically to avoid startup errors if missing
                from .sqlite_cache_backend import SqliteCacheBackend

                db_path = self.cache_dir / "symbols.db"
                backend = SqliteCacheBackend(db_path)
                diagnostics.debug(f"Using SQLite cache backend: {db_path}")
                self.initial_backend_type = "sqlite"
                return backend

            except Exception as e:
                diagnostics.warning(f"Failed to initialize SQLite backend: {e}")
                diagnostics.warning("Falling back to JSON cache backend")
                self.error_tracker.record_error(
                    "InitializationError",
                    str(e),
                    "backend_init",
                    recoverable=False
                )

        # Fall back to JSON backend
        diagnostics.debug(f"Using JSON cache backend: {self.cache_dir}")
        self.initial_backend_type = "json"
        return JsonCacheBackend(self.cache_dir)

    def _handle_backend_error(self, error: Exception, operation: str) -> bool:
        """
        Handle backend errors with tracking and fallback logic.

        Args:
            error: Exception that occurred
            operation: Operation that failed

        Returns:
            True if operation should be retried with fallback backend, False otherwise
        """
        # Classify error type
        error_type = type(error).__name__
        error_message = str(error)

        # Determine if error is recoverable
        recoverable = not isinstance(error, (
            sqlite3.DatabaseError,  # Database corruption
            PermissionError,        # Permission issues
            OSError,               # Disk full, etc.
        ))

        # Record error
        should_fallback = self.error_tracker.record_error(
            error_type,
            error_message,
            operation,
            recoverable=recoverable
        )

        # If error tracker triggers fallback, switch to JSON backend
        if should_fallback and not self.fallback_active:
            diagnostics.error(
                f"Error rate threshold exceeded. Falling back to JSON backend."
            )
            self._fallback_to_json()
            return True

        # For critical errors (corruption, disk full), attempt recovery
        if not recoverable and not self.fallback_active:
            recovery_attempted = self._attempt_recovery(error, operation)
            if not recovery_attempted:
                # Recovery failed, fall back to JSON
                self._fallback_to_json()
                return True

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

    def _fallback_to_json(self):
        """Fallback to JSON backend."""
        if self.fallback_active:
            return  # Already using fallback

        diagnostics.warning("Switching to JSON backend")
        self.fallback_active = True

        try:
            self.backend = JsonCacheBackend(self.cache_dir)
            diagnostics.info("Successfully switched to JSON backend")
        except Exception as e:
            diagnostics.error(f"Failed to initialize JSON backend: {e}")
            # This is a critical error - we can't continue
            raise

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

            # Handle error with potential fallback
            retry_with_fallback = self._handle_backend_error(e, operation)

            if retry_with_fallback and self.fallback_active:
                # Retry with JSON backend
                try:
                    diagnostics.info(f"Retrying {operation} with JSON backend")
                    self.error_tracker.record_operation(f"{operation}_retry")
                    result = func(*args, **kwargs)
                    return result
                except Exception as e2:
                    diagnostics.error(f"Retry failed: {e2}")
                    return None

            return None
    
    def get_file_hash(self, file_path: str) -> str:
        """Calculate hash of a file"""
        try:
            with open(file_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return ""
    
    def save_cache(self, class_index: Dict[str, List[SymbolInfo]],
                   function_index: Dict[str, List[SymbolInfo]],
                   file_hashes: Dict[str, str],
                   indexed_file_count: int,
                   include_dependencies: bool = False,
                   config_file_path: Optional[Path] = None,
                   config_file_mtime: Optional[float] = None,
                   compile_commands_path: Optional[Path] = None,
                   compile_commands_mtime: Optional[float] = None) -> bool:
        """Save indexes to cache file with configuration metadata"""
        result = self._safe_backend_call(
            "save_cache",
            self.backend.save_cache,
            class_index, function_index, file_hashes, indexed_file_count,
            include_dependencies, config_file_path, config_file_mtime,
            compile_commands_path, compile_commands_mtime
        )
        return result if result is not None else False
    
    def load_cache(self, include_dependencies: bool = False,
                   config_file_path: Optional[Path] = None,
                   config_file_mtime: Optional[float] = None,
                   compile_commands_path: Optional[Path] = None,
                   compile_commands_mtime: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Load cache if it exists and is valid, checking for configuration changes"""
        return self._safe_backend_call(
            "load_cache",
            self.backend.load_cache,
            include_dependencies, config_file_path, config_file_mtime,
            compile_commands_path, compile_commands_mtime
        )
    
    def save_file_cache(self, file_path: str, symbols: List[SymbolInfo],
                       file_hash: str, compile_args_hash: Optional[str] = None,
                       success: bool = True, error_message: Optional[str] = None,
                       retry_count: int = 0) -> bool:
        """Save parsed symbols for a single file with compilation arguments hash"""
        return self.backend.save_file_cache(
            file_path, symbols, file_hash, compile_args_hash,
            success, error_message, retry_count
        )

    def load_file_cache(self, file_path: str, current_hash: str,
                       compile_args_hash: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Load cached data for a file if hash matches"""
        return self.backend.load_file_cache(file_path, current_hash, compile_args_hash)

    def remove_file_cache(self, file_path: str) -> bool:
        """Remove cached data for a deleted file"""
        return self.backend.remove_file_cache(file_path)
    
    def save_progress(self, total_files: int, indexed_files: int, 
                     failed_files: int, cache_hits: int,
                     last_index_time: float, class_count: int, 
                     function_count: int, status: str = "in_progress"):
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
                "status": status
            }
            
            with open(progress_file, 'w') as f:
                json.dump(progress_data, f, indent=2)
        except:
            pass  # Silently fail for progress tracking
    
    def load_progress(self) -> Optional[Dict[str, Any]]:
        """Load indexing progress if available"""
        try:
            progress_file = self.cache_dir / "indexing_progress.json"
            if not progress_file.exists():
                return None

            with open(progress_file, 'r') as f:
                return json.load(f)
        except:
            return None

    def get_error_summary(self) -> Dict[str, Any]:
        """
        Get summary of cache errors and health status.

        Returns:
            Dict with error statistics and backend status
        """
        summary = self.error_tracker.get_error_summary()
        summary['backend_type'] = self.initial_backend_type
        summary['fallback_active'] = self.fallback_active
        return summary

    def reset_error_tracking(self):
        """Reset error tracking state (useful for testing)."""
        self.error_tracker.reset()

    def log_parse_error(self, file_path: str, error: Exception,
                       file_hash: str, compile_args_hash: Optional[str],
                       retry_count: int) -> bool:
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
                "retry_count": retry_count
            }

            # Append to JSONL file (one JSON object per line)
            with open(self.error_log_path, 'a') as f:
                f.write(json.dumps(error_entry) + '\n')

            return True
        except Exception as e:
            # Don't let error logging break the main flow
            print(f"Failed to log parse error: {e}", file=sys.stderr)
            return False

    def get_parse_errors(self, limit: Optional[int] = None,
                        file_path_filter: Optional[str] = None) -> List[Dict[str, Any]]:
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

            with open(self.error_log_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        error_entry = json.loads(line)
                        # Filter by file path if specified
                        if file_path_filter and file_path_filter not in error_entry.get('file_path', ''):
                            continue
                        errors.append(error_entry)
                    except json.JSONDecodeError:
                        # Skip malformed lines
                        continue

            # Sort by timestamp (most recent first)
            errors.sort(key=lambda x: x.get('timestamp', 0), reverse=True)

            # Apply limit if specified
            if limit:
                errors = errors[:limit]

            return errors
        except Exception as e:
            print(f"Failed to load parse errors: {e}", file=sys.stderr)
            return []

    def get_error_summary(self) -> Dict[str, Any]:
        """Get a summary of parse errors for developer analysis.

        Returns:
            Dict with error statistics and recent errors
        """
        errors = self.get_parse_errors()

        # Count errors by type
        error_types = defaultdict(int)
        files_with_errors = set()
        for error in errors:
            error_types[error.get('error_type', 'Unknown')] += 1
            files_with_errors.add(error.get('file_path'))

        # Get most recent errors
        recent_errors = errors[:10] if len(errors) > 10 else errors

        return {
            "total_errors": len(errors),
            "unique_files": len(files_with_errors),
            "error_types": dict(error_types),
            "recent_errors": recent_errors,
            "error_log_path": str(self.error_log_path)
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
                kept_errors = [e for e in errors if e.get('timestamp', 0) > cutoff_time]
                cleared_count = len(errors) - len(kept_errors)

                # Rewrite file with kept errors
                with open(self.error_log_path, 'w') as f:
                    for error in kept_errors:
                        f.write(json.dumps(error) + '\n')

                return cleared_count
        except Exception as e:
            print(f"Failed to clear error log: {e}", file=sys.stderr)
            return 0