"""Change Detection System for Incremental Analysis.

This module provides functionality to detect changes in the project since the
last analysis, enabling selective re-analysis of only affected files.

Key Features:
- Detect added, modified, and deleted source files
- Detect header file changes
- Detect compile_commands.json changes
- Track file content changes via MD5 hashing
- Unified ChangeSet representation

Usage:
    scanner = ChangeScanner(analyzer)
    changes = scanner.scan_for_changes()

    if not changes.is_empty():
        # Process changes
        for added_file in changes.added_files:
            analyzer.index_file(added_file)
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Set, cast

from .._core.file_scanner import FileScanner

# Handle both package and script imports
try:
    from .._core import diagnostics
except ImportError:
    import diagnostics  # type: ignore[no-redef]


class ChangeType(Enum):
    """Type of file change detected."""

    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    UNCHANGED = "unchanged"


@dataclass
class ChangeSet:
    """
    Container for all detected changes in a project.

    Represents the complete set of changes that have occurred since
    the last analysis, enabling incremental re-analysis.

    Attributes:
        compile_commands_changed: Whether compile_commands.json changed
        added_files: Set of newly added source files
        modified_files: Set of modified source files
        modified_headers: Set of modified header files
        removed_files: Set of deleted files (sources and headers)
    """

    compile_commands_changed: bool = False
    added_files: Set[str] = field(default_factory=set)
    modified_files: Set[str] = field(default_factory=set)
    modified_headers: Set[str] = field(default_factory=set)
    removed_files: Set[str] = field(default_factory=set)

    def is_empty(self) -> bool:
        """
        Check if no changes detected.

        Returns:
            True if no changes, False if any changes detected
        """
        return (
            not self.compile_commands_changed
            and not self.added_files
            and not self.modified_files
            and not self.modified_headers
            and not self.removed_files
        )

    def get_total_changes(self) -> int:
        """
        Get total number of changed files.

        Returns:
            Count of all changed files (not including compile_commands flag)
        """
        return (
            len(self.added_files)
            + len(self.modified_files)
            + len(self.modified_headers)
            + len(self.removed_files)
        )

    def __str__(self) -> str:
        """String representation for logging."""
        parts = []

        if self.compile_commands_changed:
            parts.append("compile_commands.json changed")

        if self.added_files:
            parts.append(f"{len(self.added_files)} added")

        if self.modified_files:
            parts.append(f"{len(self.modified_files)} modified")

        if self.modified_headers:
            parts.append(f"{len(self.modified_headers)} headers modified")

        if self.removed_files:
            parts.append(f"{len(self.removed_files)} removed")

        if not parts:
            return "No changes"

        return ", ".join(parts)


class ChangeScanner:
    """
    Unified change detection system for incremental analysis.

    Scans the project to detect all changes since last analysis:
    - File content changes (via MD5 hash comparison)
    - New and deleted files
    - compile_commands.json changes
    - Header file modifications

    Uses CppAnalyzer's cache and file scanner to determine what changed.
    """

    def __init__(self, analyzer):
        """
        Initialize change scanner.

        Args:
            analyzer: CppAnalyzer instance with cache and file scanner
        """
        self.analyzer = analyzer

    def scan_for_changes(self) -> ChangeSet:
        """
        Scan project for all changes since last analysis.

        Comprehensive scan that detects:
        1. compile_commands.json changes
        2. Added source files (new files in project)
        3. Modified source files (content changed)
        4. Modified headers (via header tracker)
        5. Deleted files (in cache but not on disk)

        Returns:
            ChangeSet containing all detected changes

        Algorithm:
            1. Check compile_commands.json first (affects everything)
            2. Scan current source files vs cached files
            3. Check header tracker for modified headers
            4. Identify deleted files (in cache but missing)
        """
        changeset = ChangeSet()

        # 1. Check compile_commands.json
        if self._check_compile_commands_changed():
            changeset.compile_commands_changed = True
            diagnostics.info("compile_commands.json has changed")

        # 2. Scan source files (excluding headers)
        self._scan_source_files(changeset)

        # 3. Scan tracked headers for modifications
        self._scan_tracked_headers(changeset)

        # 4. Check for deleted source files
        self._scan_deleted_files(changeset)

        # Log summary
        self._log_scan_result(changeset)

        return changeset

    def _scan_source_files(self, changeset: ChangeSet) -> None:
        """Detect added and modified source files, excluding headers."""
        all_cpp_files = self.analyzer.context.file_scanner.find_cpp_files()
        current_source_files = set()
        for file_path in all_cpp_files:
            if file_path.endswith(tuple(FileScanner.HEADER_EXTENSIONS)):
                continue
            current_source_files.add(file_path)

        for source_file in current_source_files:
            normalized_path = os.path.realpath(source_file)
            change_type = self._check_file_change(normalized_path)

            if change_type == ChangeType.ADDED:
                changeset.added_files.add(normalized_path)
                diagnostics.debug(f"Detected new file: {normalized_path}")
            elif change_type == ChangeType.MODIFIED:
                changeset.modified_files.add(normalized_path)
                diagnostics.debug(f"Detected modified file: {normalized_path}")

    def _scan_tracked_headers(self, changeset: ChangeSet) -> None:
        """Detect modified or deleted tracked headers."""
        tracked_headers = self.analyzer.context.cache_orchestrator.get_processed_headers()
        for header_path, tracked_hash in tracked_headers.items():
            normalized_header = os.path.realpath(header_path)

            if not Path(normalized_header).exists():
                changeset.removed_files.add(normalized_header)
                diagnostics.debug(f"Detected deleted header: {normalized_header}")
                continue

            try:
                current_hash = self.analyzer.context.cache_orchestrator._get_file_hash(
                    normalized_header
                )
                if current_hash != tracked_hash:
                    changeset.modified_headers.add(normalized_header)
                    diagnostics.debug(f"Detected modified header: {normalized_header}")
            except Exception as e:
                diagnostics.warning(f"Error checking header {normalized_header}: {e}")

    def _scan_deleted_files(self, changeset: ChangeSet) -> None:
        """Detect source files that are in cache but no longer on disk."""
        cached_files = self._get_cached_source_files()
        for cached_file in cached_files:
            normalized_cached = os.path.realpath(cached_file)
            if not Path(normalized_cached).exists():
                changeset.removed_files.add(normalized_cached)
                diagnostics.debug(f"Detected deleted file: {normalized_cached}")

    @staticmethod
    def _log_scan_result(changeset: ChangeSet) -> None:
        """Log a summary of detected changes."""
        if not changeset.is_empty():
            diagnostics.info(f"Change scan complete: {changeset}")
        else:
            diagnostics.debug("No changes detected")

    def _get_cached_hash(self, file_path: str) -> Optional[str]:
        """Get cached hash from database or in-memory cache. Returns None if not found."""
        try:
            metadata = self.analyzer.cache_manager.backend.get_file_metadata(file_path)
            if metadata:
                return str(metadata.get("file_hash", ""))
        except Exception as e:
            diagnostics.warning(f"Error getting metadata for {file_path}: {e}")

        if self.analyzer.context.symbol_store.has_file_hash(file_path):
            return str(self.analyzer.context.symbol_store.get_file_hash(file_path))

        return None

    def _compare_with_cached_hash(self, file_path: str, cached_hash: str) -> ChangeType:
        """Compare current file hash with cached hash."""
        try:
            current_hash = self.analyzer.context.cache_orchestrator._get_file_hash(file_path)
            if current_hash != cached_hash:
                return ChangeType.MODIFIED
            return ChangeType.UNCHANGED
        except Exception as e:
            diagnostics.warning(f"Error checking hash for {file_path}: {e}")
            return ChangeType.MODIFIED

    def _check_file_change(self, file_path: str) -> ChangeType:
        """
        Check if a file is new, modified, or unchanged.

        Args:
            file_path: Path to source file

        Returns:
            ChangeType indicating the type of change

        Algorithm:
            1. Query cache manager for file metadata (database)
            2. If not in database, fallback to in-memory file_hashes
            3. If not in cache at all → ADDED
            4. If in cache, compare MD5 hash
            5. Hash mismatch → MODIFIED
            6. Hash match → UNCHANGED
        """
        cached_hash = self._get_cached_hash(file_path)
        if cached_hash is None:
            return ChangeType.ADDED
        return self._compare_with_cached_hash(file_path, cached_hash)

    def _check_compile_commands_changed(self) -> bool:
        """
        Check if compile_commands.json has changed.

        Compares current file hash with stored hash from analyzer.

        Returns:
            True if changed, False if unchanged or doesn't exist
        """
        compile_commands_config = self.analyzer.config.get_compile_commands_config()
        cc_path = self.analyzer.project_root / compile_commands_config.compile_commands_path

        if not cc_path.exists():
            # If file doesn't exist, check if it existed before
            # (stored hash is non-empty means it existed)
            return bool(self.analyzer.context.cache_orchestrator.compile_commands_hash)

        # Calculate current hash
        try:
            current_hash = self.analyzer.context.cache_orchestrator._get_file_hash(str(cc_path))

            # Compare with stored hash
            if current_hash != self.analyzer.context.cache_orchestrator.compile_commands_hash:
                return True

            return False

        except Exception as e:
            diagnostics.warning(f"Error checking compile_commands.json: {e}")
            return False

    def _get_cached_source_files(self) -> Set[str]:
        """
        Get list of source files from cache.

        Returns:
            Set of file paths that were previously indexed

        Note:
            Only includes source files, not headers (those are in header_tracker)
        """
        try:
            # Query all files from file_metadata table
            if hasattr(self.analyzer.cache_manager.backend, "get_all_cached_file_paths"):
                return cast(
                    Set[str], self.analyzer.cache_manager.backend.get_all_cached_file_paths()
                )
            else:
                # Cached file list requires SQLite backend
                # Return empty set (will trigger full re-analysis)
                diagnostics.debug("Unable to get cached file list without SQLite backend")
                return set()

        except Exception as e:
            diagnostics.warning(f"Error getting cached files: {e}")
            return set()
