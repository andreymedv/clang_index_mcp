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
    incremental = IncrementalAnalyzer(analyzer)
    result = incremental.perform_incremental_analysis()

    if result.files_analyzed > 0:
        print(f"Re-analyzed {result.files_analyzed} files")
"""

import multiprocessing
import os
import time
from concurrent.futures import (
    Executor,
    ProcessPoolExecutor,
    as_completed,
)
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type

# Handle both package and script imports
try:
    from .._core import diagnostics
    from .._incremental.change_scanner import ChangeScanner, ChangeSet
    from .._symbols.indexing_callbacks import IndexingCallbacks
    from .._indexing.indexing_task_spec import IndexingTaskSpec
except ImportError:
    import diagnostics  # type: ignore[no-redef]
    from change_scanner import ChangeScanner, ChangeSet  # type: ignore[no-redef]
    from indexing_callbacks import IndexingCallbacks  # type: ignore[no-redef]
    from indexing_task_spec import IndexingTaskSpec  # type: ignore[no-redef]


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
    3. Coordinates re-analysis via CppAnalyzer
    4. Provides detailed results

    The analysis prioritizes changes to minimize redundant work:
    - compile_commands.json changes handled first (broadest impact)
    - Header changes cascade to dependents
    - Source changes are isolated
    """

    def __init__(self, analyzer):
        """
        Initialize incremental analyzer.

        Args:
            analyzer: CppAnalyzer instance with all components initialized
        """
        self.analyzer = analyzer
        self.scanner = ChangeScanner(analyzer)

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
        files_to_analyze = set()

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
        """
        Handle compile_commands.json change.

        Strategy:
            1. Load new compile_commands.json
            2. Compute diff with cached version
            3. Return files with changed/added/removed entries
            4. Invalidate all headers (compilation args affect preprocessing)

        Returns:
            Set of files to re-analyze
        """
        diagnostics.info("Handling compile_commands.json change...")

        # Get compile commands manager
        cc_manager = self.analyzer.context.compile_commands_manager
        assert cc_manager is not None

        # Get old commands (from current state)
        old_commands = cc_manager.file_to_command_map.copy()

        # Reload compile commands
        cc_manager._load_compile_commands()
        new_commands = cc_manager.file_to_command_map

        # Compute diff
        files_to_analyze: Set[str]
        if cc_manager.cache_backend is not None and hasattr(
            cc_manager.cache_backend, "set_compile_args_hash"
        ):
            # Extract argument lists from command dicts if needed
            def _extract_args(commands):
                result = {}
                for fp, cmd in commands.items():
                    if cmd and isinstance(cmd[0], dict):
                        result[fp] = cmd[0].get("arguments", [])
                    else:
                        result[fp] = cmd
                return result

            try:
                old_args = _extract_args(old_commands)
                new_args = _extract_args(new_commands)
            except (AttributeError, TypeError, IndexError):
                # If extraction fails (e.g., mock objects), pass through as-is
                old_args = old_commands
                new_args = new_commands

            added, removed, changed = cc_manager.compute_commands_diff(old_args, new_args)

            diagnostics.info(
                f"Compile commands diff: +{len(added)} -{len(removed)} ~{len(changed)}"
            )

            # Files to re-analyze
            files_to_analyze = added | changed

            # Store new commands
            cc_manager.store_command_hashes(new_args)
        else:
            # No SQLite backend, re-analyze all files from new commands
            files_to_analyze = set(new_commands.keys())
            diagnostics.warning("No SQLite backend, re-analyzing all compile_commands files")

        # Update compile_commands_hash
        self.analyzer.context.cache_orchestrator.compile_commands_hash = (
            cc_manager.get_compile_commands_hash()
        )

        # Invalidate ALL headers (args changed might affect preprocessing)
        # This is conservative but safe
        self.analyzer.context.cache_orchestrator.clear_header_tracker()
        diagnostics.info("Invalidated all header tracking due to compile commands change")

        return files_to_analyze

    def _handle_header_change(self, header_path: str) -> Set[str]:
        """
        Handle header file change.

        Strategy:
            1. Find all files that depend on this header (via dependency graph)
            2. Invalidate header in tracker (will be re-processed)
            3. Return set of dependents to re-analyze

        Args:
            header_path: Path to modified header

        Returns:
            Set of files to re-analyze (transitive dependents)
        """
        diagnostics.info(f"Handling header change: {header_path}")

        # Find dependents via dependency graph
        if self.analyzer.context.call_graph_service.dependency_graph:
            dependents = self.analyzer.context.call_graph_service.dependency_graph.find_transitive_dependents(
                header_path
            )
            diagnostics.info(f"Header {header_path} affects {len(dependents)} files")
        else:
            # No dependency graph, conservative: re-analyze everything
            diagnostics.warning("No dependency graph, cannot determine affected files")
            dependents = set()

        # Invalidate header in tracker
        self.analyzer.context.cache_orchestrator.invalidate_header(header_path)

        result: Set[str] = dependents
        return result

    def _handle_source_change(self, source_path: str):
        """
        Handle source file change.

        Strategy:
            Source files are isolated - only re-analyze this file.
            Headers it includes will be checked via first-win strategy.

        Args:
            source_path: Path to modified source file

        Note:
            The file will be added to files_to_analyze by the caller.
            This method just does any necessary prep work.
        """
        diagnostics.debug(f"Handling source change: {source_path}")
        # No additional work needed - file will be re-analyzed

    def _remove_file(self, file_path: str):
        """
        Remove file from cache, indexes, and dependency graph.

        Args:
            file_path: Path to deleted file
        """
        diagnostics.info(f"Removing deleted file: {file_path}")
        try:
            self.analyzer.context.cache_orchestrator.remove_deleted_file(file_path)
        except Exception as e:
            diagnostics.warning(f"Failed to remove deleted file {file_path}: {e}")

    def _remove_symbol_from_index(self, symbol: Any) -> None:
        """Remove a symbol from the appropriate index (class or function)."""
        self.analyzer.context.symbol_store.remove_symbol_from_indexes(symbol)

    def _handle_definition_wins(self, symbol: Any, existing: Any) -> bool:
        """Apply 'definition wins' rule for duplicate symbols. Returns True if symbol should be skipped."""
        if symbol.is_definition and not existing.is_definition:
            # Remove old declaration from index
            self._remove_symbol_from_index(existing)
            return False
        else:
            # Keep existing
            return True

    def _add_symbol_to_indices(self, symbol: Any) -> None:
        """Add a symbol to the analyzer's indices."""
        self.analyzer.context.symbol_store.add_symbol_to_indexes(symbol)

    def _merge_symbols(self, symbols: List[Any]) -> None:
        """Merge symbols from a worker process into the main analyzer index."""
        with self.analyzer.context.concurrency.index_lock:
            for symbol in symbols:
                # Apply same deduplication logic as index_project
                skip_symbol = False

                store = self.analyzer.context.symbol_store
                if symbol.usr and store.contains_usr(symbol.usr):
                    existing = store.get_symbol_by_usr(symbol.usr)
                    assert existing is not None
                    skip_symbol = self._handle_definition_wins(symbol, existing)

                if not skip_symbol:
                    self._add_symbol_to_indices(symbol)

    def _get_file_compile_args(self, file_list: List[str]) -> Dict[str, List[str]]:
        """Precompute compile arguments for a list of files."""
        file_compile_args = {}
        from pathlib import Path

        for file_path in file_list:
            file_path_obj = Path(file_path)
            args = self.analyzer.context.compilation_env.get_compile_args_for_file(file_path_obj)
            file_compile_args[file_path] = args
        return file_compile_args

    def _create_executor(
        self, max_workers: int
    ) -> Tuple[Optional[multiprocessing.context.BaseContext], Type[ProcessPoolExecutor], str]:
        """Create a process pool executor and its spawn context."""
        mp_context = None
        msg: str

        # Use 'spawn' context to avoid inheriting open file descriptors
        try:
            mp_context = multiprocessing.get_context("spawn")
            msg = (
                f"Incremental refresh: Using ProcessPoolExecutor (spawn) with {max_workers} workers"
            )
        except Exception as e:
            diagnostics.warning(f"Failed to use 'spawn' context: {e}. Falling back to default.")
            mp_context = None
            msg = f"Incremental refresh: Using ProcessPoolExecutor with {max_workers} workers"

        return mp_context, ProcessPoolExecutor, msg

    def _process_future_result(self, result: Any, file_path: str) -> Tuple[bool, bool]:
        """Process the result from a future and merge it into the analyzer."""
        # ProcessPoolExecutor returns (file_path, success, was_cached, symbols, call_sites, processed_headers)
        _, success, was_cached, symbols, call_sites, processed_headers = result

        # Merge symbols into main process (same logic as index_project)
        if success and symbols:
            self._merge_symbols(symbols)

        # Restore call sites
        if call_sites:
            for cs_dict in call_sites:
                self.analyzer.context.call_graph_service.call_graph_analyzer.add_call(
                    cs_dict["caller_usr"],
                    cs_dict["callee_usr"],
                    cs_dict["file"],
                    cs_dict["line"],
                    cs_dict.get("column"),
                )

        # Merge header tracking
        if processed_headers:
            for header_path, header_hash in processed_headers.items():
                self.analyzer.context.cache_orchestrator.mark_header_completed(
                    header_path, header_hash
                )

        # Update file hash tracking
        file_hash = self.analyzer.context.cache_orchestrator._get_file_hash(file_path)
        self.analyzer.context.symbol_store.set_file_hash(file_path, file_hash)

        return success, was_cached

    def _report_progress(
        self,
        progress_callback: Callable,
        i: int,
        total: int,
        analyzed: int,
        failed: int,
        start_time: float,
        file_path: str,
    ) -> None:
        """Calculate and report indexing progress via callback."""
        processed = i + 1
        # Report every 10 files or at completion
        if processed % 10 == 0 or processed == total:
            try:
                # Import IndexingProgress here to avoid circular dependency
                from .._mcp.state_manager import IndexingProgress

                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                eta = (total - processed) / rate if rate > 0 else 0

                estimated_completion = datetime.now() + timedelta(seconds=eta) if eta > 0 else None

                progress = IndexingProgress(
                    total_files=total,
                    indexed_files=analyzed,
                    failed_files=failed,
                    cache_hits=0,  # Not tracked during refresh
                    current_file=file_path if processed < total else None,
                    start_time=datetime.fromtimestamp(start_time),
                    estimated_completion=estimated_completion,
                )

                progress_callback(progress)
            except Exception as e:
                # Don't fail refresh if progress callback fails
                diagnostics.debug(f"Progress callback failed: {e}")

    def _submit_tasks(
        self,
        executor: Executor,
        file_list: List[str],
    ) -> Dict[Any, str]:
        """Submit re-analysis tasks to the process pool executor."""
        from .._indexing.worker_pool import _process_file_worker

        # Get project configuration for workers
        project_root = str(self.analyzer.project_root)
        config_file_str = (
            str(self.analyzer.project_identity.config_file_path)
            if self.analyzer.project_identity.config_file_path
            else None
        )
        include_dependencies = self.analyzer.context.compilation_env.include_dependencies

        # Task 3.2: Prepare compile args for all files in main process
        # This avoids loading CompileCommandsManager in each worker (~6-10 GB memory savings)
        file_compile_args = self._get_file_compile_args(file_list)

        # Submit all files to worker processes
        return {
            executor.submit(
                _process_file_worker,
                IndexingTaskSpec(
                    project_root=project_root,
                    config_file=config_file_str,
                    file_path=os.path.abspath(file_path),
                    force=True,  # force=True for refresh
                    include_dependencies=include_dependencies,
                    compile_args=file_compile_args[file_path],  # Task 3.2: precomputed args
                ),
            ): file_path
            for file_path in file_list
        }

    def _process_loop(
        self,
        executor: Executor,
        future_to_file: Dict[Any, str],
        start_time: float,
        total: int,
        callbacks: Optional[IndexingCallbacks],
    ) -> Tuple[int, int]:
        """Process results from futures in a loop."""
        analyzed = 0
        failed = 0

        for i, future in enumerate(as_completed(future_to_file)):
            # Check for interruption
            if getattr(self.analyzer, "_interrupted", False) is True:
                # Cancel all pending futures
                for f in future_to_file:
                    f.cancel()
                diagnostics.info("Incremental refresh interrupted by request")
                raise KeyboardInterrupt("Incremental refresh interrupted by request")

            if callbacks and callbacks.wait_for_tools:
                callbacks.wait_for_tools()

            file_path = future_to_file[future]
            try:
                result = future.result()
                success, was_cached = self._process_future_result(result, file_path)

                if success:
                    analyzed += 1
                    diagnostics.debug(f"Re-analyzed: {file_path}")
                else:
                    failed += 1
                    diagnostics.warning(f"Failed to re-analyze: {file_path}")

            except Exception as e:
                failed += 1
                diagnostics.error(f"Error re-analyzing {file_path}: {e}")

            # Report progress periodically
            progress_callback = callbacks.progress if callbacks else None
            if progress_callback:
                self._report_progress(
                    progress_callback, i, total, analyzed, failed, start_time, file_path
                )

        return analyzed, failed

    def _reanalyze_files(
        self,
        files: Set[str],
        start_time: float,
        callbacks: Optional[IndexingCallbacks] = None,
    ) -> int:
        """
        Re-analyze a set of files using parallel processing.

        Uses the analyzer's ProcessPoolExecutor-based indexing infrastructure
        to re-parse files concurrently, providing the same 6-7x speedup as
        initial indexing on multi-core systems.

        Args:
            files: Set of file paths to re-analyze
            start_time: Unix timestamp when analysis started (for ETA calculation)
            callbacks: Optional IndexingCallbacks with progress and wait_for_tools callbacks

        Returns:
            Number of files successfully analyzed
        """
        if not files:
            return 0

        analyzed = 0
        failed = 0
        total = len(files)
        file_list = list(files)  # Convert to list for processing

        # Use analyzer's parallel processing infrastructure (same pattern as index_project)
        # ProcessPoolExecutor provides true parallelism (GIL bypass) for 6-7x speedup
        max_workers = getattr(self.analyzer, "max_workers", None)

        if max_workers is None or not isinstance(max_workers, int):
            max_workers = os.cpu_count() or 4

        mp_context, _, msg = self._create_executor(max_workers)
        diagnostics.debug(msg)

        executor: Optional[Executor] = None
        try:
            if mp_context:
                executor = ProcessPoolExecutor(max_workers=max_workers, mp_context=mp_context)
            else:
                executor = ProcessPoolExecutor(max_workers=max_workers)

            future_to_file = self._submit_tasks(executor, file_list)

            # Process results as they complete
            analyzed, failed = self._process_loop(
                executor,
                future_to_file,
                start_time,
                total,
                callbacks,
            )
        except KeyboardInterrupt:
            # Gracefully handle Ctrl-C or requested interruption
            diagnostics.info("\nIncremental refresh interrupted")
            if executor is not None:
                # Call the shared shutdown helper on the main analyzer
                self.analyzer._shutdown_executor(executor, name="Incremental Refresh")
            raise

        finally:
            if executor is not None:
                # Final cleanup (non-blocking)
                try:
                    executor.shutdown(wait=False)
                except Exception:
                    pass

        return analyzed
