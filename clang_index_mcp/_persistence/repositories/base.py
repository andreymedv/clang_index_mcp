"""Shared base class for SQLite-backed repositories."""

import sqlite3
from typing import Callable, Optional, Tuple


class BaseRepository:
    """Provides common connection access for SQLite-backed repositories."""

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

    def _count_and_delete(self, table: str, condition: str, params: Tuple) -> int:
        """Count rows matching ``condition`` in ``table``, then delete them.

        Returns the number of deleted rows (0 when nothing matched).
        """
        cursor = self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {condition}", params)
        count: int = cursor.fetchone()[0]
        if count == 0:
            return 0
        with self.conn:
            self.conn.execute(f"DELETE FROM {table} WHERE {condition}", params)
        return count
