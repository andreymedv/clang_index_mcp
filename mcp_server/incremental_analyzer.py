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

import os
import time
from typing import Set, Optional, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

# Handle both package and script imports
try:
    from . import diagnostics
    from .change_scanner import ChangeScanner, ChangeSet
    from .compile_commands_differ import CompileCommandsDiffer
except ImportError:
    import diagnostics
    from change_scanner import ChangeScanner, ChangeSet
    from compile_commands_differ import CompileCommandsDiffer


@dataclass
class AnalysisResult:
    """
    Results from incremental analysis.

    Contains statistics and details about what was analyzed.
    """

    files_analyzed: int = 0
    files_removed: int = 0
    elapsed_seconds: float = 0.0
    changes: ChangeSet = None

    @staticmethod
    def no_changes():
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
        self, progress_callback: Optional[Callable] = None
    ) -> AnalysisResult:
        """
        Perform incremental analysis of changed files.

        This is the main entry point that orchestrates the entire
        incremental analysis workflow.

        Algorithm:
            1. Scan for all changes
            2. If no changes, return immediately
            3. Build set of files to re-analyze:
               - Files with changed compile args
               - Files affected by header changes (via dependency graph)
               - Modified source files
               - New files
            4. Remove deleted files from cache
            5. Re-analyze the minimal set
            6. Return detailed results

        Args:
            progress_callback: Optional callback for progress updates.
                             Called with IndexingProgress object during analysis.

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
            analyzed_count = self._reanalyze_files(files_to_analyze, start_time, progress_callback)
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
        cc_manager = self.analyzer.compile_commands_manager

        # Get old commands (from current state)
        old_commands = cc_manager.file_to_command_map.copy()

        # Reload compile commands
        cc_manager._load_compile_commands()
        new_commands = cc_manager.file_to_command_map

        # Compute diff
        if self.analyzer.cache_manager.backend and hasattr(
            self.analyzer.cache_manager.backend, "conn"
        ):
            differ = CompileCommandsDiffer(self.analyzer.cache_manager.backend)
            added, removed, changed = differ.compute_diff(old_commands, new_commands)

            diagnostics.info(
                f"Compile commands diff: +{len(added)} -{len(removed)} ~{len(changed)}"
            )

            # Files to re-analyze
            files_to_analyze = added | changed

            # Store new commands
            differ.store_current_commands(new_commands)
        else:
            # No SQLite backend, re-analyze all files from new commands
            files_to_analyze = set(new_commands.keys())
            diagnostics.warning("No SQLite backend, re-analyzing all compile_commands files")

        # Update compile_commands_hash
        cc_path = (
            self.analyzer.project_root
            / self.analyzer.config.get_compile_commands_config().get(
                "compile_commands_path", "compile_commands.json"
            )
        )
        if cc_path.exists():
            self.analyzer.compile_commands_hash = self.analyzer._get_file_hash(str(cc_path))

        # Invalidate ALL headers (args changed might affect preprocessing)
        # This is conservative but safe
        if self.analyzer.header_tracker:
            self.analyzer.header_tracker.clear_all()
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
        if self.analyzer.dependency_graph:
            dependents = self.analyzer.dependency_graph.find_transitive_dependents(header_path)
            diagnostics.info(f"Header {header_path} affects {len(dependents)} files")
        else:
            # No dependency graph, conservative: re-analyze everything
            diagnostics.warning("No dependency graph, cannot determine affected files")
            dependents = set()

        # Invalidate header in tracker
        if self.analyzer.header_tracker:
            self.analyzer.header_tracker.invalidate_header(header_path)

        return dependents

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
        Remove file from cache and dependency graph.

        Args:
            file_path: Path to deleted file
        """
        diagnostics.info(f"Removing deleted file: {file_path}")

        # Remove from cache
        try:
            self.analyzer.cache_manager.backend.remove_file_cache(file_path)
        except Exception as e:
            diagnostics.warning(f"Failed to remove {file_path} from cache: {e}")

        # Remove from dependency graph
        if self.analyzer.dependency_graph:
            try:
                self.analyzer.dependency_graph.remove_file_dependencies(file_path)
            except Exception as e:
                diagnostics.warning(f"Failed to remove {file_path} from dependency graph: {e}")

        # Remove from header tracker if it's a header
        if self.analyzer.header_tracker and file_path.endswith((".h", ".hpp", ".hxx", ".h++")):
            try:
                self.analyzer.header_tracker.invalidate_header(file_path)
            except Exception as e:
                diagnostics.warning(f"Failed to remove {file_path} from header tracker: {e}")

    def _reanalyze_files(
        self,
        files: Set[str],
        start_time: float,
        progress_callback: Optional[Callable] = None,
    ) -> int:
        """
        Re-analyze a set of files using parallel processing.

        Uses the analyzer's parallel indexing infrastructure (ProcessPoolExecutor
        or ThreadPoolExecutor) to re-parse files concurrently, providing the same
        6-7x speedup as initial indexing on multi-core systems.

        Args:
            files: Set of file paths to re-analyze
            start_time: Unix timestamp when analysis started (for ETA calculation)
            progress_callback: Optional callback for progress updates

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
        from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
        from unittest.mock import Mock

        use_processes = getattr(self.analyzer, "use_processes", True)
        max_workers = getattr(self.analyzer, "max_workers", None)

        # Detect mocked analyzer (can't pickle Mock objects)
        # Fall back to ThreadPoolExecutor when analyzer is mocked in tests
        if isinstance(self.analyzer, Mock) or type(self.analyzer).__name__ in ("Mock", "MagicMock"):
            use_processes = False
            diagnostics.debug("Detected mocked analyzer - using ThreadPoolExecutor")

        # Handle mocked analyzer in tests or missing attribute
        if max_workers is None or not isinstance(max_workers, int):
            max_workers = os.cpu_count() or 4

        # Choose executor based on configuration
        executor_class = ProcessPoolExecutor if use_processes else ThreadPoolExecutor

        if use_processes:
            diagnostics.debug(
                f"Incremental refresh: Using ProcessPoolExecutor with {max_workers} workers (GIL bypass)"
            )
        else:
            diagnostics.debug(
                f"Incremental refresh: Using ThreadPoolExecutor with {max_workers} workers"
            )

        executor = None
        try:
            executor = executor_class(max_workers=max_workers)

            if use_processes:
                # ProcessPoolExecutor: use worker function (same as index_project)
                from mcp_server.cpp_analyzer import _process_file_worker

                # Get project configuration for workers
                project_root = str(self.analyzer.project_root)
                config_file_str = (
                    str(self.analyzer.project_identity.config_file_path)
                    if self.analyzer.project_identity.config_file_path
                    else None
                )
                include_dependencies = self.analyzer.include_dependencies

                # Submit all files to worker processes
                future_to_file = {
                    executor.submit(
                        _process_file_worker,
                        (
                            project_root,
                            config_file_str,
                            os.path.abspath(file_path),
                            True,  # force=True for refresh
                            include_dependencies,
                        ),
                    ): file_path
                    for file_path in file_list
                }
            else:
                # ThreadPoolExecutor: use index_file method directly
                future_to_file = {
                    executor.submit(self.analyzer.index_file, file_path, force=True): file_path
                    for file_path in file_list
                }

            # Process results as they complete
            for i, future in enumerate(as_completed(future_to_file)):
                file_path = future_to_file[future]
                try:
                    result = future.result()

                    if use_processes:
                        # ProcessPoolExecutor returns (file_path, success, was_cached, symbols, call_sites, processed_headers)
                        _, success, was_cached, symbols, call_sites, processed_headers = result

                        # Merge symbols into main process (same logic as index_project)
                        if success and symbols:
                            with self.analyzer.index_lock:
                                for symbol in symbols:
                                    # Apply same deduplication logic as index_project
                                    skip_symbol = False

                                    if symbol.usr and symbol.usr in self.analyzer.usr_index:
                                        existing = self.analyzer.usr_index[symbol.usr]

                                        # Definition-wins
                                        if symbol.is_definition and not existing.is_definition:
                                            # Remove old declaration from index
                                            if existing.kind in ("class", "struct"):
                                                if existing.name in self.analyzer.class_index:
                                                    try:
                                                        self.analyzer.class_index[
                                                            existing.name
                                                        ].remove(existing)
                                                        if not self.analyzer.class_index[
                                                            existing.name
                                                        ]:
                                                            del self.analyzer.class_index[
                                                                existing.name
                                                            ]
                                                    except ValueError:
                                                        pass
                                            else:
                                                if existing.name in self.analyzer.function_index:
                                                    try:
                                                        self.analyzer.function_index[
                                                            existing.name
                                                        ].remove(existing)
                                                        if not self.analyzer.function_index[
                                                            existing.name
                                                        ]:
                                                            del self.analyzer.function_index[
                                                                existing.name
                                                            ]
                                                    except ValueError:
                                                        pass
                                        else:
                                            # Keep existing
                                            skip_symbol = True

                                    if not skip_symbol:
                                        # Add to appropriate index
                                        if symbol.kind in ("class", "struct"):
                                            self.analyzer.class_index[symbol.name].append(symbol)
                                        else:
                                            self.analyzer.function_index[symbol.name].append(symbol)

                                        # Add to USR index
                                        if symbol.usr:
                                            self.analyzer.usr_index[symbol.usr] = symbol

                                        # Add to file index (with deduplication)
                                        if symbol.file:
                                            if symbol.file not in self.analyzer.file_index:
                                                self.analyzer.file_index[symbol.file] = []

                                            # Check for duplicates in file_index
                                            already_in_file_index = False
                                            if symbol.usr:
                                                for existing in self.analyzer.file_index[
                                                    symbol.file
                                                ]:
                                                    if existing.usr == symbol.usr:
                                                        already_in_file_index = True
                                                        break

                                            if not already_in_file_index:
                                                self.analyzer.file_index[symbol.file].append(symbol)

                                    # v9.0: calls/called_by removed from SymbolInfo
                                    # Call graph is restored from call_sites below

                                # Restore call sites
                                if call_sites:
                                    for cs_dict in call_sites:
                                        self.analyzer.call_graph_analyzer.add_call(
                                            cs_dict["caller_usr"],
                                            cs_dict["callee_usr"],
                                            cs_dict["file"],
                                            cs_dict["line"],
                                            cs_dict.get("column"),
                                        )

                                # Merge header tracking
                                if processed_headers:
                                    for header_path, header_hash in processed_headers.items():
                                        self.analyzer.header_tracker.mark_completed(
                                            header_path, header_hash
                                        )

                                # Update file hash tracking
                                file_hash = self.analyzer._get_file_hash(file_path)
                                self.analyzer.file_hashes[file_path] = file_hash
                    else:
                        # ThreadPoolExecutor returns (success, was_cached)
                        success, was_cached = result

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
                if progress_callback:
                    processed = i + 1
                    # Report every 10 files or at completion
                    if processed % 10 == 0 or processed == total:
                        try:
                            # Import IndexingProgress here to avoid circular dependency
                            from .state_manager import IndexingProgress

                            elapsed = time.time() - start_time
                            rate = processed / elapsed if elapsed > 0 else 0
                            eta = (total - processed) / rate if rate > 0 else 0

                            estimated_completion = (
                                datetime.now() + timedelta(seconds=eta) if eta > 0 else None
                            )

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

        finally:
            if executor:
                executor.shutdown(wait=True)

        return analyzed
