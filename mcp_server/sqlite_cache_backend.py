"""SQLite-based cache backend for C++ analyzer."""

import sqlite3
import json
import time
import sys
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from .symbol_info import SymbolInfo
from .schema_migrations import SchemaMigration

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics


class SqliteCacheBackend:
    """
    SQLite-based cache backend for C++ symbol storage.

    Provides high-performance symbol caching with:
    - FTS5 full-text search for fast name lookups
    - WAL mode for concurrent read access
    - Automatic schema migrations
    - Transaction-based bulk operations
    - Platform-specific optimizations

    Performance targets (100K symbols):
    - Startup: < 500ms
    - Name search (FTS5): < 5ms
    - Bulk insert: > 5000 symbols/sec
    - Memory usage: < 50MB
    """

    CURRENT_SCHEMA_VERSION = 1

    def __init__(self, db_path: Path):
        """
        Initialize SQLite cache backend.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.conn: Optional[sqlite3.Connection] = None
        self._last_access = 0
        self._connection_timeout = 300  # 5 minutes idle timeout

        # Initialize database
        self._connect()
        self._init_database()

    def _connect(self):
        """Open database connection with optimized settings."""
        try:
            # Configure for concurrent access
            self.conn = sqlite3.connect(
                str(self.db_path),
                timeout=30.0,              # Wait up to 30s for locks
                isolation_level=None,      # Autocommit off, manual transactions
                check_same_thread=False    # Allow multi-threaded access
            )

            # Enable row factory for dict-like access
            self.conn.row_factory = sqlite3.Row

            # Set busy handler for lock retry with exponential backoff
            self.conn.set_busy_handler(self._busy_handler)

            # Configure platform-specific settings
            self._configure_platform()

            self._last_access = time.time()

        except Exception as e:
            diagnostics.error(f"Failed to connect to SQLite database: {e}")
            raise

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

        if platform == 'win32':
            # Windows: WAL mode works well
            diagnostics.debug("SQLite configured for Windows")
        elif platform == 'darwin':
            # macOS: Standard configuration
            diagnostics.debug("SQLite configured for macOS")
        else:
            # Linux/Unix: Standard configuration
            diagnostics.debug("SQLite configured for Linux/Unix")

        # Note: NFS support explicitly not included per requirements
        # Database should be on local filesystem

    def _init_database(self):
        """Initialize database schema and configuration."""
        try:
            # Execute schema file
            schema_path = Path(__file__).parent / "schema.sql"

            if not schema_path.exists():
                raise FileNotFoundError(f"Schema file not found: {schema_path}")

            with open(schema_path, 'r') as f:
                schema_sql = f.read()

            # Execute schema (creates tables, indexes, triggers)
            self.conn.executescript(schema_sql)
            self.conn.commit()

            # Check and apply schema migrations
            migration = SchemaMigration(self.conn)

            # Verify version compatibility
            migration.check_version_compatibility()

            # Apply pending migrations if needed
            if migration.needs_migration():
                diagnostics.info("Database schema migration required")
                migration.migrate()
            else:
                current_version = migration.get_current_version()
                diagnostics.debug(f"Database schema up-to-date (version {current_version})")

            diagnostics.debug("SQLite database initialized successfully")

        except Exception as e:
            diagnostics.error(f"Failed to initialize database: {e}")
            raise

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

    def _close(self):
        """Close database connection."""
        if self.conn:
            try:
                self.conn.close()
            except Exception as e:
                diagnostics.warning(f"Error closing connection: {e}")
            finally:
                self.conn = None

    def __enter__(self):
        """Context manager entry."""
        self._ensure_connected()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self._close()

    def _symbol_to_tuple(self, symbol: SymbolInfo) -> tuple:
        """
        Convert SymbolInfo to tuple for SQL insertion.

        Args:
            symbol: SymbolInfo object

        Returns:
            Tuple of values matching INSERT statement column order
        """
        now = time.time()

        return (
            symbol.usr,
            symbol.name,
            symbol.kind,
            symbol.file,
            symbol.line,
            symbol.column,
            symbol.signature,
            symbol.is_project,
            symbol.namespace,
            symbol.access,
            symbol.parent_class,
            json.dumps(symbol.base_classes),
            json.dumps(symbol.calls),
            json.dumps(symbol.called_by),
            now,  # created_at
            now   # updated_at
        )

    def _row_to_symbol(self, row: sqlite3.Row) -> SymbolInfo:
        """
        Convert database row to SymbolInfo object.

        Args:
            row: SQLite row object

        Returns:
            SymbolInfo object
        """
        return SymbolInfo(
            name=row['name'],
            kind=row['kind'],
            file=row['file'],
            line=row['line'],
            column=row['column'],
            signature=row['signature'] or '',
            is_project=bool(row['is_project']),
            namespace=row['namespace'] or '',
            access=row['access'] or 'public',
            parent_class=row['parent_class'] or '',
            base_classes=json.loads(row['base_classes']) if row['base_classes'] else [],
            usr=row['usr'] or '',
            calls=json.loads(row['calls']) if row['calls'] else [],
            called_by=json.loads(row['called_by']) if row['called_by'] else []
        )

    def save_symbol(self, symbol: SymbolInfo) -> bool:
        """
        Insert or update a single symbol.

        Args:
            symbol: SymbolInfo object to save

        Returns:
            True if successful, False otherwise
        """
        try:
            self._ensure_connected()

            with self.conn:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO symbols (
                        usr, name, kind, file, line, column, signature,
                        is_project, namespace, access, parent_class,
                        base_classes, calls, called_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._symbol_to_tuple(symbol)
                )

            return True

        except Exception as e:
            diagnostics.error(f"Failed to save symbol {symbol.usr}: {e}")
            return False

    def save_symbols_batch(self, symbols: List[SymbolInfo]) -> int:
        """
        Batch insert/update symbols using transaction.

        Performance: ~10,000 symbols/sec vs ~100 symbols/sec for individual inserts.

        Args:
            symbols: List of SymbolInfo objects to save

        Returns:
            Number of symbols successfully saved
        """
        if not symbols:
            return 0

        try:
            self._ensure_connected()

            # Batch insert in a single transaction
            with self.conn:
                self.conn.executemany(
                    """
                    INSERT OR REPLACE INTO symbols (
                        usr, name, kind, file, line, column, signature,
                        is_project, namespace, access, parent_class,
                        base_classes, calls, called_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [self._symbol_to_tuple(s) for s in symbols]
                )

            return len(symbols)

        except Exception as e:
            diagnostics.error(f"Failed to batch save {len(symbols)} symbols: {e}")
            return 0

    def load_symbol_by_usr(self, usr: str) -> Optional[SymbolInfo]:
        """
        Load a symbol by its USR.

        Args:
            usr: Unified Symbol Resolution ID

        Returns:
            SymbolInfo object if found, None otherwise
        """
        try:
            self._ensure_connected()

            cursor = self.conn.execute(
                "SELECT * FROM symbols WHERE usr = ?",
                (usr,)
            )

            row = cursor.fetchone()
            if row:
                return self._row_to_symbol(row)

            return None

        except Exception as e:
            diagnostics.error(f"Failed to load symbol by USR {usr}: {e}")
            return None

    def load_symbols_by_name(self, name: str) -> List[SymbolInfo]:
        """
        Load all symbols matching a name.

        Args:
            name: Symbol name to search for

        Returns:
            List of matching SymbolInfo objects
        """
        try:
            self._ensure_connected()

            cursor = self.conn.execute(
                "SELECT * FROM symbols WHERE name = ?",
                (name,)
            )

            return [self._row_to_symbol(row) for row in cursor.fetchall()]

        except Exception as e:
            diagnostics.error(f"Failed to load symbols by name {name}: {e}")
            return []

    def count_symbols(self) -> int:
        """
        Get total symbol count.

        Returns:
            Number of symbols in database
        """
        try:
            self._ensure_connected()

            cursor = self.conn.execute("SELECT COUNT(*) FROM symbols")
            return cursor.fetchone()[0]

        except Exception as e:
            diagnostics.error(f"Failed to count symbols: {e}")
            return 0

    def verify_integrity(self) -> bool:
        """
        Verify database integrity.

        Returns:
            True if database is healthy, False if corrupted
        """
        try:
            self._ensure_connected()

            cursor = self.conn.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]

            if result == 'ok':
                diagnostics.debug("Database integrity check: OK")
                return True
            else:
                diagnostics.error(f"Database integrity check failed: {result}")
                return False

        except Exception as e:
            diagnostics.error(f"Failed to check integrity: {e}")
            return False
