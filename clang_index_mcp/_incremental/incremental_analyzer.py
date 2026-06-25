"""Incremental Analysis Coordinator.

This module coordinates incremental analysis by detecting changes and
selectively re-analyzing only affected files.

Key Features:
- Orchestrates change detection and re-analysis
- Handles header changes with dependency cascade
- Handles source file changes (isolated)
- Handles compile_commands.json changes (per-entry diff)
- Provides detailed analysis results

Usage:
    incremental = IncrementalAnalyzer(ctx)
    result = incremental.perform_incremental_analysis()

    if result.files_analyzed > 0:
        print(f"Re-analyzed {result.files_analyzed} files")
"""

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional, Set

# Handle both package and script imports
try:
    from .._core import diagnostics
    from .._incremental import change_handler, worker_orchestrator
    from .._incremental.change_scanner import ChangeScanner, ChangeSet
    from .._symbols.indexing_callbacks import IndexingCallbacks
except ImportError:
    import diagnostics  # type: ignore[no-redef]
    import change_handler  # type: ignore[no-redef]
    import worker_orchestrator  # type: ignore[no-redef]
    from change_scanner import ChangeScanner, ChangeSet  # type: ignore[no-redef]
    from indexing_callbacks import IndexingCallbacks  # type: ignore[no-redef]

if TYPE_CHECKING:
    from concurrent.futures import Executor

    from .._contexts.incremental_context import IncrementalContext


@dataclass
class AnalysisResult:
    """
    Results from incremental analysis.

    Contains statistics and details about what was analyzed.
    """

    files_analyzed: int = 0
    files_removed: int = 0
    elapsed_seconds: float = 0.0
    changes: Optional[ChangeSet] = None

    @staticmethod
    def no_changes() -> "AnalysisResult":
        """Create result for no changes case."""
        return AnalysisResult(0, 0, 0.0, ChangeSet())

    def __str__(self):
        """String representation for logging."""
        return (
            f"Analyzed {self.files_analyzed} files, "
            f"removed {self.files_removed} files "
            f"in {self.elapsed_seconds:.2f}s"
        )


class IncrementalAnalyzer:
    """
    Coordinates incremental analysis based on detected changes.

    This is the main entry point for all incremental updates. It:
    1. Scans for changes using ChangeScanner
    2. Determines affected files using DependencyGraphBuilder
    3. Coordinates re-analysis via worker pool
    4. Provides detailed results

    The analysis prioritizes changes to minimize redundant work:
    - compile_commands.json changes handled first (broadest impact)
    - Header changes cascade to dependents
    - Source changes are isolated
    """

    def __init__(
        self,
        ctx: "IncrementalContext",
        is_interrupted: Optional[Callable[[], bool]] = None,
        shutdown_executor: Optional[Callable[["Executor", str], None]] = None,
    ):
        """
        Initialize incremental analyzer.

        Args:
            ctx: IncrementalContext with all required services
            is_interrupted: Callback to check if analysis was interrupted
            shutdown_executor: Callback to shut down an executor
        """
        self.ctx = ctx
        self.scanner = ChangeScanner(ctx)
        self._is_interrupted = is_interrupted or (lambda: False)
        self._shutdown_executor = shutdown_executor

    def perform_incremental_analysis(
        self,
        callbacks: Optional[IndexingCallbacks] = None,
    ) -> AnalysisResult:
        """
        Perform incremental analysis of changed files.

        This is the sophisticated incremental update path used by the MCP
        refresh_project tool with mode="incremental". It provides:
        - Header dependency cascade via DependencyGraphBuilder
        - Per-file compile_commands diffing via CompileCommandsDiffer
        - Detailed change categorization (added/modified/deleted)

        For simple cache-based startup refresh, use CppAnalyzer.refresh_if_needed.
        Both paths use shared primitives from file_utils:
        - hash_file() for consistent file content hashing
        - hash_compile_args() for consistent argument hashing

        This ensures both paths agree on whether files or arguments have
        changed, even though they process changes differently.

        Algorithm:
            1. Scan for all changes
            2. If no changes, return immediately
            3. Build set of files to re-analyze:
               - Files with changed compile args
               - Files affected by header changes (via dependency graph)
               - Modified source files
               - New files
            4. Remove deleted files from cache and indexes
            5. Re-analyze the minimal set
            6. Return detailed results

        Args:
            callbacks: Optional IndexingCallbacks with progress and wait_for_tools callbacks.

        Returns:
            AnalysisResult with statistics and details

        Performance:
            - Typical case (single file): <1s vs 30s full re-analysis
            - Header change (10 dependents): <5s vs 30s full re-analysis
        """
        diagnostics.info("Starting incremental analysis...")
        start_time = time.time()

        # 1. Scan for changes
        changes = self.scanner.scan_for_changes()

        if changes.is_empty():
            diagnostics.info("No changes detected, cache is up to date")
            return AnalysisResult.no_changes()

        diagnostics.info(f"Detected changes: {changes}")

        # 2. Build re-analysis set
        files_to_analyze: Set[str] = set()

        # Handle compile_commands.json change (broadest impact)
        if changes.compile_commands_changed:
            cc_affected = self._handle_compile_commands_change()
            files_to_analyze.update(cc_affected)

        # Handle header changes (cascade to dependents)
        for header in changes.modified_headers:
            dependents = self._handle_header_change(header)
            files_to_analyze.update(dependents)

        # Handle source changes (isolated)
        for source_file in changes.modified_files:
            self._handle_source_change(source_file)
            files_to_analyze.add(source_file)

        # Handle new files
        files_to_analyze.update(changes.added_files)

        # 3. Handle removed files
        for removed_file in changes.removed_files:
            self._remove_file(removed_file)

        # 4. Re-analyze files
        if files_to_analyze:
            diagnostics.info(f"Re-analyzing {len(files_to_analyze)} files...")
            analyzed_count = self._reanalyze_files(files_to_analyze, start_time, callbacks)
        else:
            analyzed_count = 0

        # 5. Build result
        elapsed = time.time() - start_time
        result = AnalysisResult(
            files_analyzed=analyzed_count,
            files_removed=len(changes.removed_files),
            elapsed_seconds=elapsed,
            changes=changes,
        )

        diagnostics.info(f"Incremental analysis complete: {result}")
        return result

    def _handle_compile_commands_change(self) -> Set[str]:
        """Handle compile_commands.json change."""
        return change_handler.handle_compile_commands_change(self.ctx)

    def _handle_header_change(self, header_path: str) -> Set[str]:
        """Handle header file change."""
        return change_handler.handle_header_change(self.ctx, header_path)

    def _handle_source_change(self, source_path: str) -> None:
        """Handle source file change."""
        return change_handler.handle_source_change(self.ctx, source_path)

    def _remove_file(self, file_path: str) -> None:
        """Remove a deleted file from cache, indexes, and dependency graph."""
        return change_handler.remove_file(self.ctx, file_path)

    def _reanalyze_files(
        self,
        files: Set[str],
        start_time: float,
        callbacks: Optional[IndexingCallbacks] = None,
    ) -> int:
        """Re-analyze a set of files using parallel processing."""
        return worker_orchestrator.reanalyze_files(
            self.ctx,
            files,
            start_time,
            callbacks,
            is_interrupted=self._is_interrupted,
            shutdown_executor=self._shutdown_executor,
        )
