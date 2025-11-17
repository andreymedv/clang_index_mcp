"""Cache management for C++ analyzer."""

import json
import hashlib
import time
import os
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from collections import defaultdict
from .symbol_info import SymbolInfo
from .cache_backend import CacheBackend
from .json_cache_backend import JsonCacheBackend

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics


class CacheManager:
    """Manages caching for the C++ analyzer with pluggable backends."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.cache_dir = self._get_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.error_log_path = self.cache_dir / "parse_errors.jsonl"

        # Initialize cache backend based on feature flag
        self.backend = self._create_backend()
        
    def _get_cache_dir(self) -> Path:
        """Get the cache directory for this project"""
        # Use the MCP server directory for cache, not the project being analyzed
        mcp_server_root = Path(__file__).parent.parent  # Go up from mcp_server/cache_manager.py to root
        cache_base = mcp_server_root / ".mcp_cache"

        # Use a hash of the project path to create a unique cache directory
        project_hash = hashlib.md5(str(self.project_root).encode()).hexdigest()[:8]
        cache_dir = cache_base / f"{self.project_root.name}_{project_hash}"
        return cache_dir

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
                # Import SQLite backend dynamically to avoid startup errors if missing
                from .sqlite_cache_backend import SqliteCacheBackend

                db_path = self.cache_dir / "symbols.db"
                backend = SqliteCacheBackend(db_path)
                diagnostics.debug(f"Using SQLite cache backend: {db_path}")
                return backend

            except Exception as e:
                diagnostics.warning(f"Failed to initialize SQLite backend: {e}")
                diagnostics.warning("Falling back to JSON cache backend")

        # Fall back to JSON backend
        diagnostics.debug(f"Using JSON cache backend: {self.cache_dir}")
        return JsonCacheBackend(self.cache_dir)
    
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
        return self.backend.save_cache(
            class_index, function_index, file_hashes, indexed_file_count,
            include_dependencies, config_file_path, config_file_mtime,
            compile_commands_path, compile_commands_mtime
        )
    
    def load_cache(self, include_dependencies: bool = False,
                   config_file_path: Optional[Path] = None,
                   config_file_mtime: Optional[float] = None,
                   compile_commands_path: Optional[Path] = None,
                   compile_commands_mtime: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Load cache if it exists and is valid, checking for configuration changes"""
        return self.backend.load_cache(
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