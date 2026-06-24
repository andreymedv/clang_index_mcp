"""SQLite-backed implementation of the DependencyRepository port."""

import sqlite3
import time
from typing import Callable, Dict, List, Optional, Set, Union

from ..._core import diagnostics


class SqliteDependencyRepository:
    """Stores and queries include dependencies using SQLite."""

    def __init__(self, conn_getter: Callable[[], Optional[sqlite3.Connection]]):
        """
        Args:
            conn_getter: Callable returning the current SQLite connection.
                         A callable is used so the repository survives cache
                         reconnections.
        """
        self._conn_getter = conn_getter

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the current database connection."""
        conn = self._conn_getter()
        assert conn is not None
        return conn

    def update_dependencies(self, source_file: str, included_files: List[str]) -> int:
        """Replace stored dependencies for ``source_file``."""
        cursor = self.conn.cursor()

        try:
            cursor.execute("DELETE FROM file_dependencies WHERE source_file = ?", (source_file,))

            now = time.time()
            inserted = 0
            unique_includes = set(included_files)

            for included_file in unique_includes:
                try:
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO file_dependencies
                        (source_file, included_file, is_direct, include_depth, detected_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (source_file, included_file, True, 1, now),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass

            self.conn.commit()
            diagnostics.debug(f"Updated dependencies for {source_file}: {inserted} includes")
            return inserted

        except Exception as e:
            diagnostics.error(f"Failed to update dependencies for {source_file}: {e}")
            self.conn.rollback()
            return 0

    def find_dependents(self, header_path: str) -> Set[str]:
        """Return source files that directly include ``header_path``."""
        cursor = self.conn.cursor()

        try:
            cursor.execute(
                """
                SELECT DISTINCT source_file
                FROM file_dependencies
                WHERE included_file = ?
                """,
                (header_path,),
            )
            dependents = {row[0] for row in cursor.fetchall()}
            diagnostics.debug(f"Found {len(dependents)} direct dependents of {header_path}")
            return dependents

        except Exception as e:
            diagnostics.error(f"Failed to find dependents of {header_path}: {e}")
            return set()

    def find_transitive_dependents(self, header_path: str) -> Set[str]:
        """Return all files that transitively include ``header_path``."""
        cursor = self.conn.cursor()

        try:
            cursor.execute(
                """
                WITH RECURSIVE dependents(file_path) AS (
                    SELECT DISTINCT source_file
                    FROM file_dependencies
                    WHERE included_file = ?

                    UNION

                    SELECT DISTINCT fd.source_file
                    FROM file_dependencies fd
                    JOIN dependents d ON fd.included_file = d.file_path
                )
                SELECT file_path FROM dependents
                """,
                (header_path,),
            )
            transitive_dependents = {row[0] for row in cursor.fetchall()}
            diagnostics.debug(
                f"Found {len(transitive_dependents)} transitive dependents of {header_path}"
            )
            return transitive_dependents

        except Exception as e:
            diagnostics.error(f"Failed to find transitive dependents of {header_path}: {e}")
            return set()

    def remove_file_dependencies(self, file_path: str) -> int:
        """Remove all dependency records involving ``file_path``."""
        cursor = self.conn.cursor()

        try:
            cursor.execute("DELETE FROM file_dependencies WHERE source_file = ?", (file_path,))
            source_deleted = cursor.rowcount

            cursor.execute("DELETE FROM file_dependencies WHERE included_file = ?", (file_path,))
            included_deleted = cursor.rowcount

            self.conn.commit()

            total_deleted = source_deleted + included_deleted
            diagnostics.debug(f"Removed {total_deleted} dependencies for {file_path}")
            return total_deleted

        except Exception as e:
            diagnostics.error(f"Failed to remove dependencies for {file_path}: {e}")
            self.conn.rollback()
            return 0

    def get_dependency_stats(self) -> Dict[str, Union[int, float]]:
        """Return aggregate dependency statistics."""
        cursor = self.conn.cursor()

        try:
            cursor.execute("SELECT COUNT(*) FROM file_dependencies")
            total_dependencies = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT source_file) FROM file_dependencies")
            unique_sources = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT included_file) FROM file_dependencies")
            unique_includes = cursor.fetchone()[0]

            avg_includes = total_dependencies / unique_sources if unique_sources > 0 else 0

            return {
                "total_dependencies": total_dependencies,
                "unique_source_files": unique_sources,
                "unique_included_files": unique_includes,
                "avg_includes_per_file": round(avg_includes, 2),
            }

        except Exception as e:
            diagnostics.error(f"Failed to get dependency stats: {e}")
            return {
                "total_dependencies": 0,
                "unique_source_files": 0,
                "unique_included_files": 0,
                "avg_includes_per_file": float(0),
            }

    def get_include_count(self, source_file: str) -> int:
        """Return the number of files included by ``source_file``."""
        cursor = self.conn.cursor()

        try:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM file_dependencies
                WHERE source_file = ?
                """,
                (source_file,),
            )
            count: int = cursor.fetchone()[0]
            return count

        except Exception as e:
            diagnostics.error(f"Failed to get include count for {source_file}: {e}")
            return 0

    def clear_all_dependencies(self) -> int:
        """Remove all dependency records."""
        cursor = self.conn.cursor()

        try:
            cursor.execute("DELETE FROM file_dependencies")
            deleted = cursor.rowcount
            self.conn.commit()
            diagnostics.info(f"Cleared all dependencies ({deleted} records)")
            return deleted

        except Exception as e:
            diagnostics.error(f"Failed to clear dependencies: {e}")
            self.conn.rollback()
            return 0
