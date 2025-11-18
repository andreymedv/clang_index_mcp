"""Dependency Graph Builder for Incremental Analysis.

This module provides functionality to track include dependencies between
source files and headers, enabling cascade re-analysis when headers change.

Key Features:
- Extract include directives from translation units
- Build forward dependency graph (file → what it includes)
- Build reverse dependency graph (header → files that include it)
- Compute transitive closure for cascade analysis
- Efficient graph queries using recursive CTEs

Usage:
    builder = DependencyGraphBuilder(db_connection)

    # Extract and store dependencies
    includes = builder.extract_includes_from_tu(tu, source_file)
    builder.update_dependencies(source_file, includes)

    # Query dependencies
    dependents = builder.find_dependents("header.h")
    all_dependents = builder.find_transitive_dependents("header.h")
"""

import sqlite3
import time
from pathlib import Path
from typing import List, Set, Dict, Optional

try:
    import clang.cindex
    from clang.cindex import TranslationUnit
except ImportError:
    TranslationUnit = None  # Type hint only

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics


class DependencyGraphBuilder:
    """
    Builds and maintains the include dependency graph.

    This class tracks which files include which headers, enabling
    incremental analysis by identifying files affected by header changes.

    The dependency graph is stored in the file_dependencies table:
    - source_file: File doing the including
    - included_file: File being included
    - is_direct: True for direct includes, False for transitive
    - include_depth: 1 for direct, 2+ for transitive
    - detected_at: Timestamp when relationship was discovered

    Attributes:
        conn: SQLite database connection
    """

    def __init__(self, conn: sqlite3.Connection):
        """
        Initialize dependency graph builder.

        Args:
            conn: Active SQLite database connection with file_dependencies table
        """
        self.conn = conn

    def extract_includes_from_tu(
        self,
        tu: 'TranslationUnit',
        source_file: str
    ) -> List[str]:
        """
        Extract all includes from a translation unit.

        Uses libclang's translation unit to get complete include list,
        including system headers and transitive includes. This provides
        the full closure of all files that affect the compilation of
        the source file.

        Args:
            tu: Parsed translation unit from libclang
            source_file: Path to source file being analyzed

        Returns:
            List of absolute paths to all included files (headers)

        Note:
            libclang provides the complete transitive closure of includes,
            so we don't need to manually compute transitivity.
        """
        includes = []

        try:
            # Get all includes from TU
            # tu.get_includes() returns an iterator of Include objects
            for include in tu.get_includes():
                # include.include is a File object
                included_path = str(include.include.name)

                # Normalize path to absolute
                try:
                    included_path = str(Path(included_path).resolve())
                except Exception:
                    # If path resolution fails, use as-is
                    pass

                # Add to list (avoid duplicates)
                if included_path not in includes:
                    includes.append(included_path)

        except Exception as e:
            diagnostics.warning(f"Failed to extract includes from {source_file}: {e}")
            return []

        diagnostics.debug(f"Extracted {len(includes)} includes from {source_file}")
        return includes

    def update_dependencies(
        self,
        source_file: str,
        included_files: List[str]
    ) -> int:
        """
        Update dependency graph for a source file.

        Strategy:
        1. Delete old dependencies for this source file
        2. Insert new dependencies

        This ensures the dependency graph stays current as includes change.

        Args:
            source_file: Path to source file (absolute)
            included_files: List of files it includes (absolute paths)

        Returns:
            Number of dependencies inserted

        Note:
            All dependencies are marked as direct (is_direct=True) since
            libclang doesn't easily distinguish direct vs transitive includes,
            and for our use case (finding affected files), we only need to
            know that a relationship exists.
        """
        cursor = self.conn.cursor()

        try:
            # Delete old dependencies for this source file
            cursor.execute(
                "DELETE FROM file_dependencies WHERE source_file = ?",
                (source_file,)
            )

            # Insert new dependencies (deduplicate first)
            now = time.time()
            inserted = 0
            unique_includes = set(included_files)  # Remove duplicates

            for included_file in unique_includes:
                try:
                    cursor.execute("""
                        INSERT OR REPLACE INTO file_dependencies
                        (source_file, included_file, is_direct, include_depth, detected_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (source_file, included_file, True, 1, now))
                    inserted += 1
                except sqlite3.IntegrityError:
                    # Duplicate, skip
                    pass

            self.conn.commit()

            diagnostics.debug(
                f"Updated dependencies for {source_file}: {inserted} includes"
            )

            return inserted

        except Exception as e:
            diagnostics.error(f"Failed to update dependencies for {source_file}: {e}")
            self.conn.rollback()
            return 0

    def find_dependents(self, header_path: str) -> Set[str]:
        """
        Find all files that directly depend on a header (reverse lookup).

        This is the key query for incremental analysis:
        "Header X changed, which files need re-analysis?"

        Args:
            header_path: Path to header file (absolute)

        Returns:
            Set of source files that include this header

        Example:
            >>> builder.find_dependents("utils.h")
            {"main.cpp", "test.cpp", "helper.cpp"}
        """
        cursor = self.conn.cursor()

        try:
            # Direct dependents
            cursor.execute("""
                SELECT DISTINCT source_file
                FROM file_dependencies
                WHERE included_file = ?
            """, (header_path,))

            dependents = {row[0] for row in cursor.fetchall()}

            diagnostics.debug(
                f"Found {len(dependents)} direct dependents of {header_path}"
            )

            return dependents

        except Exception as e:
            diagnostics.error(f"Failed to find dependents of {header_path}: {e}")
            return set()

    def find_transitive_dependents(self, header_path: str) -> Set[str]:
        """
        Find all files that depend on a header transitively.

        Uses recursive SQL to traverse the dependency graph and find
        all files affected by a header change, including those that
        include the header indirectly through other headers.

        Example:
            A.cpp includes B.h
            B.h includes C.h
            C.h is modified

            find_transitive_dependents("C.h") → {B.h, A.cpp}

        Args:
            header_path: Path to header file (absolute)

        Returns:
            Set of all files that transitively depend on this header

        Algorithm:
            Uses recursive CTE (Common Table Expression) for efficient
            graph traversal in SQLite:
            1. Base case: Direct dependents
            2. Recursive case: Dependents of dependents
            3. DISTINCT prevents infinite loops in circular dependencies
        """
        cursor = self.conn.cursor()

        try:
            cursor.execute("""
                WITH RECURSIVE dependents(file_path) AS (
                    -- Base case: direct dependents
                    SELECT DISTINCT source_file
                    FROM file_dependencies
                    WHERE included_file = ?

                    UNION

                    -- Recursive case: files that include dependents
                    SELECT DISTINCT fd.source_file
                    FROM file_dependencies fd
                    JOIN dependents d ON fd.included_file = d.file_path
                )
                SELECT file_path FROM dependents
            """, (header_path,))

            transitive_dependents = {row[0] for row in cursor.fetchall()}

            diagnostics.debug(
                f"Found {len(transitive_dependents)} transitive dependents of {header_path}"
            )

            return transitive_dependents

        except Exception as e:
            diagnostics.error(
                f"Failed to find transitive dependents of {header_path}: {e}"
            )
            return set()

    def remove_file_dependencies(self, file_path: str) -> int:
        """
        Remove all dependencies for a file (when file is deleted).

        Removes both:
        - Dependencies where this file is the source (includes others)
        - Dependencies where this file is included (others include it)

        Args:
            file_path: Path to file being removed

        Returns:
            Number of dependency records removed
        """
        cursor = self.conn.cursor()

        try:
            # Remove dependencies where this is the source
            cursor.execute(
                "DELETE FROM file_dependencies WHERE source_file = ?",
                (file_path,)
            )
            source_deleted = cursor.rowcount

            # Remove dependencies where this is included
            cursor.execute(
                "DELETE FROM file_dependencies WHERE included_file = ?",
                (file_path,)
            )
            included_deleted = cursor.rowcount

            self.conn.commit()

            total_deleted = source_deleted + included_deleted
            diagnostics.debug(
                f"Removed {total_deleted} dependencies for {file_path}"
            )

            return total_deleted

        except Exception as e:
            diagnostics.error(f"Failed to remove dependencies for {file_path}: {e}")
            self.conn.rollback()
            return 0

    def get_dependency_stats(self) -> Dict[str, int]:
        """
        Get statistics about the dependency graph.

        Returns:
            Dictionary with statistics:
            - total_dependencies: Total dependency records
            - unique_source_files: Number of unique source files
            - unique_included_files: Number of unique headers
            - avg_includes_per_file: Average includes per source file

        Useful for diagnostics and monitoring.
        """
        cursor = self.conn.cursor()

        try:
            # Total dependencies
            cursor.execute("SELECT COUNT(*) FROM file_dependencies")
            total_dependencies = cursor.fetchone()[0]

            # Unique source files
            cursor.execute(
                "SELECT COUNT(DISTINCT source_file) FROM file_dependencies"
            )
            unique_sources = cursor.fetchone()[0]

            # Unique included files
            cursor.execute(
                "SELECT COUNT(DISTINCT included_file) FROM file_dependencies"
            )
            unique_includes = cursor.fetchone()[0]

            # Average includes per file
            avg_includes = (
                total_dependencies / unique_sources if unique_sources > 0 else 0
            )

            return {
                "total_dependencies": total_dependencies,
                "unique_source_files": unique_sources,
                "unique_included_files": unique_includes,
                "avg_includes_per_file": round(avg_includes, 2)
            }

        except Exception as e:
            diagnostics.error(f"Failed to get dependency stats: {e}")
            return {
                "total_dependencies": 0,
                "unique_source_files": 0,
                "unique_included_files": 0,
                "avg_includes_per_file": 0.0
            }

    def get_include_count(self, source_file: str) -> int:
        """
        Get number of files included by a source file.

        Args:
            source_file: Path to source file

        Returns:
            Number of files it includes
        """
        cursor = self.conn.cursor()

        try:
            cursor.execute("""
                SELECT COUNT(*)
                FROM file_dependencies
                WHERE source_file = ?
            """, (source_file,))

            count = cursor.fetchone()[0]
            return count

        except Exception as e:
            diagnostics.error(f"Failed to get include count for {source_file}: {e}")
            return 0

    def clear_all_dependencies(self) -> int:
        """
        Clear all dependencies from the graph.

        Useful for:
        - Full re-analysis
        - Testing
        - Recovery from corruption

        Returns:
            Number of dependency records removed
        """
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
