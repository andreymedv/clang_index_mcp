"""SQLite-backed symbol CRUD and search operations."""

import json
import sqlite3
import time
from typing import Callable, List, Optional

from ..._symbols.model import SymbolInfo

try:
    from ..._core import diagnostics
except ImportError:
    import diagnostics  # type: ignore[no-redef]


class SymbolRepository:
    """Handles symbol persistence: insert, batch write, search, and delete."""

    def __init__(self, conn_getter: Callable[[], Optional[sqlite3.Connection]]):
        """
        Args:
            conn_getter: Callable returning the current SQLite connection.
                         Survives cache reconnections.
        """
        self._conn_getter = conn_getter

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the current database connection."""
        connection = self._conn_getter()
        assert connection is not None, "Database connection not initialized"
        return connection

    def symbol_to_tuple(self, symbol: SymbolInfo) -> tuple:
        """Convert SymbolInfo to tuple for SQL insertion."""
        now = time.time()
        return (
            symbol.usr,
            symbol.name,
            symbol.qualified_name,
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
            symbol.is_template_specialization,
            symbol.is_template,
            symbol.template_kind,
            symbol.template_parameters,
            symbol.primary_template_usr,
            symbol.start_line,
            symbol.end_line,
            symbol.header_file,
            symbol.header_line,
            symbol.header_start_line,
            symbol.header_end_line,
            symbol.is_definition,
            symbol.is_virtual,
            symbol.is_pure_virtual,
            symbol.is_const,
            symbol.is_static,
            symbol.brief,
            symbol.doc_comment,
            now,
            now,
        )

    def row_to_symbol(self, row: sqlite3.Row) -> SymbolInfo:
        """Convert database row to SymbolInfo object."""
        return SymbolInfo(
            name=row["name"],
            qualified_name=(row["qualified_name"] if "qualified_name" in row.keys() else ""),
            kind=row["kind"],
            file=row["file"],
            line=row["line"],
            column=row["column"],
            signature=row["signature"] or "",
            is_project=bool(row["is_project"]),
            namespace=row["namespace"] or "",
            access=row["access"] or "public",
            parent_class=row["parent_class"] or "",
            base_classes=json.loads(row["base_classes"]) if row["base_classes"] else [],
            usr=row["usr"] or "",
            is_template_specialization=(
                bool(row["is_template_specialization"])
                if "is_template_specialization" in row.keys()
                else False
            ),
            is_template=(bool(row["is_template"]) if "is_template" in row.keys() else False),
            template_kind=(row["template_kind"] if "template_kind" in row.keys() else None),
            template_parameters=(
                row["template_parameters"] if "template_parameters" in row.keys() else None
            ),
            primary_template_usr=(
                row["primary_template_usr"] if "primary_template_usr" in row.keys() else None
            ),
            start_line=row["start_line"] if "start_line" in row.keys() else None,
            end_line=row["end_line"] if "end_line" in row.keys() else None,
            header_file=row["header_file"] if "header_file" in row.keys() else None,
            header_line=row["header_line"] if "header_line" in row.keys() else None,
            header_start_line=(
                row["header_start_line"] if "header_start_line" in row.keys() else None
            ),
            header_end_line=row["header_end_line"] if "header_end_line" in row.keys() else None,
            is_definition=bool(row["is_definition"]) if "is_definition" in row.keys() else False,
            is_virtual=bool(row["is_virtual"]) if "is_virtual" in row.keys() else False,
            is_pure_virtual=(
                bool(row["is_pure_virtual"]) if "is_pure_virtual" in row.keys() else False
            ),
            is_const=bool(row["is_const"]) if "is_const" in row.keys() else False,
            is_static=bool(row["is_static"]) if "is_static" in row.keys() else False,
            brief=row["brief"] if "brief" in row.keys() else None,
            doc_comment=row["doc_comment"] if "doc_comment" in row.keys() else None,
        )

    def save_symbol(self, symbol: SymbolInfo) -> bool:
        """Insert or update a single symbol."""
        try:
            with self.conn:
                self.conn.execute(
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
                    self.symbol_to_tuple(symbol),
                )
            return True
        except Exception as e:
            diagnostics.error(f"Failed to save symbol {symbol.usr}: {e}")
            return False

    def save_symbols_batch(self, symbols: List[SymbolInfo]) -> int:
        """Batch insert/update symbols in a single transaction (C6)."""
        if not symbols:
            return 0
        try:
            with self.conn:
                self.conn.executemany(
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
                    [self.symbol_to_tuple(s) for s in symbols],
                )
            return len(symbols)
        except Exception as e:
            diagnostics.error(f"Failed to batch save {len(symbols)} symbols: {e}")
            return 0

    def load_symbol_by_usr(self, usr: str) -> Optional[SymbolInfo]:
        """Load a symbol by its USR."""
        try:
            cursor = self.conn.execute("SELECT * FROM symbols WHERE usr = ?", (usr,))
            row = cursor.fetchone()
            if row:
                return self.row_to_symbol(row)
            return None
        except Exception as e:
            diagnostics.error(f"Failed to load symbol by USR {usr}: {e}")
            return None

    def load_symbols_by_name(self, name: str) -> List[SymbolInfo]:
        """Load all symbols matching a name."""
        try:
            cursor = self.conn.execute("SELECT * FROM symbols WHERE name = ?", (name,))
            return [self.row_to_symbol(row) for row in cursor.fetchall()]
        except Exception as e:
            diagnostics.error(f"Failed to load symbols by name {name}: {e}")
            return []

    def count_symbols(self) -> int:
        """Get total symbol count."""
        try:
            cursor = self.conn.execute("SELECT COUNT(*) FROM symbols")
            result: int = cursor.fetchone()[0]
            return result
        except Exception as e:
            diagnostics.error(f"Failed to count symbols: {e}")
            return 0

    def delete_symbols_by_file(self, file_path: str) -> int:
        """Delete all symbols from a specific file."""
        try:
            cursor = self.conn.execute("SELECT COUNT(*) FROM symbols WHERE file = ?", (file_path,))
            count: int = cursor.fetchone()[0]
            if count == 0:
                return 0
            with self.conn:
                self.conn.execute("DELETE FROM symbols WHERE file = ?", (file_path,))
            diagnostics.debug(f"Deleted {count} symbols from {file_path}")
            return count
        except Exception as e:
            diagnostics.error(f"Failed to delete symbols for file {file_path}: {e}")
            return 0

    def search_symbols_fts(
        self, pattern: str, kind: Optional[str] = None, project_only: bool = True
    ) -> List[SymbolInfo]:
        """Fast full-text search using FTS5. Falls back to regex on failure."""
        try:
            query = """
                SELECT s.* FROM symbols s
                WHERE s.usr IN (
                    SELECT usr FROM symbols_fts
                    WHERE name MATCH ?
                )
            """
            params: list = [pattern]
            if kind:
                query += " AND s.kind = ?"
                params.append(kind)
            if project_only:
                query += " AND s.is_project = 1"
            cursor = self.conn.execute(query, params)
            return [self.row_to_symbol(row) for row in cursor.fetchall()]
        except Exception as e:
            diagnostics.error(f"FTS5 search failed for pattern '{pattern}': {e}")
            return self.search_symbols_regex(pattern, kind, project_only)

    def search_symbols_regex(
        self, pattern: str, kind: Optional[str] = None, project_only: bool = True
    ) -> List[SymbolInfo]:
        """Regex search (fallback for complex patterns)."""
        try:
            query = "SELECT * FROM symbols WHERE name REGEXP ?"
            params: list = [pattern]
            if kind:
                query += " AND kind = ?"
                params.append(kind)
            if project_only:
                query += " AND is_project = 1"
            cursor = self.conn.execute(query, params)
            return [self.row_to_symbol(row) for row in cursor.fetchall()]
        except Exception as e:
            diagnostics.error(f"Regex search failed for pattern '{pattern}': {e}")
            return []

    def search_symbols_by_file(self, file_path: str) -> List[SymbolInfo]:
        """Get all symbols defined in a specific file."""
        try:
            cursor = self.conn.execute("SELECT * FROM symbols WHERE file = ?", (file_path,))
            return [self.row_to_symbol(row) for row in cursor.fetchall()]
        except Exception as e:
            diagnostics.error(f"Failed to search symbols by file {file_path}: {e}")
            return []

    def search_symbols_by_kind(self, kind: str, project_only: bool = True) -> List[SymbolInfo]:
        """Get all symbols of a specific kind."""
        try:
            query = "SELECT * FROM symbols WHERE kind = ?"
            params: list = [kind]
            if project_only:
                query += " AND is_project = 1"
            cursor = self.conn.execute(query, params)
            return [self.row_to_symbol(row) for row in cursor.fetchall()]
        except Exception as e:
            diagnostics.error(f"Failed to search symbols by kind {kind}: {e}")
            return []
