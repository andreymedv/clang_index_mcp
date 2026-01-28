"""Compile Commands Differ for Incremental Analysis.

This module provides functionality to compute differences between
compile_commands.json versions, enabling selective re-analysis of
only files with changed compilation arguments.

Key Features:
- Detect added compilation entries
- Detect removed compilation entries
- Detect changed compilation arguments per file
- Store per-file argument hashes for efficient comparison

Usage:
    differ = CompileCommandsDiffer(cache_backend)

    # Compute diff
    added, removed, changed = differ.compute_diff(old_commands, new_commands)

    # Store current commands for future comparison
    differ.store_current_commands(new_commands)
"""

import hashlib
from typing import Dict, List, Set, Tuple

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics


class CompileCommandsDiffer:
    """
    Computes differences between compile_commands.json versions.

    Tracks per-file compilation arguments and detects:
    - Added files (new entries in compile_commands.json)
    - Removed files (entries deleted from compile_commands.json)
    - Files with changed compilation arguments

    Uses MD5 hashing of argument lists for efficient comparison.
    """

    def __init__(self, cache_backend):
        """
        Initialize compile commands differ.

        Args:
            cache_backend: CacheBackend instance (SQLite or JSON) for storing hashes
        """
        self.cache = cache_backend

    def compute_diff(
        self, old_commands: Dict[str, List[str]], new_commands: Dict[str, List[str]]
    ) -> Tuple[Set[str], Set[str], Set[str]]:
        """
        Compute difference between compile command sets.

        Identifies files that were added, removed, or had their
        compilation arguments changed.

        Args:
            old_commands: {file_path: [compilation_args]} from previous version
            new_commands: {file_path: [compilation_args]} from current version

        Returns:
            Tuple of (added_files, removed_files, changed_files)

        Example:
            >>> old = {
            ...     "main.cpp": ["-std=c++17", "-O2"],
            ...     "utils.cpp": ["-std=c++17"]
            ... }
            >>> new = {
            ...     "main.cpp": ["-std=c++20", "-O3"],  # Changed
            ...     "test.cpp": ["-std=c++17"]          # Added
            ... }
            >>> differ.compute_diff(old, new)
            ({'test.cpp'}, {'utils.cpp'}, {'main.cpp'})
        """
        old_files = set(old_commands.keys())
        new_files = set(new_commands.keys())

        # Files added to compile_commands.json
        added = new_files - old_files

        # Files removed from compile_commands.json
        removed = old_files - new_files

        # Files with changed compilation arguments
        changed = set()

        for file_path in old_files & new_files:
            old_args = old_commands[file_path]
            new_args = new_commands[file_path]

            # Compare argument lists
            # Order matters for some flags, so compare as lists
            if old_args != new_args:
                changed.add(file_path)

        diagnostics.debug(f"Compile commands diff: +{len(added)} -{len(removed)} ~{len(changed)}")

        return added, removed, changed

    def store_current_commands(self, commands: Dict[str, List[str]]) -> int:
        """
        Store current compile commands in cache for future diffing.

        Stores a hash of compilation arguments for each file in the
        file_metadata table. This enables efficient comparison on next load.

        Args:
            commands: {file_path: [compilation_args]} to store

        Returns:
            Number of command hashes stored

        Note:
            Uses compile_args_hash column in file_metadata table.
            If file_metadata doesn't exist for a file, creates it.
        """
        if not hasattr(self.cache, "conn"):
            # JSON backend doesn't support this yet
            diagnostics.debug("Compile commands storage not supported for JSON backend")
            return 0

        stored = 0

        try:
            for file_path, args in commands.items():
                args_hash = self._hash_args(args)

                # Try to update existing record
                cursor = self.cache.conn.execute(
                    """
                    UPDATE file_metadata
                    SET compile_args_hash = ?
                    WHERE file_path = ?
                """,
                    (args_hash, file_path),
                )

                if cursor.rowcount == 0:
                    # No existing record, create one
                    # Note: Other fields will be populated when file is actually indexed
                    import time

                    self.cache.conn.execute(
                        """
                        INSERT OR IGNORE INTO file_metadata
                        (file_path, file_hash, compile_args_hash, indexed_at, symbol_count)
                        VALUES (?, ?, ?, ?, ?)
                    """,
                        (file_path, "", args_hash, time.time(), 0),
                    )

                stored += 1

            self.cache.conn.commit()

            diagnostics.debug(f"Stored {stored} compile command hashes")
            return stored

        except Exception as e:
            diagnostics.error(f"Failed to store compile commands: {e}")
            self.cache.conn.rollback()
            return 0

    def _hash_args(self, args: List[str]) -> str:
        """
        Hash compilation arguments for comparison.

        Creates a stable hash of the argument list that can be used
        to detect changes in compilation flags.

        Args:
            args: List of compilation arguments

        Returns:
            SHA-256 hash (first 16 characters) of concatenated arguments

        Algorithm:
            1. Join arguments with "|" separator
            2. Compute SHA-256 hash
            3. Return first 16 hex characters

        Note:
            Order matters - different order = different hash
        """
        args_str = "|".join(args)
        hash_value = hashlib.sha256(args_str.encode("utf-8")).hexdigest()
        return hash_value[:16]  # 16 chars = 64 bits

    def get_stored_commands_hash(self, file_path: str) -> str:
        """
        Get stored compilation arguments hash for a file.

        Args:
            file_path: Path to source file

        Returns:
            Stored hash, or empty string if not found

        Use Case:
            Check if compilation arguments changed for a specific file
            without loading all commands.
        """
        if not hasattr(self.cache, "conn"):
            return ""

        try:
            cursor = self.cache.conn.execute(
                """
                SELECT compile_args_hash FROM file_metadata
                WHERE file_path = ?
            """,
                (file_path,),
            )

            row = cursor.fetchone()
            if row:
                return row[0] or ""

            return ""

        except Exception as e:
            diagnostics.warning(f"Error getting stored commands hash: {e}")
            return ""

    def has_args_changed(self, file_path: str, current_args: List[str]) -> bool:
        """
        Check if compilation arguments changed for a file.

        Convenience method that compares current args with stored hash.

        Args:
            file_path: Path to source file
            current_args: Current compilation arguments

        Returns:
            True if arguments changed, False if unchanged or not stored

        Example:
            >>> differ.has_args_changed(
            ...     "main.cpp",
            ...     ["-std=c++20", "-O3"]
            ... )
            True  # If stored args were different
        """
        stored_hash = self.get_stored_commands_hash(file_path)

        if not stored_hash:
            # No stored hash = assume changed (conservative)
            return True

        current_hash = self._hash_args(current_args)
        return current_hash != stored_hash

    def clear_stored_commands(self) -> int:
        """
        Clear all stored compilation command hashes.

        Useful for:
        - Full re-analysis
        - Testing
        - Resetting after major changes

        Returns:
            Number of records cleared
        """
        if not hasattr(self.cache, "conn"):
            return 0

        try:
            cursor = self.cache.conn.execute("""
                UPDATE file_metadata
                SET compile_args_hash = NULL
            """)

            cleared = cursor.rowcount
            self.cache.conn.commit()

            diagnostics.info(f"Cleared {cleared} stored command hashes")
            return cleared

        except Exception as e:
            diagnostics.error(f"Failed to clear command hashes: {e}")
            self.cache.conn.rollback()
            return 0
