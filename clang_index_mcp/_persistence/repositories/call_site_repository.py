"""SQLite-backed call site storage and queries."""

import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

try:
    from ..._core import diagnostics
except ImportError:
    import diagnostics  # type: ignore[no-redef]


class CallSiteRepository:
    """Handles call site persistence: batch insert, query by caller/callee, delete."""

    def __init__(self, conn_getter: Callable[[], Optional[sqlite3.Connection]]):
        self._conn_getter = conn_getter

    @property
    def conn(self) -> sqlite3.Connection:
        connection = self._conn_getter()
        assert connection is not None, "Database connection not initialized"
        return connection

    def save_call_sites_batch(self, call_sites: List[Dict[str, Any]]) -> int:
        """Batch insert call sites in a single transaction (C6)."""
        if not call_sites:
            return 0
        try:
            current_time = time.time()
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
            with self.conn:
                self.conn.executemany(
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
        """Get all call sites from a specific caller function."""
        try:
            cursor = self.conn.execute(
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
        """Get all call sites to a specific callee function."""
        try:
            cursor = self.conn.execute(
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
        """Get call sites between callers and callee that have template metadata."""
        if not caller_usrs:
            return []
        try:
            placeholders = ",".join("?" for _ in caller_usrs)
            cursor = self.conn.execute(
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
        """Delete all call sites from a specific file."""
        try:
            cursor = self.conn.execute(
                "SELECT COUNT(*) FROM call_sites WHERE file = ?", (file_path,)
            )
            count: int = cursor.fetchone()[0]
            if count == 0:
                return 0
            with self.conn:
                self.conn.execute("DELETE FROM call_sites WHERE file = ?", (file_path,))
            return count
        except Exception as e:
            diagnostics.error(f"Failed to delete call sites for file {file_path}: {e}")
            return 0

    def delete_call_sites_by_usr(self, usr: str) -> int:
        """Delete all call sites where the given USR appears as either caller or callee."""
        try:
            cursor = self.conn.execute(
                "SELECT COUNT(*) FROM call_sites WHERE caller_usr = ? OR callee_usr = ?",
                (usr, usr),
            )
            count: int = cursor.fetchone()[0]
            if count == 0:
                return 0
            with self.conn:
                self.conn.execute(
                    "DELETE FROM call_sites WHERE caller_usr = ? OR callee_usr = ?", (usr, usr)
                )
            return count
        except Exception as e:
            diagnostics.error(f"Failed to delete call sites for USR {usr}: {e}")
            return 0

    def load_all_call_sites(self) -> List[Dict[str, Any]]:
        """Load all call sites from the database."""
        try:
            cursor = self.conn.execute("""
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
