"""SQLite-backed file metadata and cache metadata operations."""

import sqlite3
import time
from typing import Any, Callable, Dict, Optional, Set

try:
    from ..._core import diagnostics
except ImportError:
    import diagnostics  # type: ignore[no-redef]


class FileMetadataRepository:
    """Handles file metadata, cache metadata, and compile args hash persistence."""

    def __init__(self, conn_getter: Callable[[], Optional[sqlite3.Connection]]):
        self._conn_getter = conn_getter

    @property
    def conn(self) -> sqlite3.Connection:
        connection = self._conn_getter()
        assert connection is not None, "Database connection not initialized"
        return connection

    def update_file_metadata(
        self,
        file_path: str,
        file_hash: str,
        compile_args_hash: Optional[str] = None,
        symbol_count: int = 0,
        success: bool = True,
        error_message: Optional[str] = None,
        retry_count: int = 0,
    ) -> bool:
        """Update or insert file metadata."""
        try:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO file_metadata
                    (file_path, file_hash, compile_args_hash, indexed_at, symbol_count,
                     success, error_message, retry_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_path,
                        file_hash,
                        compile_args_hash,
                        time.time(),
                        symbol_count,
                        success,
                        error_message,
                        retry_count,
                    ),
                )
            return True
        except Exception as e:
            diagnostics.error(f"Failed to update file metadata for {file_path}: {e}")
            return False

    def get_file_metadata(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a file."""
        try:
            cursor = self.conn.execute(
                "SELECT * FROM file_metadata WHERE file_path = ?", (file_path,)
            )
            row = cursor.fetchone()
            if row:
                result: Dict[str, Any] = {
                    "file_path": row["file_path"],
                    "file_hash": row["file_hash"],
                    "compile_args_hash": row["compile_args_hash"],
                    "indexed_at": row["indexed_at"],
                    "symbol_count": row["symbol_count"],
                }
                try:
                    result["success"] = bool(row["success"])
                    result["error_message"] = row["error_message"]
                    result["retry_count"] = row["retry_count"]
                except (KeyError, IndexError):
                    result["success"] = True
                    result["error_message"] = None
                    result["retry_count"] = 0
                return result
            return None
        except Exception as e:
            diagnostics.error(f"Failed to get file metadata for {file_path}: {e}")
            return None

    def load_all_file_hashes(self) -> Dict[str, str]:
        """Load all file hashes for cache validation."""
        try:
            cursor = self.conn.execute("SELECT file_path, file_hash FROM file_metadata")
            return {row["file_path"]: row["file_hash"] for row in cursor.fetchall()}
        except Exception as e:
            diagnostics.error(f"Failed to load file hashes: {e}")
            return {}

    def update_cache_metadata(self, key: str, value: str) -> bool:
        """Update cache metadata."""
        try:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO cache_metadata (key, value, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (key, value, time.time()),
                )
            return True
        except Exception as e:
            diagnostics.error(f"Failed to update cache metadata {key}: {e}")
            return False

    def get_cache_metadata(self, key: str) -> Optional[str]:
        """Get cache metadata value."""
        try:
            cursor = self.conn.execute("SELECT value FROM cache_metadata WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else None
        except Exception as e:
            diagnostics.error(f"Failed to get cache metadata {key}: {e}")
            return None

    def get_all_cached_file_paths(self) -> Set[str]:
        """Return all file paths stored in file_metadata table."""
        try:
            cursor = self.conn.execute("SELECT file_path FROM file_metadata")
            return {row[0] for row in cursor.fetchall()}
        except Exception as e:
            diagnostics.warning(f"Failed to get cached file paths: {e}")
            return set()

    def set_compile_args_hash(self, file_path: str, args_hash: str) -> bool:
        """Store or update the compile arguments hash for a file."""
        try:
            cursor = self.conn.execute(
                """
                UPDATE file_metadata
                SET compile_args_hash = ?
                WHERE file_path = ?
                """,
                (args_hash, file_path),
            )
            if cursor.rowcount == 0:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO file_metadata
                    (file_path, file_hash, compile_args_hash, indexed_at, symbol_count)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (file_path, "", args_hash, time.time(), 0),
                )
            self.conn.commit()
            return True
        except Exception as e:
            diagnostics.warning(f"Failed to set compile args hash for {file_path}: {e}")
            self.conn.rollback()
            return False

    def get_compile_args_hash(self, file_path: str) -> Optional[str]:
        """Return the stored compile arguments hash for a file."""
        try:
            cursor = self.conn.execute(
                """
                SELECT compile_args_hash FROM file_metadata
                WHERE file_path = ?
                """,
                (file_path,),
            )
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            diagnostics.warning(f"Failed to get compile args hash for {file_path}: {e}")
            return None

    def clear_compile_args_hashes(self) -> int:
        """Clear all stored compile arguments hashes from file_metadata."""
        try:
            cursor = self.conn.execute("""
                UPDATE file_metadata
                SET compile_args_hash = NULL
                """)
            cleared = cursor.rowcount or 0
            self.conn.commit()
            return cleared
        except Exception as e:
            diagnostics.warning(f"Failed to clear compile args hashes: {e}")
            self.conn.rollback()
            return 0
