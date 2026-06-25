"""SQLite-based cache backend for C++ analyzer."""

import fcntl
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .._symbols.model import SymbolInfo
from .._persistence import type_alias_repository
from .._persistence.repositories.symbol_repository import SymbolRepository

# Handle both package and script imports
try:
    from .._core import diagnostics
except ImportError:
    import diagnostics  # type: ignore[no-redef]


class SqliteCacheBackend:
    """
    SQLite-based cache backend for C++ symbol storage.

    Provides high-performance symbol caching with:
    - FTS5 full-text search for fast name lookups
    - WAL mode for concurrent read access
    - Automatic database recreation on schema changes (development mode)
    - Transaction-based bulk operations
    - Platform-specific optimizations

    Performance targets (100K symbols):
    - Startup: < 500ms
    - Name search (FTS5): < 5ms
    - Bulk insert: > 5000 symbols/sec
    - Memory usage: < 50MB

    Note: During development, the database is automatically recreated when the
    schema version changes. This simplifies development by avoiding migration
    complexity, since the cache can be regenerated from source files.
    """

    CURRENT_SCHEMA_VERSION = "17.0"  # Must match version in schema.sql

    def __init__(self, db_path: Path, skip_schema_recreation: bool = False):
        """
        Initialize SQLite cache backend.

        Args:
            db_path: Path to SQLite database file
            skip_schema_recreation: If True, skip database recreation on schema mismatch.
                                   Used by worker processes to avoid race conditions.
                                   Workers should rely on main process to ensure schema is current.
        """
        self.db_path = Path(db_path)
        self.conn: Optional[sqlite3.Connection] = None
        self._last_access = 0
        self._connection_timeout = 300  # 5 minutes idle timeout
        self._skip_schema_recreation = skip_schema_recreation

        # Initialize database under file lock to prevent SIGBUS from
        # concurrent DB file deletion during schema recreation.
        # The lock must cover _connect() because WAL mode causes SQLite
        # to internally mmap the SHM file, and another instance deleting
        # that file during recreation would crash this connection with SIGBUS.
        with self._acquire_init_lock():
            self._connect()
            self._init_database()

        # Sub-repositories (delegate after connection is live)
        self._symbol_repo = SymbolRepository(self.get_connection)

    def _connect(self):
        """Open database connection with optimized settings."""
        try:
            # Ensure parent directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            # Configure for concurrent access
            self.conn = sqlite3.connect(
                str(self.db_path),
                timeout=30.0,  # Wait up to 30s for locks
                isolation_level=None,  # Autocommit off, manual transactions
                check_same_thread=False,  # Allow multi-threaded access
            )

            # Enable row factory for dict-like access
            self._conn.row_factory = sqlite3.Row

            # Set busy handler for lock retry with exponential backoff (if available)
            if hasattr(self.conn, "set_busy_handler"):
                self._conn.set_busy_handler(self._busy_handler)
            else:
                diagnostics.debug("set_busy_handler not available, using timeout only")

            # Configure platform-specific settings
            self._configure_platform()

            # Apply connection-level PRAGMA optimizations
            # CRITICAL: This must be called for EVERY connection (main + workers)
            # to ensure proper performance, regardless of schema recreation status
            self._set_connection_pragmas()

            self._last_access = time.time()

        except Exception as e:
            diagnostics.error(f"Failed to connect to SQLite database: {e}")
            raise

    @property
    def _conn(self) -> sqlite3.Connection:
        """Return the database connection, asserting it is not None."""
        assert self.conn is not None, "Database connection not initialized"
        return self.conn

    def _busy_handler(self, retry_count: int) -> bool:
        """
        Called when database is locked.
        Implements exponential backoff.

        Args:
            retry_count: Number of retries so far

        Returns:
            True to retry, False to give up
        """
        if retry_count < 20:
            # Exponential backoff up to 1 second
            sleep_time = 0.001 * (2 ** min(retry_count, 10))
            time.sleep(sleep_time)
            return True  # Retry
        return False  # Give up after 20 retries

    def _configure_platform(self):
        """Apply platform-specific SQLite configuration."""
        # Get platform
        platform = sys.platform

        if platform == "win32":
            # Windows: WAL mode works well
            diagnostics.debug("SQLite configured for Windows")
        elif platform == "darwin":
            # macOS: Standard configuration
            diagnostics.debug("SQLite configured for macOS")
        else:
            # Linux/Unix: Standard configuration
            diagnostics.debug("SQLite configured for Linux/Unix")

        # Note: NFS support explicitly not included per requirements
        # Database should be on local filesystem

    def _set_connection_pragmas(self):
        """
        Apply connection-level PRAGMA optimizations.

        These are connection-specific settings that must be applied to each
        database connection, including worker processes. They were previously
        in schema.sql, but that caused a bug where worker processes (with
        skip_schema_recreation=True) would skip applying these critical
        performance optimizations.

        CRITICAL: These PRAGMAs are connection-level settings, NOT schema.
        They must be applied every time a connection is opened, regardless
        of whether schema recreation is needed.
        """
        try:
            # Write-Ahead Logging for better concurrency
            # This is especially important for ProcessPoolExecutor workers
            self._conn.execute("PRAGMA journal_mode = WAL")

            # Balance safety and speed (NORMAL is safe for WAL mode)
            self._conn.execute("PRAGMA synchronous = NORMAL")

            # 64MB cache for better performance
            # Negative value means KiB (64000 KiB = ~64 MB)
            self._conn.execute("PRAGMA cache_size = -64000")

            # Keep temporary tables in RAM instead of disk
            self._conn.execute("PRAGMA temp_store = MEMORY")

            # Disable memory-mapped I/O to prevent bus errors with concurrent access
            # mmap is incompatible with concurrent writes from multiple processes/threads
            # and can cause SIGBUS crashes. WAL mode + other optimizations provide
            # sufficient performance without mmap.
            # See: https://www.sqlite.org/mmap.html#disadvantages
            self._conn.execute("PRAGMA mmap_size = 0")

            diagnostics.debug("SQLite connection PRAGMAs applied successfully")

        except Exception as e:
            diagnostics.warning(f"Failed to apply some SQLite PRAGMAs: {e}")
            # Don't raise - database can still work with default settings

    def _acquire_init_lock(self):
        """Acquire file lock for database initialization.

        Returns context manager that releases lock on exit.
        """
        import contextlib

        @contextlib.contextmanager
        def lock_context():
            lock_path = self.db_path.with_suffix(".db.lock")
            lock_file = None
            try:
                lock_file = open(lock_path, "w")
                lock_fd = lock_file.fileno()
                # Try non-blocking lock first
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    diagnostics.debug(f"Acquired init lock on {lock_path}")
                except BlockingIOError:
                    # Lock is held by another instance, wait for it
                    diagnostics.debug(f"Waiting for init lock on {lock_path}...")
                    fcntl.flock(lock_fd, fcntl.LOCK_EX)  # Blocking lock
                    diagnostics.debug(f"Acquired init lock on {lock_path}")

                yield  # Critical section

            finally:
                if lock_file:
                    try:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                        lock_file.close()
                        diagnostics.debug("Released init lock")
                    except Exception as e:
                        diagnostics.warning(f"Error releasing init lock: {e}")

        return lock_context()

    def _check_schema_version(self) -> Tuple[bool, bool]:
        """Check if schema needs recreation. Returns (needs_recreate, schema_ok)."""
        if not self.db_path.exists():
            return False, False

        try:
            cursor = self._conn.execute("SELECT value FROM cache_metadata WHERE key = 'version'")
            result = cursor.fetchone()
            if result:
                current_version = json.loads(result[0])
                if current_version != self.CURRENT_SCHEMA_VERSION:
                    if self._skip_schema_recreation:
                        # Worker process: don't recreate, just use existing DB
                        diagnostics.debug(
                            f"Worker: Schema mismatch ({current_version} vs {self.CURRENT_SCHEMA_VERSION}), "
                            "skipping recreation (main process handles this)"
                        )
                        return False, True  # Assume main handled it
                    else:
                        diagnostics.info(
                            f"Schema version mismatch: current={current_version}, expected={self.CURRENT_SCHEMA_VERSION}"
                        )
                        diagnostics.info("Recreating database with current schema")
                        return True, False
                else:
                    return False, True
            else:
                if self._skip_schema_recreation:
                    diagnostics.debug("Worker: No version metadata, skipping recreation")
                    return False, True
                else:
                    diagnostics.info("No version metadata found, recreating database")
                    return True, False
        except (sqlite3.OperationalError, Exception) as e:
            if self._skip_schema_recreation:
                # Worker: database might be being recreated by main
                diagnostics.debug(f"Worker: DB access error ({e}), will retry")
                raise  # Will trigger retry logic
            else:
                # Table doesn't exist or other error - recreate
                diagnostics.info("Invalid or corrupted database, recreating")
                return True, False

    def _recreate_database(self) -> None:
        """Close connection, delete old database files, and reconnect."""
        self._close()
        if self.db_path.exists():
            try:
                self.db_path.unlink()
                diagnostics.info(f"Deleted old database: {self.db_path}")
            except FileNotFoundError:
                # Race condition: another thread already deleted it
                pass

        # Also delete WAL and SHM files if they exist
        for ext in ["-wal", "-shm"]:
            wal_file = Path(str(self.db_path) + ext)
            if wal_file.exists():
                try:
                    wal_file.unlink()
                except FileNotFoundError:
                    # Race condition: another thread already deleted it
                    pass

        # Reconnect to create fresh database
        self._connect()

    def _init_database(self):
        """Initialize database schema and configuration with retry logic."""
        max_retries = 10
        base_delay = 0.1  # 100ms initial delay

        for attempt in range(max_retries):
            try:
                # Check if database exists and has the correct version
                needs_recreate, schema_ok = self._check_schema_version()

                # If schema is already OK, just ensure tables exist
                if schema_ok:
                    diagnostics.debug(
                        f"Database schema is current (v{self.CURRENT_SCHEMA_VERSION})"
                    )
                    return

                if needs_recreate:
                    self._recreate_database()

                # Execute schema file
                schema_path = Path(__file__).parent / "schema.sql"

                if not schema_path.exists():
                    raise FileNotFoundError(f"Schema file not found: {schema_path}")

                with open(schema_path, "r") as f:
                    schema_sql = f.read()

                # Execute schema (creates tables, indexes, triggers)
                self._conn.executescript(schema_sql)
                self._conn.commit()

                diagnostics.debug(
                    f"SQLite database initialized successfully (schema v{self.CURRENT_SCHEMA_VERSION})"
                )
                return  # Success, exit the retry loop

            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    # Exponential backoff with jitter
                    import random

                    delay = base_delay * (2**attempt) + random.uniform(0, 0.1)
                    diagnostics.debug(
                        f"Database locked during init, retry {attempt + 1}/{max_retries} after {delay:.2f}s"
                    )
                    time.sleep(delay)
                    continue
                else:
                    diagnostics.error(f"Failed to initialize database: {e}")
                    raise
            except Exception as e:
                diagnostics.error(f"Failed to initialize database: {e}")
                raise

    def ensure_schema_current(self) -> bool:
        """
        Ensure database schema is current. Called by main process before spawning workers.

        This method should be called BEFORE creating ProcessPoolExecutor workers
        to prevent race conditions where multiple workers detect schema mismatch
        and try to recreate the database simultaneously.

        Returns:
            True if schema was recreated, False if it was already current.
        """
        try:
            cursor = self._conn.execute("SELECT value FROM cache_metadata WHERE key = 'version'")
            result = cursor.fetchone()
            if result:
                current_version = json.loads(result[0])
                if current_version == self.CURRENT_SCHEMA_VERSION:
                    diagnostics.debug(
                        f"Schema is current (v{self.CURRENT_SCHEMA_VERSION}), workers can proceed"
                    )
                    return False  # Already current

            # Schema mismatch or missing - need to recreate
            diagnostics.info("Main process ensuring schema is current before workers...")

            # Force recreation by clearing skip flag temporarily
            old_skip = self._skip_schema_recreation
            self._skip_schema_recreation = False

            # Close and reopen under lock to prevent SIGBUS (see cplusplus_mcp-j19)
            with self._acquire_init_lock():
                self._close()
                self._connect()
                self._init_database()

            self._skip_schema_recreation = old_skip
            diagnostics.info(
                f"Schema updated to v{self.CURRENT_SCHEMA_VERSION}, workers can now proceed"
            )
            return True

        except Exception as e:
            diagnostics.error(f"Failed to ensure schema current: {e}")
            # Try to recreate anyway
            with self._acquire_init_lock():
                self._close()
                self._connect()
                self._init_database()
            return True

    def _ensure_connected(self):
        """Ensure connection is active, reconnect if needed."""
        if self.conn is None:
            self._connect()
            return

        # Check if connection is stale
        if time.time() - self._last_access > self._connection_timeout:
            diagnostics.debug("Connection idle timeout, reconnecting...")
            self._close()
            self._connect()

        self._last_access = time.time()

    def get_connection(self) -> Optional[sqlite3.Connection]:
        """Return the raw SQLite connection.

        This is a transitional method for components like DependencyGraphBuilder
        that inherently require raw SQL access.
        """
        self._ensure_connected()
        return self.conn

    def _close(self):
        """Close database connection."""
        if self.conn is not None:
            try:
                self._conn.close()
            except Exception as e:
                diagnostics.warning(f"Error closing connection: {e}")
            finally:
                self.conn = None

    def close(self):
        """Close database connection (CacheBackend protocol method)."""
        self._close()

    def __enter__(self):
        """Context manager entry."""
        self._ensure_connected()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self._close()

    def __del__(self):
        """Destructor to ensure connection is closed on garbage collection."""
        self._close()

    def _symbol_to_tuple(self, symbol: SymbolInfo) -> tuple:
        return self._symbol_repo._symbol_to_tuple(symbol)

    def _row_to_symbol(self, row: sqlite3.Row) -> SymbolInfo:
        return self._symbol_repo._row_to_symbol(row)

    def save_symbol(self, symbol: SymbolInfo) -> bool:
        self._ensure_connected()
        return self._symbol_repo.save_symbol(symbol)

    def save_symbols_batch(self, symbols: List[SymbolInfo]) -> int:
        self._ensure_connected()
        return self._symbol_repo.save_symbols_batch(symbols)

    def load_symbol_by_usr(self, usr: str) -> Optional[SymbolInfo]:
        self._ensure_connected()
        return self._symbol_repo.load_symbol_by_usr(usr)

    def load_symbols_by_name(self, name: str) -> List[SymbolInfo]:
        self._ensure_connected()
        return self._symbol_repo.load_symbols_by_name(name)

    def count_symbols(self) -> int:
        self._ensure_connected()
        return self._symbol_repo.count_symbols()

    def delete_symbols_by_file(self, file_path: str) -> int:
        self._ensure_connected()
        return self._symbol_repo.delete_symbols_by_file(file_path)

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
        """
        Update or insert file metadata.

        Args:
            file_path: Absolute path to file
            file_hash: MD5 hash of file contents
            compile_args_hash: Hash of compilation arguments
            symbol_count: Number of symbols in file
            success: Whether parsing succeeded
            error_message: Error message if parsing failed
            retry_count: Number of retry attempts

        Returns:
            True if successful, False otherwise
        """
        try:
            self._ensure_connected()

            with self._conn:
                self._conn.execute(
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
        """
        Get metadata for a file.

        Args:
            file_path: Path to file

        Returns:
            Dict with file metadata if found, None otherwise
        """
        try:
            self._ensure_connected()

            cursor = self._conn.execute(
                "SELECT * FROM file_metadata WHERE file_path = ?", (file_path,)
            )

            row = cursor.fetchone()
            if row:
                # Handle databases that may not have the new columns yet (before migration)
                result = {
                    "file_path": row["file_path"],
                    "file_hash": row["file_hash"],
                    "compile_args_hash": row["compile_args_hash"],
                    "indexed_at": row["indexed_at"],
                    "symbol_count": row["symbol_count"],
                }
                # Add new columns if they exist
                try:
                    result["success"] = bool(row["success"])
                    result["error_message"] = row["error_message"]
                    result["retry_count"] = row["retry_count"]
                except (KeyError, IndexError):
                    # Columns don't exist yet (pre-migration database)
                    result["success"] = True
                    result["error_message"] = None
                    result["retry_count"] = 0
                return result

            return None

        except Exception as e:
            diagnostics.error(f"Failed to get file metadata for {file_path}: {e}")
            return None

    def load_all_file_hashes(self) -> Dict[str, str]:
        """
        Load all file hashes for cache validation.

        Returns:
            Dict mapping file_path to file_hash
        """
        try:
            self._ensure_connected()

            cursor = self._conn.execute("SELECT file_path, file_hash FROM file_metadata")

            return {row["file_path"]: row["file_hash"] for row in cursor.fetchall()}

        except Exception as e:
            diagnostics.error(f"Failed to load file hashes: {e}")
            return {}

    def update_cache_metadata(self, key: str, value: str) -> bool:
        """
        Update cache metadata.

        Args:
            key: Metadata key
            value: Metadata value (as JSON string for complex types)

        Returns:
            True if successful, False otherwise
        """
        try:
            self._ensure_connected()

            with self._conn:
                self._conn.execute(
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
        """
        Get cache metadata value.

        Args:
            key: Metadata key

        Returns:
            Metadata value if found, None otherwise
        """
        try:
            self._ensure_connected()

            cursor = self._conn.execute("SELECT value FROM cache_metadata WHERE key = ?", (key,))

            row = cursor.fetchone()
            return row["value"] if row else None

        except Exception as e:
            diagnostics.error(f"Failed to get cache metadata {key}: {e}")
            return None

    def search_symbols_fts(
        self, pattern: str, kind: Optional[str] = None, project_only: bool = True
    ) -> List[SymbolInfo]:
        self._ensure_connected()
        return self._symbol_repo.search_symbols_fts(pattern, kind, project_only)

    def search_symbols_regex(
        self, pattern: str, kind: Optional[str] = None, project_only: bool = True
    ) -> List[SymbolInfo]:
        self._ensure_connected()
        return self._symbol_repo.search_symbols_regex(pattern, kind, project_only)

    def search_symbols_by_file(self, file_path: str) -> List[SymbolInfo]:
        self._ensure_connected()
        return self._symbol_repo.search_symbols_by_file(file_path)

    def search_symbols_by_kind(self, kind: str, project_only: bool = True) -> List[SymbolInfo]:
        self._ensure_connected()
        return self._symbol_repo.search_symbols_by_kind(kind, project_only)

    def get_symbol_stats(self) -> Dict[str, Any]:
        """
        Get detailed symbol statistics.

        Returns:
            Dict with statistics about symbols in database
        """
        try:
            self._ensure_connected()

            stats = {}

            # Total symbol count
            cursor = self._conn.execute("SELECT COUNT(*) FROM symbols")
            stats["total_symbols"] = cursor.fetchone()[0]

            # Count by kind
            cursor = self._conn.execute("""
                SELECT kind, COUNT(*) as count
                FROM symbols
                GROUP BY kind
                ORDER BY count DESC
            """)
            stats["by_kind"] = {row["kind"]: row["count"] for row in cursor.fetchall()}

            # Project vs dependencies
            cursor = self._conn.execute("""
                SELECT is_project, COUNT(*) as count
                FROM symbols
                GROUP BY is_project
            """)
            for row in cursor.fetchall():
                if row["is_project"]:
                    stats["project_symbols"] = row["count"]
                else:
                    stats["dependency_symbols"] = row["count"]

            # File count
            cursor = self._conn.execute("SELECT COUNT(*) FROM file_metadata")
            stats["total_files"] = cursor.fetchone()[0]

            # Database size
            cursor = self._conn.execute("PRAGMA page_count")
            page_count = cursor.fetchone()[0]
            cursor = self._conn.execute("PRAGMA page_size")
            page_size = cursor.fetchone()[0]
            stats["db_size_bytes"] = page_count * page_size
            stats["db_size_mb"] = stats["db_size_bytes"] / (1024 * 1024)

            return stats

        except Exception as e:
            diagnostics.error(f"Failed to get symbol stats: {e}")
            return {}

    def verify_integrity(self) -> bool:
        """
        Verify database integrity.

        Returns:
            True if database is healthy, False if corrupted
        """
        try:
            self._ensure_connected()

            cursor = self._conn.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]

            if result == "ok":
                diagnostics.debug("Database integrity check: OK")
                return True
            else:
                diagnostics.error(f"Database integrity check failed: {result}")
                return False

        except Exception as e:
            diagnostics.error(f"Failed to check integrity: {e}")
            return False

    # =========================================================================
    # Database Maintenance Methods
    # =========================================================================

    def vacuum(self) -> bool:
        """
        Reclaim space from deleted records and defragment database.

        VACUUM rebuilds the database file, repacking it into a minimal amount
        of disk space. This is useful after large deletions.

        Performance: Can take several seconds for large databases (100K+ symbols).
        Best run during idle time or as part of scheduled maintenance.

        Returns:
            True if successful, False otherwise
        """
        try:
            self._ensure_connected()

            # Get size before vacuum
            stats_before = self.get_symbol_stats()
            size_before_mb = stats_before.get("db_size_mb", 0)

            diagnostics.info(f"Running VACUUM (database size: {size_before_mb:.2f} MB)...")
            start_time = time.time()

            # Run VACUUM (cannot be in transaction)
            self._conn.execute("VACUUM")

            elapsed = time.time() - start_time

            # Get size after vacuum
            stats_after = self.get_symbol_stats()
            size_after_mb = stats_after.get("db_size_mb", 0)
            space_saved = size_before_mb - size_after_mb

            diagnostics.info(
                f"VACUUM complete in {elapsed:.2f}s. "
                f"Size: {size_before_mb:.2f} MB → {size_after_mb:.2f} MB "
                f"(saved {space_saved:.2f} MB)"
            )

            return True

        except Exception as e:
            diagnostics.error(f"VACUUM failed: {e}")
            return False

    def optimize(self) -> bool:
        """
        Optimize FTS5 indexes by rebuilding them.

        This is useful after large bulk inserts or updates to ensure
        optimal search performance.

        Performance: Can take 1-2 seconds for 100K symbols.

        Returns:
            True if successful, False otherwise
        """
        try:
            self._ensure_connected()

            diagnostics.info("Optimizing FTS5 indexes...")
            start_time = time.time()

            # Optimize FTS5 table
            self._conn.execute("INSERT INTO symbols_fts(symbols_fts) VALUES('optimize')")

            elapsed = time.time() - start_time
            diagnostics.info(f"FTS5 optimization complete in {elapsed:.2f}s")

            return True

        except Exception as e:
            diagnostics.error(f"FTS5 optimization failed: {e}")
            return False

    def rebuild_fts(self) -> bool:
        """
        Rebuild FTS5 index from scratch.

        This is needed after force re-indexing because INSERT OR REPLACE
        on the symbols table causes rowid changes, and FTS5 internal tables
        accumulate stale entries that are not cleaned up by the DELETE trigger.

        Unlike 'optimize' which only merges b-tree segments, 'rebuild'
        completely recreates the FTS index from the content table, removing
        all stale data and reclaiming space.

        Performance: Can take 1-2 seconds for 100K symbols.

        Returns:
            True if successful, False otherwise
        """
        try:
            self._ensure_connected()

            diagnostics.debug("Rebuilding FTS5 index...")
            start_time = time.time()

            # Rebuild FTS5 table completely
            self._conn.execute("INSERT INTO symbols_fts(symbols_fts) VALUES('rebuild')")

            elapsed = time.time() - start_time
            diagnostics.debug(f"FTS5 rebuild complete in {elapsed:.2f}s")

            return True

        except Exception as e:
            diagnostics.error(f"FTS5 rebuild failed: {e}")
            return False

    def analyze(self) -> bool:
        """
        Update query planner statistics for optimal query performance.

        ANALYZE gathers statistics about tables and indexes that SQLite's
        query optimizer uses to make better decisions about query plans.

        Performance: Fast, typically < 100ms for 100K symbols.

        Returns:
            True if successful, False otherwise
        """
        try:
            self._ensure_connected()

            diagnostics.info("Running ANALYZE...")
            start_time = time.time()

            # Analyze all tables
            self._conn.execute("ANALYZE")

            elapsed = time.time() - start_time
            diagnostics.info(f"ANALYZE complete in {elapsed:.2f}s")

            return True

        except Exception as e:
            diagnostics.error(f"ANALYZE failed: {e}")
            return False

    def auto_maintenance(
        self, vacuum_threshold_mb: float = 100.0, vacuum_min_waste_mb: float = 10.0
    ) -> Dict[str, Any]:
        """
        Run automatic maintenance based on database health.

        Decision rules:
        1. Always run ANALYZE (fast, always beneficial)
        2. Run OPTIMIZE if FTS5 table exists (improves search)
        3. Run VACUUM only if:
           - Database > vacuum_threshold_mb AND
           - Estimated waste > vacuum_min_waste_mb

        Args:
            vacuum_threshold_mb: Only vacuum if DB exceeds this size
            vacuum_min_waste_mb: Only vacuum if waste exceeds this amount

        Returns:
            Dict with maintenance actions taken and results
        """
        try:
            diagnostics.info("Running auto-maintenance...")
            results: Dict[str, Any] = {
                "analyze": False,
                "optimize": False,
                "vacuum": False,
                "vacuum_skipped_reason": None,
            }

            # Always run ANALYZE (fast)
            results["analyze"] = self.analyze()

            # Always run OPTIMIZE (relatively fast, improves search)
            results["optimize"] = self.optimize()

            # Conditionally run VACUUM
            stats = self.get_symbol_stats()
            db_size_mb = stats.get("db_size_mb", 0)

            if db_size_mb < vacuum_threshold_mb:
                results["vacuum_skipped_reason"] = (
                    f"Database too small ({db_size_mb:.2f} MB < {vacuum_threshold_mb} MB)"
                )
                diagnostics.info(results["vacuum_skipped_reason"])
            else:
                # Estimate wasted space (rough heuristic)
                # Get page count and freelist count
                cursor = self._conn.execute("PRAGMA freelist_count")
                freelist_count = cursor.fetchone()[0]
                cursor = self._conn.execute("PRAGMA page_size")
                page_size = cursor.fetchone()[0]

                waste_mb = (freelist_count * page_size) / (1024 * 1024)

                if waste_mb >= vacuum_min_waste_mb:
                    diagnostics.info(
                        f"Running VACUUM (DB: {db_size_mb:.2f} MB, waste: {waste_mb:.2f} MB)"
                    )
                    results["vacuum"] = self.vacuum()
                else:
                    results["vacuum_skipped_reason"] = (
                        f"Insufficient waste ({waste_mb:.2f} MB < {vacuum_min_waste_mb} MB)"
                    )
                    diagnostics.info(results["vacuum_skipped_reason"])

            diagnostics.info(f"Auto-maintenance complete: {results}")
            return results

        except Exception as e:
            diagnostics.error(f"Auto-maintenance failed: {e}")
            return {"error": str(e)}

    # =========================================================================
    # Health Check Methods
    # =========================================================================

    def check_integrity(self, full: bool = False) -> Tuple[bool, str]:
        """
        Check database integrity with detailed reporting.

        Args:
            full: If True, run full integrity check (slower but more thorough)

        Returns:
            Tuple of (is_healthy: bool, message: str)
        """
        try:
            self._ensure_connected()

            diagnostics.info(f"Running {'full' if full else 'quick'} integrity check...")
            start_time = time.time()

            if full:
                # Full integrity check
                cursor = self._conn.execute("PRAGMA integrity_check")
            else:
                # Quick check (faster)
                cursor = self._conn.execute("PRAGMA quick_check")

            results = [row[0] for row in cursor.fetchall()]
            elapsed = time.time() - start_time

            if results == ["ok"]:
                message = f"Integrity check passed in {elapsed:.2f}s"
                diagnostics.info(message)
                return True, message
            else:
                message = f"Integrity check FAILED: {', '.join(results[:5])}"
                if len(results) > 5:
                    message += f" (and {len(results) - 5} more issues)"
                diagnostics.error(message)
                return False, message

        except Exception as e:
            message = f"Integrity check error: {e}"
            diagnostics.error(message)
            return False, message

    def _check_fts5_health(self, health: Dict[str, Any], stats: Dict[str, Any]) -> None:
        """Check FTS5 index health and update health dict."""
        try:
            cursor = self._conn.execute("SELECT COUNT(*) FROM symbols_fts")
            fts_count = cursor.fetchone()[0]
            symbol_count = stats.get("total_symbols", 0)

            fts_health = {"fts_count": fts_count, "symbol_count": symbol_count, "status": "ok"}

            if fts_count != symbol_count:
                warning = (
                    f"FTS5 count mismatch: {fts_count} FTS vs {symbol_count} symbols. "
                    "Consider running optimize()."
                )
                health["warnings"].append(warning)
                fts_health["status"] = "warning"

            health["checks"]["fts_index"] = fts_health

        except Exception as e:
            health["errors"].append(f"FTS5 check failed: {e}")
            health["checks"]["fts_index"] = {"status": "error", "error": str(e)}

    def _check_wal_mode(self, health: Dict[str, Any]) -> None:
        """Check WAL journal mode and update health dict."""
        try:
            cursor = self._conn.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0].lower()

            wal_health = {
                "journal_mode": journal_mode,
                "status": "ok" if journal_mode == "wal" else "warning",
            }

            if journal_mode != "wal":
                warning = f"Journal mode is '{journal_mode}', expected 'wal' for best performance"
                health["warnings"].append(warning)

            health["checks"]["wal_mode"] = wal_health

        except Exception as e:
            health["errors"].append(f"WAL check failed: {e}")

    @staticmethod
    def _determine_overall_status(health: Dict[str, Any]) -> None:
        """Set overall health status based on errors and warnings."""
        if health["errors"]:
            health["status"] = "error"
        elif health["warnings"]:
            health["status"] = "warning"
        else:
            health["status"] = "healthy"

    def get_health_status(self) -> Dict[str, Any]:
        """
        Get comprehensive database health status.

        Returns:
            Dict with health metrics and status
        """
        try:
            self._ensure_connected()

            health: Dict[str, Any] = {
                "status": "unknown",
                "checks": {},
                "warnings": [],
                "errors": [],
            }

            # 1. Integrity check
            is_healthy, message = self.check_integrity(full=False)
            health["checks"]["integrity"] = {"passed": is_healthy, "message": message}
            if not is_healthy:
                health["errors"].append(f"Integrity: {message}")

            # 2. Database size check
            stats = self.get_symbol_stats()
            db_size_mb = stats.get("db_size_mb", 0)
            health["checks"]["size"] = {"db_size_mb": db_size_mb, "status": "ok"}

            if db_size_mb > 500:
                warning = f"Database is very large ({db_size_mb:.2f} MB)"
                health["warnings"].append(warning)
                health["checks"]["size"]["status"] = "warning"

            # 3. FTS5 index health
            self._check_fts5_health(health, stats)

            # 4. WAL mode check
            self._check_wal_mode(health)

            # 5. Table statistics
            health["checks"]["tables"] = self._get_table_sizes()

            self._determine_overall_status(health)

            return health

        except Exception as e:
            diagnostics.error(f"Failed to get health status: {e}")
            return {"status": "error", "errors": [str(e)]}

    def _get_table_sizes(self) -> Dict[str, Dict[str, Any]]:
        """
        Get size information for all tables.

        Returns:
            Dict mapping table names to size info
        """
        try:
            tables = {}

            # Get list of tables
            cursor = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            table_names = [row[0] for row in cursor.fetchall()]

            for table_name in table_names:
                try:
                    # Get row count
                    cursor = self._conn.execute(f"SELECT COUNT(*) FROM {table_name}")
                    row_count = cursor.fetchone()[0]

                    tables[table_name] = {"row_count": row_count, "status": "ok"}

                except Exception as e:
                    tables[table_name] = {"error": str(e), "status": "error"}

            return tables

        except Exception as e:
            diagnostics.error(f"Failed to get table sizes: {e}")
            return {}

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive cache statistics (enhanced version).

        Returns:
            Dict with detailed cache statistics
        """
        try:
            self._ensure_connected()

            stats = {}

            # Basic symbol stats (reuse existing method)
            symbol_stats = self.get_symbol_stats()
            stats.update(symbol_stats)

            # File statistics
            cursor = self._conn.execute("""
                SELECT
                    COUNT(*) as total_files,
                    SUM(symbol_count) as total_symbols_from_files,
                    AVG(symbol_count) as avg_symbols_per_file,
                    MAX(symbol_count) as max_symbols_in_file
                FROM file_metadata
            """)
            row = cursor.fetchone()
            stats["file_stats"] = {
                "total_files": row[0] or 0,
                "total_symbols_from_files": row[1] or 0,
                "avg_symbols_per_file": round(row[2], 2) if row[2] else 0,
                "max_symbols_in_file": row[3] or 0,
            }

            # Top files by symbol count
            cursor = self._conn.execute("""
                SELECT file_path, symbol_count
                FROM file_metadata
                ORDER BY symbol_count DESC
                LIMIT 10
            """)
            stats["top_files"] = [
                {"file": row[0], "symbol_count": row[1]} for row in cursor.fetchall()
            ]

            # Cache metadata
            cursor = self._conn.execute("SELECT key, value FROM cache_metadata")
            stats["metadata"] = {row[0]: row[1] for row in cursor.fetchall()}

            # Performance metrics
            stats["performance"] = {
                "db_path": str(self.db_path),
                "connection_timeout": self._connection_timeout,
                "last_access_age_seconds": time.time() - self._last_access,
            }

            return stats

        except Exception as e:
            diagnostics.error(f"Failed to get cache stats: {e}")
            return {}

    def monitor_performance(self, operation: str = "search") -> Dict[str, float]:
        """
        Monitor database performance with sample queries.

        Args:
            operation: Type of operation to test ('search', 'load', 'write')

        Returns:
            Dict with performance metrics (times in milliseconds)
        """
        try:
            self._ensure_connected()

            metrics = {}

            if operation == "search":
                # Test FTS5 search performance
                start = time.time()
                cursor = self._conn.execute(
                    "SELECT COUNT(*) FROM symbols_fts WHERE name MATCH 'test*'"
                )
                cursor.fetchone()
                metrics["fts_search_ms"] = (time.time() - start) * 1000

                # Test regular search
                start = time.time()
                cursor = self._conn.execute("SELECT COUNT(*) FROM symbols WHERE name LIKE 'test%'")
                cursor.fetchone()
                metrics["like_search_ms"] = (time.time() - start) * 1000

            elif operation == "load":
                # Test symbol load by USR
                # Get a random USR first
                cursor = self._conn.execute("SELECT usr FROM symbols LIMIT 1")
                row = cursor.fetchone()
                if row:
                    usr = row[0]
                    start = time.time()
                    cursor = self._conn.execute("SELECT * FROM symbols WHERE usr = ?", (usr,))
                    cursor.fetchone()
                    metrics["load_by_usr_ms"] = (time.time() - start) * 1000

            elif operation == "write":
                # Test write performance (rollback to avoid changes)
                # Build a raw tuple matching the symbols table column order
                # instead of creating a domain SymbolInfo object.
                test_tuple = (
                    "perf_test_usr",  # usr
                    "PerfTestSymbol",  # name
                    "",  # qualified_name
                    "function",  # kind
                    "/test/perf.cpp",  # file
                    1,  # line
                    1,  # column
                    "void PerfTestSymbol",  # signature
                    True,  # is_project
                    "",  # namespace
                    "public",  # access
                    "",  # parent_class
                    "[]",  # base_classes
                    False,  # is_template_specialization
                    False,  # is_template
                    None,  # template_kind
                    None,  # template_parameters
                    None,  # primary_template_usr
                    1,  # start_line
                    1,  # end_line
                    None,  # header_file
                    None,  # header_line
                    None,  # header_start_line
                    None,  # header_end_line
                    True,  # is_definition
                    False,  # is_virtual
                    False,  # is_pure_virtual
                    False,  # is_const
                    False,  # is_static
                    None,  # brief
                    None,  # doc_comment
                    time.time(),  # created_at
                    time.time(),  # updated_at
                )

                start = time.time()
                # Use savepoint to rollback
                self._conn.execute("SAVEPOINT perf_test")
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO symbols (
                        usr, name, qualified_name, kind, file, line, column, signature,
                        is_project, namespace, access, parent_class,
                        base_classes, is_template_specialization,
                        is_template, template_kind, template_parameters, primary_template_usr,
                        start_line, end_line, header_file, header_line,
                        header_start_line, header_end_line, is_definition,
                        is_virtual, is_pure_virtual, is_const, is_static,
                        brief, doc_comment,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    test_tuple,
                )
                self._conn.execute("ROLLBACK TO perf_test")
                metrics["write_symbol_ms"] = (time.time() - start) * 1000

            return metrics

        except Exception as e:
            diagnostics.error(f"Performance monitoring failed: {e}")
            return {}

    # =========================================================================
    # CacheBackend Protocol Adapter Methods
    # =========================================================================

    def save_cache(
        self,
        class_index: Dict[str, List],
        function_index: Dict[str, List],
        file_hashes: Dict[str, str],
        indexed_file_count: int,
        include_dependencies: bool = False,
        config_file_path: Optional[Path] = None,
        config_file_mtime: Optional[float] = None,
        compile_commands_path: Optional[Path] = None,
        compile_commands_mtime: Optional[float] = None,
    ) -> bool:
        """
        Save indexes to SQLite cache (CacheBackend protocol method).

        Adapts CacheManager's save_cache interface to SQLite backend.

        Args:
            class_index: Dict mapping class names to SymbolInfo lists
            function_index: Dict mapping function names to SymbolInfo lists
            file_hashes: Dict mapping file paths to content hashes
            indexed_file_count: Number of files indexed
            include_dependencies: Whether dependencies were included
            config_file_path: Path to config file
            config_file_mtime: Config file modification time
            compile_commands_path: Path to compile_commands.json
            compile_commands_mtime: compile_commands.json modification time

        Returns:
            True if successful, False otherwise
        """
        try:
            self._ensure_connected()

            # Collect all symbols from both indexes
            all_symbols = []
            for symbols in class_index.values():
                all_symbols.extend(symbols)
            for symbols in function_index.values():
                all_symbols.extend(symbols)

            # Save symbols in batch
            if all_symbols:
                self.save_symbols_batch(all_symbols)

            # Save file metadata
            for file_path, file_hash in file_hashes.items():
                # Count symbols for this file
                symbol_count = sum(1 for s in all_symbols if s.file == file_path)
                self.update_file_metadata(file_path, file_hash, None, symbol_count)

            # Save cache metadata
            self.update_cache_metadata("include_dependencies", str(include_dependencies))
            self.update_cache_metadata("indexed_file_count", str(indexed_file_count))
            if config_file_path:
                self.update_cache_metadata("config_file_path", str(config_file_path))
                self.update_cache_metadata("config_file_mtime", str(config_file_mtime))
            if compile_commands_path:
                self.update_cache_metadata("compile_commands_path", str(compile_commands_path))
                self.update_cache_metadata("compile_commands_mtime", str(compile_commands_mtime))

            return True

        except Exception as e:
            diagnostics.error(f"Failed to save cache: {e}")
            return False

    def _check_config_changes(
        self, config_file_path: Optional[Path], config_file_mtime: Optional[float]
    ) -> bool:
        """Check if config file has changed since caching."""
        cached_config = self.get_cache_metadata("config_file_path")
        if config_file_path:
            if cached_config != str(config_file_path):
                diagnostics.info("Configuration file path changed")
                return False
            cached_mtime = self.get_cache_metadata("config_file_mtime")
            if cached_mtime and cached_mtime != str(config_file_mtime):
                diagnostics.info("Configuration file modified")
                return False
        elif cached_config:
            # Config was cached but not provided on load - invalidate
            diagnostics.info("Configuration file was cached but not provided")
            return False
        return True

    def _check_compile_commands_changes(
        self, compile_commands_path: Optional[Path], compile_commands_mtime: Optional[float]
    ) -> bool:
        """Check if compile_commands.json has changed since caching."""
        cached_cc = self.get_cache_metadata("compile_commands_path")
        if compile_commands_path:
            if cached_cc != str(compile_commands_path):
                diagnostics.info("compile_commands.json path changed")
                return False
            cached_cc_mtime = self.get_cache_metadata("compile_commands_mtime")
            if cached_cc_mtime and cached_cc_mtime != str(compile_commands_mtime):
                diagnostics.info("compile_commands.json modified")
                return False
        elif cached_cc:
            # Compile commands was cached but not provided on load - invalidate
            diagnostics.info("compile_commands.json was cached but not provided")
            return False
        return True

    def _validate_cache_metadata(
        self,
        include_dependencies: bool,
        config_file_path: Optional[Path],
        config_file_mtime: Optional[float],
        compile_commands_path: Optional[Path],
        compile_commands_mtime: Optional[float],
    ) -> bool:
        """Validate if the cache metadata matches the current configuration."""
        # Check if cache has been initialized (has metadata)
        cached_deps = self.get_cache_metadata("include_dependencies")
        if cached_deps is None:
            # No cache metadata - cache is empty/uninitialized
            return False

        # Check cache metadata for compatibility
        if cached_deps != str(include_dependencies):
            diagnostics.info(
                f"Cache dependencies mismatch: {cached_deps} != {include_dependencies}"
            )
            return False

        if not self._check_config_changes(config_file_path, config_file_mtime):
            return False

        if not self._check_compile_commands_changes(compile_commands_path, compile_commands_mtime):
            return False

        return True

    def _load_symbols_from_db(self) -> Tuple[Dict[str, List[Any]], Dict[str, List[Any]]]:
        """Load symbols from database and build class and function indexes."""
        cursor = self._conn.execute("SELECT * FROM symbols")

        from collections import defaultdict

        class_index = defaultdict(list)
        function_index = defaultdict(list)

        for row in cursor:
            symbol = self._row_to_symbol(row)
            if symbol.kind in (
                "class",
                "struct",
                "union",
                "enum",
                "class_template",
                "partial_specialization",
            ):
                class_index[symbol.name].append(symbol)
            elif symbol.kind in (
                "function",
                "method",
                "constructor",
                "destructor",
                "function_template",
            ):
                function_index[symbol.name].append(symbol)

        return dict(class_index), dict(function_index)

    def load_cache(
        self,
        include_dependencies: bool = False,
        config_file_path: Optional[Path] = None,
        config_file_mtime: Optional[float] = None,
        compile_commands_path: Optional[Path] = None,
        compile_commands_mtime: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Load cache from SQLite if valid (CacheBackend protocol method).

        Adapts CacheManager's load_cache interface to SQLite backend.

        Args:
            include_dependencies: Whether dependencies should be included
            config_file_path: Path to config file
            config_file_mtime: Config file modification time
            compile_commands_path: Path to compile_commands.json
            compile_commands_mtime: compile_commands.json modification time

        Returns:
            Dict with cache data, or None if cache invalid/missing
        """
        try:
            self._ensure_connected()

            is_valid = self._validate_cache_metadata(
                include_dependencies,
                config_file_path,
                config_file_mtime,
                compile_commands_path,
                compile_commands_mtime,
            )
            if not is_valid:
                return None

            class_index, function_index = self._load_symbols_from_db()

            # Load file hashes
            file_hashes = self.load_all_file_hashes()

            # Get indexed file count
            indexed_count = self.get_cache_metadata("indexed_file_count")

            return {
                "version": "2.0",
                "include_dependencies": include_dependencies,
                "config_file_path": str(config_file_path) if config_file_path else None,
                "config_file_mtime": config_file_mtime,
                "compile_commands_path": (
                    str(compile_commands_path) if compile_commands_path else None
                ),
                "compile_commands_mtime": compile_commands_mtime,
                "class_index": class_index,
                "function_index": function_index,
                "file_hashes": file_hashes,
                "indexed_file_count": int(indexed_count) if indexed_count else 0,
                "timestamp": time.time(),
            }

        except Exception as e:
            diagnostics.error(f"Failed to load cache: {e}")
            return None

    def save_file_cache(
        self,
        file_path: str,
        symbols: List,
        file_hash: str,
        compile_args_hash: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        retry_count: int = 0,
    ) -> bool:
        """
        Save parsed symbols for a single file (CacheBackend protocol method).

        Args:
            file_path: Path to the source file
            symbols: List of SymbolInfo objects (may be empty if failed)
            file_hash: Hash of the file content
            compile_args_hash: Hash of compilation arguments
            success: Whether parsing succeeded
            error_message: Error message if parsing failed
            retry_count: Number of retry attempts

        Returns:
            True if successful, False otherwise
        """
        try:
            # Delete existing symbols for this file
            self.delete_symbols_by_file(file_path)

            # Save new symbols
            if symbols:
                self.save_symbols_batch(symbols)

            # Update file metadata with success/failure information
            self.update_file_metadata(
                file_path,
                file_hash,
                compile_args_hash,
                len(symbols),
                success,
                error_message,
                retry_count,
            )

            return True

        except Exception as e:
            diagnostics.error(f"Failed to save file cache for {file_path}: {e}")
            return False

    def load_file_cache(
        self, file_path: str, current_hash: str, compile_args_hash: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Load cached data for a file if hash matches (CacheBackend protocol method).

        Args:
            file_path: Path to the source file
            current_hash: Current hash of the file content
            compile_args_hash: Current hash of compilation arguments

        Returns:
            Dict with symbols and metadata, or None if cache invalid
        """
        try:
            # Get file metadata
            metadata = self.get_file_metadata(file_path)
            if not metadata:
                return None

            # Check file hash
            if metadata["file_hash"] != current_hash:
                return None

            # Check compile args hash
            if compile_args_hash and metadata.get("compile_args_hash") != compile_args_hash:
                return None

            # Load symbols for this file
            symbols = self.search_symbols_by_file(file_path)

            return {
                "symbols": symbols,
                "success": metadata.get("success", True),
                "error_message": metadata.get("error_message"),
                "retry_count": metadata.get("retry_count", 0),
            }

        except Exception as e:
            diagnostics.error(f"Failed to load file cache for {file_path}: {e}")
            return None

    def remove_file_cache(self, file_path: str) -> bool:
        """
        Remove cached data for a deleted file (CacheBackend protocol method).

        Args:
            file_path: Path to the file to remove

        Returns:
            True if successful, False otherwise
        """
        try:
            # Delete symbols
            self.delete_symbols_by_file(file_path)

            # Delete call sites
            self.delete_call_sites_by_file(file_path)

            # Delete file metadata
            self._ensure_connected()
            with self._conn:
                self._conn.execute("DELETE FROM file_metadata WHERE file_path = ?", (file_path,))

            return True

        except Exception as e:
            diagnostics.error(f"Failed to remove file cache for {file_path}: {e}")
            return False

    # Phase 3: Call Sites Methods (v8.0)

    def save_call_sites_batch(self, call_sites: List[Dict[str, Any]]) -> int:
        """
        Batch insert call sites using transaction.

        Args:
            call_sites: List of dicts with keys:
                - caller_usr: USR of calling function
                - callee_usr: USR of called function
                - file: Source file containing call
                - line: Line number of call
                - column: Column number (optional)

        Returns:
            Number of call sites successfully saved
        """
        if not call_sites:
            return 0

        try:
            self._ensure_connected()

            current_time = time.time()

            # Prepare tuples for batch insert
            values = [
                (
                    cs["caller_usr"],
                    cs["callee_usr"],
                    cs["file"],
                    cs["line"],
                    cs.get("column"),
                    cs.get("display_name"),
                    cs.get("template_project_types"),
                    current_time,
                )
                for cs in call_sites
            ]

            # Batch insert in a single transaction
            with self._conn:
                self._conn.executemany(
                    """
                    INSERT INTO call_sites (
                        caller_usr, callee_usr, file, line, column,
                        display_name, template_project_types, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )

            return len(call_sites)

        except Exception as e:
            diagnostics.error(f"Failed to batch save {len(call_sites)} call sites: {e}")
            return 0

    def get_call_sites_for_caller(self, caller_usr: str) -> List[Dict[str, Any]]:
        """
        Get all call sites from a specific caller function.

        Args:
            caller_usr: USR of the calling function

        Returns:
            List of call site dicts with keys: callee_usr, file, line, column
        """
        try:
            self._ensure_connected()

            cursor = self._conn.execute(
                """
                SELECT callee_usr, file, line, column,
                       display_name, template_project_types
                FROM call_sites
                WHERE caller_usr = ?
                ORDER BY file, line
                """,
                (caller_usr,),
            )

            return [
                {
                    "callee_usr": row["callee_usr"],
                    "file": row["file"],
                    "line": row["line"],
                    "column": row["column"],
                    "display_name": row["display_name"],
                    "template_project_types": row["template_project_types"],
                }
                for row in cursor.fetchall()
            ]

        except Exception as e:
            diagnostics.error(f"Failed to get call sites for caller {caller_usr}: {e}")
            return []

    def get_call_sites_for_callee(self, callee_usr: str) -> List[Dict[str, Any]]:
        """
        Get all call sites to a specific callee function.

        Args:
            callee_usr: USR of the called function

        Returns:
            List of call site dicts with keys: caller_usr, file, line, column
        """
        try:
            self._ensure_connected()

            cursor = self._conn.execute(
                """
                SELECT caller_usr, file, line, column,
                       display_name, template_project_types
                FROM call_sites
                WHERE callee_usr = ?
                ORDER BY file, line
                """,
                (callee_usr,),
            )

            return [
                {
                    "caller_usr": row["caller_usr"],
                    "file": row["file"],
                    "line": row["line"],
                    "column": row["column"],
                    "display_name": row["display_name"],
                    "template_project_types": row["template_project_types"],
                }
                for row in cursor.fetchall()
            ]

        except Exception as e:
            diagnostics.error(f"Failed to get call sites for callee {callee_usr}: {e}")
            return []

    def get_template_mediated_call_sites(
        self, caller_usrs: List[str], callee_usr: str
    ) -> List[Dict[str, Any]]:
        """
        Get call sites between specific callers and a callee that have template metadata.

        Args:
            caller_usrs: List of caller USRs
            callee_usr: USR of the called function

        Returns:
            List of call site dicts with template_project_types set
        """
        if not caller_usrs:
            return []
        try:
            self._ensure_connected()
            placeholders = ",".join("?" for _ in caller_usrs)
            cursor = self._conn.execute(
                f"""
                SELECT caller_usr, callee_usr, file, line, column,
                       display_name, template_project_types
                FROM call_sites
                WHERE caller_usr IN ({placeholders})
                  AND callee_usr = ?
                  AND template_project_types IS NOT NULL
                ORDER BY file, line
                """,
                (*caller_usrs, callee_usr),
            )
            return [
                {
                    "caller_usr": row["caller_usr"],
                    "callee_usr": row["callee_usr"],
                    "file": row["file"],
                    "line": row["line"],
                    "column": row["column"],
                    "display_name": row["display_name"],
                    "template_project_types": row["template_project_types"],
                }
                for row in cursor.fetchall()
            ]
        except Exception as e:
            diagnostics.error(
                f"Failed to get template-mediated call sites for callee {callee_usr}: {e}"
            )
            return []

    def delete_call_sites_by_file(self, file_path: str) -> int:
        """
        Delete all call sites from a specific file.

        Args:
            file_path: Path to file whose call sites should be deleted

        Returns:
            Number of call sites deleted
        """
        try:
            self._ensure_connected()

            # Get count before deletion
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM call_sites WHERE file = ?", (file_path,)
            )
            count: int = cursor.fetchone()[0]

            if count == 0:
                return 0

            # Delete call sites
            with self._conn:
                self._conn.execute("DELETE FROM call_sites WHERE file = ?", (file_path,))

            return count

        except Exception as e:
            diagnostics.error(f"Failed to delete call sites for file {file_path}: {e}")
            return 0

    def delete_call_sites_by_usr(self, usr: str) -> int:
        """
        Delete all call sites where the given USR appears as either caller or callee.

        Used during incremental refresh when removing symbols.

        Args:
            usr: USR of the symbol to remove from call graph

        Returns:
            Number of call sites deleted
        """
        try:
            self._ensure_connected()

            # Get count before deletion
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM call_sites WHERE caller_usr = ? OR callee_usr = ?",
                (usr, usr),
            )
            count: int = cursor.fetchone()[0]

            if count == 0:
                return 0

            # Delete call sites where USR is either caller or callee
            with self._conn:
                self._conn.execute(
                    "DELETE FROM call_sites WHERE caller_usr = ? OR callee_usr = ?", (usr, usr)
                )

            return count

        except Exception as e:
            diagnostics.error(f"Failed to delete call sites for USR {usr}: {e}")
            return 0

    def load_all_call_sites(self) -> List[Dict[str, Any]]:
        """
        Load all call sites from the database.

        Returns:
            List of call site dicts with keys: caller_usr, callee_usr, file, line, column
        """
        try:
            self._ensure_connected()

            cursor = self._conn.execute("""
                SELECT caller_usr, callee_usr, file, line, column
                FROM call_sites
                ORDER BY file, line
                """)

            return [
                {
                    "caller_usr": row["caller_usr"],
                    "callee_usr": row["callee_usr"],
                    "file": row["file"],
                    "line": row["line"],
                    "column": row["column"],
                }
                for row in cursor.fetchall()
            ]

        except Exception as e:
            diagnostics.error(f"Failed to load call sites from database: {e}")
            return []

    # -------------------------------------------------------------------------
    # Type Aliases Storage and Lookup (Phase 1.3: Type Alias Tracking)
    # -------------------------------------------------------------------------

    def save_type_aliases_batch(self, aliases: List[Dict[str, Any]]) -> int:
        """Batch insert type aliases using transaction."""
        self._ensure_connected()
        return type_alias_repository.save_type_aliases_batch(self._conn, aliases)

    def get_aliases_for_canonical(self, canonical_type: str) -> List[str]:
        """Get all alias names that resolve to a given canonical type."""
        self._ensure_connected()
        return type_alias_repository.get_aliases_for_canonical(self._conn, canonical_type)

    def get_canonical_for_alias(self, alias_name: str) -> Optional[str]:
        """Get canonical type for a given alias name (short or qualified)."""
        self._ensure_connected()
        return type_alias_repository.get_canonical_for_alias(self._conn, alias_name)

    def get_type_alias_info(self, type_name: str) -> Optional[Dict[str, Any]]:
        """Get high-level info for a known alias from the type_aliases table."""
        self._ensure_connected()
        return type_alias_repository.get_type_alias_info(self._conn, type_name)

    def get_type_alias_details(self, alias_names: List[str]) -> List[Dict[str, Any]]:
        """Get detailed records from the type_aliases table for a list of alias names."""
        self._ensure_connected()
        return type_alias_repository.get_type_alias_details(self._conn, alias_names)

    def get_all_cached_file_paths(self) -> Set[str]:
        """
        Return all file paths stored in file_metadata table.

        Used by ChangeScanner to identify cached files for diff analysis.

        Returns:
            Set of file paths
        """
        try:
            self._ensure_connected()
            cursor = self._conn.execute("SELECT file_path FROM file_metadata")
            return {row[0] for row in cursor.fetchall()}
        except Exception as e:
            diagnostics.warning(f"Failed to get cached file paths: {e}")
            return set()

    def set_compile_args_hash(self, file_path: str, args_hash: str) -> bool:
        """
        Store or update the compile arguments hash for a file.

        Phase 1.4: Compile Commands Integration

        Args:
            file_path: Source file path
            args_hash: Hash of the compile arguments

        Returns:
            True if successful, False otherwise
        """
        try:
            self._ensure_connected()
            cursor = self._conn.execute(
                """
                UPDATE file_metadata
                SET compile_args_hash = ?
                WHERE file_path = ?
                """,
                (args_hash, file_path),
            )
            if cursor.rowcount == 0:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO file_metadata
                    (file_path, file_hash, compile_args_hash, indexed_at, symbol_count)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (file_path, "", args_hash, time.time(), 0),
                )
            self._conn.commit()
            return True
        except Exception as e:
            diagnostics.warning(f"Failed to set compile args hash for {file_path}: {e}")
            self._conn.rollback()
            return False

    def get_compile_args_hash(self, file_path: str) -> Optional[str]:
        """
        Return the stored compile arguments hash for a file.

        Phase 1.4: Compile Commands Integration

        Args:
            file_path: Source file path

        Returns:
            Args hash string or None if not found
        """
        try:
            self._ensure_connected()
            cursor = self._conn.execute(
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
        """
        Clear all stored compile arguments hashes from file_metadata.

        Phase 1.4: Compile Commands Integration

        Returns:
            Number of rows cleared
        """
        try:
            self._ensure_connected()
            cursor = self._conn.execute("""
                UPDATE file_metadata
                SET compile_args_hash = NULL
                """)
            cleared = cursor.rowcount or 0
            self._conn.commit()
            return cleared
        except Exception as e:
            diagnostics.warning(f"Failed to clear compile args hashes: {e}")
            self._conn.rollback()
            return 0

    def get_all_alias_mappings(self) -> Dict[str, str]:
        """Get all alias → canonical mappings."""
        self._ensure_connected()
        return type_alias_repository.get_all_alias_mappings(self._conn)
