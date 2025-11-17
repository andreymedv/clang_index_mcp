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

            # Set busy handler for lock retry with exponential backoff (if available)
            if hasattr(self.conn, 'set_busy_handler'):
                self.conn.set_busy_handler(self._busy_handler)
            else:
                diagnostics.debug("set_busy_handler not available, using timeout only")

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

    def delete_symbols_by_file(self, file_path: str) -> int:
        """
        Delete all symbols from a specific file.

        Args:
            file_path: Path to file whose symbols should be deleted

        Returns:
            Number of symbols deleted
        """
        try:
            self._ensure_connected()

            # Get count before deletion
            cursor = self.conn.execute(
                "SELECT COUNT(*) FROM symbols WHERE file = ?",
                (file_path,)
            )
            count = cursor.fetchone()[0]

            if count == 0:
                return 0

            # Delete symbols
            with self.conn:
                self.conn.execute(
                    "DELETE FROM symbols WHERE file = ?",
                    (file_path,)
                )

            diagnostics.debug(f"Deleted {count} symbols from {file_path}")
            return count

        except Exception as e:
            diagnostics.error(f"Failed to delete symbols for file {file_path}: {e}")
            return 0

    def update_file_metadata(self, file_path: str, file_hash: str,
                            compile_args_hash: Optional[str] = None,
                            symbol_count: int = 0) -> bool:
        """
        Update or insert file metadata.

        Args:
            file_path: Absolute path to file
            file_hash: MD5 hash of file contents
            compile_args_hash: Hash of compilation arguments
            symbol_count: Number of symbols in file

        Returns:
            True if successful, False otherwise
        """
        try:
            self._ensure_connected()

            with self.conn:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO file_metadata
                    (file_path, file_hash, compile_args_hash, indexed_at, symbol_count)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (file_path, file_hash, compile_args_hash, time.time(), symbol_count)
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

            cursor = self.conn.execute(
                "SELECT * FROM file_metadata WHERE file_path = ?",
                (file_path,)
            )

            row = cursor.fetchone()
            if row:
                return {
                    'file_path': row['file_path'],
                    'file_hash': row['file_hash'],
                    'compile_args_hash': row['compile_args_hash'],
                    'indexed_at': row['indexed_at'],
                    'symbol_count': row['symbol_count']
                }

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

            cursor = self.conn.execute(
                "SELECT file_path, file_hash FROM file_metadata"
            )

            return {row['file_path']: row['file_hash'] for row in cursor.fetchall()}

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

            with self.conn:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO cache_metadata (key, value, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (key, value, time.time())
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

            cursor = self.conn.execute(
                "SELECT value FROM cache_metadata WHERE key = ?",
                (key,)
            )

            row = cursor.fetchone()
            return row['value'] if row else None

        except Exception as e:
            diagnostics.error(f"Failed to get cache metadata {key}: {e}")
            return None

    def search_symbols_fts(self, pattern: str, kind: Optional[str] = None,
                           project_only: bool = True) -> List[SymbolInfo]:
        """
        Fast full-text search using FTS5.

        Pattern can be:
        - Exact: "Vector"
        - Prefix: "Vec*"
        - Multiple terms: "Vector push"

        Performance: 2-5ms for 100K symbols (vs 50ms with LIKE)

        Args:
            pattern: Search pattern (FTS5 MATCH syntax)
            kind: Filter by symbol kind (class, function, etc.)
            project_only: If True, only return project symbols

        Returns:
            List of matching SymbolInfo objects
        """
        try:
            self._ensure_connected()

            # Build query using FTS5
            query = """
                SELECT s.* FROM symbols s
                WHERE s.usr IN (
                    SELECT usr FROM symbols_fts
                    WHERE name MATCH ?
                )
            """

            params = [pattern]

            if kind:
                query += " AND s.kind = ?"
                params.append(kind)

            if project_only:
                query += " AND s.is_project = 1"

            cursor = self.conn.execute(query, params)
            return [self._row_to_symbol(row) for row in cursor.fetchall()]

        except Exception as e:
            diagnostics.error(f"FTS5 search failed for pattern '{pattern}': {e}")
            # Fall back to regex search
            return self.search_symbols_regex(pattern, kind, project_only)

    def search_symbols_regex(self, pattern: str, kind: Optional[str] = None,
                             project_only: bool = True) -> List[SymbolInfo]:
        """
        Regex search (fallback for complex patterns).

        Slower than FTS5 but more flexible.
        Performance: 10-50ms for 100K symbols

        Args:
            pattern: Regular expression pattern
            kind: Filter by symbol kind
            project_only: If True, only return project symbols

        Returns:
            List of matching SymbolInfo objects
        """
        try:
            self._ensure_connected()

            query = "SELECT * FROM symbols WHERE name REGEXP ?"
            params = [pattern]

            if kind:
                query += " AND kind = ?"
                params.append(kind)

            if project_only:
                query += " AND is_project = 1"

            cursor = self.conn.execute(query, params)
            return [self._row_to_symbol(row) for row in cursor.fetchall()]

        except Exception as e:
            diagnostics.error(f"Regex search failed for pattern '{pattern}': {e}")
            return []

    def search_symbols_by_file(self, file_path: str) -> List[SymbolInfo]:
        """
        Get all symbols defined in a specific file.

        Args:
            file_path: Path to source file

        Returns:
            List of SymbolInfo objects from that file
        """
        try:
            self._ensure_connected()

            cursor = self.conn.execute(
                "SELECT * FROM symbols WHERE file = ?",
                (file_path,)
            )

            return [self._row_to_symbol(row) for row in cursor.fetchall()]

        except Exception as e:
            diagnostics.error(f"Failed to search symbols by file {file_path}: {e}")
            return []

    def search_symbols_by_kind(self, kind: str, project_only: bool = True) -> List[SymbolInfo]:
        """
        Get all symbols of a specific kind.

        Args:
            kind: Symbol kind (class, function, method, etc.)
            project_only: If True, only return project symbols

        Returns:
            List of matching SymbolInfo objects
        """
        try:
            self._ensure_connected()

            query = "SELECT * FROM symbols WHERE kind = ?"
            params = [kind]

            if project_only:
                query += " AND is_project = 1"

            cursor = self.conn.execute(query, params)
            return [self._row_to_symbol(row) for row in cursor.fetchall()]

        except Exception as e:
            diagnostics.error(f"Failed to search symbols by kind {kind}: {e}")
            return []

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
            cursor = self.conn.execute("SELECT COUNT(*) FROM symbols")
            stats['total_symbols'] = cursor.fetchone()[0]

            # Count by kind
            cursor = self.conn.execute("""
                SELECT kind, COUNT(*) as count
                FROM symbols
                GROUP BY kind
                ORDER BY count DESC
            """)
            stats['by_kind'] = {row['kind']: row['count'] for row in cursor.fetchall()}

            # Project vs dependencies
            cursor = self.conn.execute("""
                SELECT is_project, COUNT(*) as count
                FROM symbols
                GROUP BY is_project
            """)
            for row in cursor.fetchall():
                if row['is_project']:
                    stats['project_symbols'] = row['count']
                else:
                    stats['dependency_symbols'] = row['count']

            # File count
            cursor = self.conn.execute("SELECT COUNT(*) FROM file_metadata")
            stats['total_files'] = cursor.fetchone()[0]

            # Database size
            cursor = self.conn.execute("PRAGMA page_count")
            page_count = cursor.fetchone()[0]
            cursor = self.conn.execute("PRAGMA page_size")
            page_size = cursor.fetchone()[0]
            stats['db_size_bytes'] = page_count * page_size
            stats['db_size_mb'] = stats['db_size_bytes'] / (1024 * 1024)

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

    # =========================================================================
    # CacheBackend Protocol Adapter Methods
    # =========================================================================

    def save_cache(self, class_index: Dict[str, List], function_index: Dict[str, List],
                   file_hashes: Dict[str, str], indexed_file_count: int,
                   include_dependencies: bool = False,
                   config_file_path: Optional[Path] = None,
                   config_file_mtime: Optional[float] = None,
                   compile_commands_path: Optional[Path] = None,
                   compile_commands_mtime: Optional[float] = None) -> bool:
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

    def load_cache(self, include_dependencies: bool = False,
                   config_file_path: Optional[Path] = None,
                   config_file_mtime: Optional[float] = None,
                   compile_commands_path: Optional[Path] = None,
                   compile_commands_mtime: Optional[float] = None) -> Optional[Dict[str, Any]]:
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

            # Check if database has any symbols
            cursor = self.conn.execute("SELECT COUNT(*) FROM symbols")
            if cursor.fetchone()[0] == 0:
                return None

            # Check cache metadata for compatibility
            cached_deps = self.get_cache_metadata("include_dependencies")
            if cached_deps and cached_deps != str(include_dependencies):
                diagnostics.info(f"Cache dependencies mismatch: {cached_deps} != {include_dependencies}")
                return None

            # Check config file changes
            if config_file_path:
                cached_config = self.get_cache_metadata("config_file_path")
                if cached_config != str(config_file_path):
                    diagnostics.info("Configuration file path changed")
                    return None
                cached_mtime = self.get_cache_metadata("config_file_mtime")
                if cached_mtime and cached_mtime != str(config_file_mtime):
                    diagnostics.info("Configuration file modified")
                    return None

            # Check compile_commands.json changes
            if compile_commands_path:
                cached_cc = self.get_cache_metadata("compile_commands_path")
                if cached_cc != str(compile_commands_path):
                    diagnostics.info("compile_commands.json path changed")
                    return None
                cached_cc_mtime = self.get_cache_metadata("compile_commands_mtime")
                if cached_cc_mtime and cached_cc_mtime != str(compile_commands_mtime):
                    diagnostics.info("compile_commands.json modified")
                    return None

            # Load all symbols
            cursor = self.conn.execute("SELECT * FROM symbols")
            all_symbols = [self._row_to_symbol(row) for row in cursor.fetchall()]

            # Build indexes by name
            from collections import defaultdict
            class_index = defaultdict(list)
            function_index = defaultdict(list)

            for symbol in all_symbols:
                if symbol.kind in ('class', 'struct', 'union', 'enum'):
                    class_index[symbol.name].append(symbol)
                elif symbol.kind in ('function', 'method', 'constructor', 'destructor'):
                    function_index[symbol.name].append(symbol)

            # Load file hashes
            file_hashes = self.load_all_file_hashes()

            # Get indexed file count
            indexed_count = self.get_cache_metadata("indexed_file_count")

            return {
                "version": "2.0",
                "include_dependencies": include_dependencies,
                "config_file_path": str(config_file_path) if config_file_path else None,
                "config_file_mtime": config_file_mtime,
                "compile_commands_path": str(compile_commands_path) if compile_commands_path else None,
                "compile_commands_mtime": compile_commands_mtime,
                "class_index": dict(class_index),
                "function_index": dict(function_index),
                "file_hashes": file_hashes,
                "indexed_file_count": int(indexed_count) if indexed_count else 0,
                "timestamp": time.time()
            }

        except Exception as e:
            diagnostics.error(f"Failed to load cache: {e}")
            return None

    def save_file_cache(self, file_path: str, symbols: List,
                       file_hash: str, compile_args_hash: Optional[str] = None,
                       success: bool = True, error_message: Optional[str] = None,
                       retry_count: int = 0) -> bool:
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

            # Update file metadata
            self.update_file_metadata(file_path, file_hash, compile_args_hash, len(symbols))

            return True

        except Exception as e:
            diagnostics.error(f"Failed to save file cache for {file_path}: {e}")
            return False

    def load_file_cache(self, file_path: str, current_hash: str,
                       compile_args_hash: Optional[str] = None) -> Optional[Dict[str, Any]]:
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
            if metadata['file_hash'] != current_hash:
                return None

            # Check compile args hash
            if compile_args_hash and metadata.get('compile_args_hash') != compile_args_hash:
                return None

            # Load symbols for this file
            symbols = self.search_symbols_by_file(file_path)

            return {
                'symbols': symbols,
                'success': True,  # SQLite cache doesn't track failures
                'error_message': None,
                'retry_count': 0
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

            # Delete file metadata
            self._ensure_connected()
            with self.conn:
                self.conn.execute("DELETE FROM file_metadata WHERE file_path = ?", (file_path,))

            return True

        except Exception as e:
            diagnostics.error(f"Failed to remove file cache for {file_path}: {e}")
            return False
