"""SQLite-based cache backend for C++ analyzer."""

import fcntl
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .._symbols.model import SymbolInfo
from .._symbols.ports.parser import TypeAliasRecord
from .._persistence import type_alias_repository
from .._persistence.repositories.symbol_repository import SymbolRepository
from .._persistence.repositories.call_site_repository import CallSiteRepository
from .._persistence.repositories.file_metadata_repository import FileMetadataRepository
from .._persistence.repositories.maintenance_service import MaintenanceService

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
        self._call_site_repo = CallSiteRepository(self.get_connection)
        self._file_metadata_repo = FileMetadataRepository(self.get_connection)
        self._maintenance = MaintenanceService(self.get_connection)

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
        self._ensure_connected()
        return self._file_metadata_repo.update_file_metadata(
            file_path,
            file_hash,
            compile_args_hash,
            symbol_count,
            success,
            error_message,
            retry_count,
        )

    def get_file_metadata(self, file_path: str) -> Optional[Dict[str, Any]]:
        self._ensure_connected()
        return self._file_metadata_repo.get_file_metadata(file_path)

    def load_all_file_hashes(self) -> Dict[str, str]:
        self._ensure_connected()
        return self._file_metadata_repo.load_all_file_hashes()

    def update_cache_metadata(self, key: str, value: str) -> bool:
        self._ensure_connected()
        return self._file_metadata_repo.update_cache_metadata(key, value)

    def get_cache_metadata(self, key: str) -> Optional[str]:
        self._ensure_connected()
        return self._file_metadata_repo.get_cache_metadata(key)

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
        self._ensure_connected()
        return self._maintenance.get_symbol_stats()

    def verify_integrity(self) -> bool:
        self._ensure_connected()
        return self._maintenance.verify_integrity()

    def vacuum(self) -> bool:
        self._ensure_connected()
        return self._maintenance.vacuum()

    def optimize(self) -> bool:
        self._ensure_connected()
        return self._maintenance.optimize()

    def rebuild_fts(self) -> bool:
        self._ensure_connected()
        return self._maintenance.rebuild_fts()

    def analyze(self) -> bool:
        self._ensure_connected()
        return self._maintenance.analyze()

    def auto_maintenance(
        self, vacuum_threshold_mb: float = 100.0, vacuum_min_waste_mb: float = 10.0
    ) -> Dict[str, Any]:
        self._ensure_connected()
        return self._maintenance.auto_maintenance(vacuum_threshold_mb, vacuum_min_waste_mb)

    def check_integrity(self, full: bool = False) -> Tuple[bool, str]:
        self._ensure_connected()
        return self._maintenance.check_integrity(full)

    def _check_fts5_health(self, health: Dict[str, Any], stats: Dict[str, Any]) -> None:
        self._maintenance._check_fts5_health(health, stats)

    def _check_wal_mode(self, health: Dict[str, Any]) -> None:
        self._maintenance._check_wal_mode(health)

    @staticmethod
    def _determine_overall_status(health: Dict[str, Any]) -> None:
        MaintenanceService._determine_overall_status(health)

    def get_health_status(self) -> Dict[str, Any]:
        self._ensure_connected()
        return self._maintenance.get_health_status()

    def _get_table_sizes(self) -> Dict[str, Dict[str, Any]]:
        return self._maintenance._get_table_sizes()

    def get_cache_stats(self) -> Dict[str, Any]:
        self._ensure_connected()
        return self._maintenance.get_cache_stats(
            db_path=str(self.db_path),
            connection_timeout=self._connection_timeout,
            last_access=self._last_access,
        )

    def monitor_performance(self, operation: str = "search") -> Dict[str, float]:
        self._ensure_connected()
        return self._maintenance.monitor_performance(operation)

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
        self._ensure_connected()
        return self._call_site_repo.save_call_sites_batch(call_sites)

    def get_call_sites_for_caller(self, caller_usr: str) -> List[Dict[str, Any]]:
        self._ensure_connected()
        return self._call_site_repo.get_call_sites_for_caller(caller_usr)

    def get_call_sites_for_callee(self, callee_usr: str) -> List[Dict[str, Any]]:
        self._ensure_connected()
        return self._call_site_repo.get_call_sites_for_callee(callee_usr)

    def get_template_mediated_call_sites(
        self, caller_usrs: List[str], callee_usr: str
    ) -> List[Dict[str, Any]]:
        self._ensure_connected()
        return self._call_site_repo.get_template_mediated_call_sites(caller_usrs, callee_usr)

    def delete_call_sites_by_file(self, file_path: str) -> int:
        self._ensure_connected()
        return self._call_site_repo.delete_call_sites_by_file(file_path)

    def delete_call_sites_by_usr(self, usr: str) -> int:
        self._ensure_connected()
        return self._call_site_repo.delete_call_sites_by_usr(usr)

    def load_all_call_sites(self) -> List[Dict[str, Any]]:
        self._ensure_connected()
        return self._call_site_repo.load_all_call_sites()

    # -------------------------------------------------------------------------
    # Type Aliases Storage and Lookup (Phase 1.3: Type Alias Tracking)
    # -------------------------------------------------------------------------

    def save_type_aliases_batch(self, aliases: List[TypeAliasRecord]) -> int:
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
        self._ensure_connected()
        return self._file_metadata_repo.get_all_cached_file_paths()

    def set_compile_args_hash(self, file_path: str, args_hash: str) -> bool:
        self._ensure_connected()
        return self._file_metadata_repo.set_compile_args_hash(file_path, args_hash)

    def get_compile_args_hash(self, file_path: str) -> Optional[str]:
        self._ensure_connected()
        return self._file_metadata_repo.get_compile_args_hash(file_path)

    def clear_compile_args_hashes(self) -> int:
        self._ensure_connected()
        return self._file_metadata_repo.clear_compile_args_hashes()

    def get_all_alias_mappings(self) -> Dict[str, str]:
        """Get all alias → canonical mappings."""
        self._ensure_connected()
        return type_alias_repository.get_all_alias_mappings(self._conn)
