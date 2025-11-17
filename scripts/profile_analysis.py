#!/usr/bin/env python3
"""
Profile the performance of C++ analysis to identify bottlenecks.

This script instruments the analyzer to measure time spent in different phases:
- File I/O (reading source files)
- libclang parsing (TU creation)
- AST traversal
- Lock contention (waiting for index_lock)
- Bulk writes
- Cache operations

Usage:
    python scripts/profile_analysis.py [project_root]
"""

import sys
import os
import time
import threading
from pathlib import Path
from collections import defaultdict
import json

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server import diagnostics


class ProfiledAnalyzer(CppAnalyzer):
    """Instrumented analyzer that tracks timing for different operations."""

    def __init__(self, project_root: str):
        super().__init__(project_root)

        # Thread-safe timing collectors
        self.timing_lock = threading.Lock()
        self.timings = defaultdict(list)

        # Per-thread timing storage
        self.thread_timings = threading.local()

    def _record_timing(self, category: str, duration: float):
        """Record a timing measurement."""
        with self.timing_lock:
            self.timings[category].append(duration)

    def _start_timer(self, name: str):
        """Start a timer for the current thread."""
        if not hasattr(self.thread_timings, 'timers'):
            self.thread_timings.timers = {}
        self.thread_timings.timers[name] = time.time()

    def _stop_timer(self, name: str, category: str):
        """Stop a timer and record the duration."""
        if not hasattr(self.thread_timings, 'timers'):
            return

        start_time = self.thread_timings.timers.get(name)
        if start_time:
            duration = time.time() - start_time
            self._record_timing(category, duration)
            del self.thread_timings.timers[name]

    def _bulk_write_symbols(self):
        """Instrumented bulk write."""
        self._start_timer('bulk_write')

        # Measure lock wait time
        lock_wait_start = time.time()
        with self.index_lock:
            lock_acquired = time.time()
            self._record_timing('lock_wait', lock_acquired - lock_wait_start)

            # Call original implementation (inline to measure)
            symbols_buffer, calls_buffer = self._get_thread_local_buffers()

            if not symbols_buffer and not calls_buffer:
                return 0

            added_count = 0

            # Add all collected symbols
            for info in symbols_buffer:
                if info.usr and info.usr in self.usr_index:
                    continue

                if info.kind in ("class", "struct"):
                    self.class_index[info.name].append(info)
                else:
                    self.function_index[info.name].append(info)

                if info.usr:
                    self.usr_index[info.usr] = info

                if info.file:
                    if info.file not in self.file_index:
                        self.file_index[info.file] = []
                    self.file_index[info.file].append(info)

                added_count += 1

            # Add all collected call relationships
            for caller_usr, called_usr in calls_buffer:
                self.call_graph_analyzer.add_call(caller_usr, called_usr)

            # Clear buffers
            symbols_buffer.clear()
            calls_buffer.clear()

        self._stop_timer('bulk_write', 'bulk_write')
        return added_count

    def _index_translation_unit(self, tu, source_file: str):
        """Instrumented TU indexing."""
        self._start_timer('ast_traversal')
        result = super()._index_translation_unit(tu, source_file)
        self._stop_timer('ast_traversal', 'ast_traversal')
        return result

    def index_file(self, file_path: str, force: bool = False):
        """Instrumented file indexing."""
        self._start_timer('total_file')

        file_path = os.path.abspath(file_path)
        current_hash = self._get_file_hash(file_path)

        # Get compilation arguments
        file_path_obj = Path(file_path)
        args = self.compile_commands_manager.get_compile_args_with_fallback(file_path_obj)

        if not self.compile_commands_manager.is_file_supported(file_path_obj):
            vcpkg_include = self.project_root / "vcpkg_installed" / "x64-windows" / "include"
            if vcpkg_include.exists():
                args.append(f'-I{vcpkg_include}')

            vcpkg_paths = [
                "C:/vcpkg/installed/x64-windows/include",
                "C:/dev/vcpkg/installed/x64-windows/include"
            ]
            for path in vcpkg_paths:
                if Path(path).exists():
                    args.append(f'-I{path}')
                    break

        compile_args_hash = self._compute_compile_args_hash(args)

        # Try cache
        if not force:
            self._start_timer('cache_load')
            cache_data = self._load_file_cache(file_path, current_hash, compile_args_hash)
            self._stop_timer('cache_load', 'cache_load')

            if cache_data is not None:
                if not cache_data['success']:
                    retry_count = cache_data['retry_count']
                    if retry_count >= self.max_parse_retries:
                        self._stop_timer('total_file', 'total_file_cached_skip')
                        return (False, True)
                else:
                    # Load from cache (includes lock acquisition for index updates)
                    with self.index_lock:
                        # Apply cached symbols to indexes
                        cached_symbols = cache_data['symbols']

                        if file_path in self.file_index:
                            for info in self.file_index[file_path]:
                                if info.kind in ("class", "struct"):
                                    self.class_index[info.name] = [
                                        i for i in self.class_index[info.name] if i.file != file_path
                                    ]
                                else:
                                    self.function_index[info.name] = [
                                        i for i in self.function_index[info.name] if i.file != file_path
                                    ]

                        self.file_index[file_path] = cached_symbols
                        for symbol in cached_symbols:
                            if symbol.kind in ("class", "struct"):
                                self.class_index[symbol.name].append(symbol)
                            else:
                                self.function_index[symbol.name].append(symbol)

                            if symbol.usr:
                                self.usr_index[symbol.usr] = symbol

                            if symbol.calls:
                                for called_usr in symbol.calls:
                                    self.call_graph_analyzer.add_call(symbol.usr, called_usr)
                            if symbol.called_by:
                                for caller_usr in symbol.called_by:
                                    self.call_graph_analyzer.add_call(caller_usr, symbol.usr)

                        self.file_hashes[file_path] = current_hash

                    self._stop_timer('total_file', 'total_file_cached')
                    return (True, True)

        # Parse file
        retry_count = 0
        if not force:
            cache_data = self._load_file_cache(file_path, current_hash, compile_args_hash)
            if cache_data is not None and not cache_data['success']:
                retry_count = cache_data['retry_count'] + 1

        try:
            # libclang parsing
            self._start_timer('libclang_parse')
            index = self._get_thread_index()

            from clang.cindex import TranslationUnit
            tu = index.parse(
                file_path,
                args=args,
                options=TranslationUnit.PARSE_INCOMPLETE |
                       TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
            )
            self._stop_timer('libclang_parse', 'libclang_parse')

            if not tu:
                error_msg = "Failed to create translation unit"
                self.cache_manager.log_parse_error(
                    file_path, Exception(error_msg), current_hash, compile_args_hash, retry_count
                )
                self._save_file_cache(
                    file_path, [], current_hash, compile_args_hash,
                    success=False, error_message=error_msg[:200], retry_count=retry_count
                )
                self._stop_timer('total_file', 'total_file_failed')
                return (False, False)

            # Check diagnostics
            from mcp_server.cpp_analyzer import CppAnalyzer as BaseAnalyzer
            error_diagnostics, warning_diagnostics = BaseAnalyzer._extract_diagnostics(self, tu)

            if error_diagnostics:
                formatted_errors = BaseAnalyzer._format_diagnostics(self, error_diagnostics, max_count=5)
                full_error_msg = f"libclang parsing errors ({len(error_diagnostics)} total):\n{formatted_errors}"
                cache_error_msg = full_error_msg[:200]

                self.cache_manager.log_parse_error(
                    file_path, Exception(full_error_msg), current_hash, compile_args_hash, retry_count
                )
                self._save_file_cache(
                    file_path, [], current_hash, compile_args_hash,
                    success=False, error_message=cache_error_msg, retry_count=retry_count
                )

                self._stop_timer('total_file', 'total_file_failed')
                return (False, False)

            # Clear old entries
            with self.index_lock:
                if file_path in self.file_index:
                    for info in self.file_index[file_path]:
                        if info.kind in ("class", "struct"):
                            self.class_index[info.name] = [
                                i for i in self.class_index[info.name] if i.file != file_path
                            ]
                        else:
                            self.function_index[info.name] = [
                                i for i in self.function_index[info.name] if i.file != file_path
                            ]

                    self.file_index[file_path].clear()

            # Process TU (includes AST traversal and bulk write)
            extraction_result = self._index_translation_unit(tu, file_path)

            # Get symbols and populate call graph
            collected_symbols = []
            with self.index_lock:
                if file_path in self.file_index:
                    collected_symbols = self.file_index[file_path].copy()

                    for symbol in collected_symbols:
                        if symbol.usr and symbol.kind in ("function", "method"):
                            calls = self.call_graph_analyzer.find_callees(symbol.usr)
                            if calls:
                                symbol.calls = list(calls)
                            callers = self.call_graph_analyzer.find_callers(symbol.usr)
                            if callers:
                                symbol.called_by = list(callers)

            # Save cache
            self._start_timer('cache_save')
            self._save_file_cache(
                file_path, collected_symbols, current_hash, compile_args_hash,
                success=True, error_message=None, retry_count=0
            )
            self._stop_timer('cache_save', 'cache_save')

            # Update tracking
            with self.index_lock:
                self.translation_units[file_path] = tu
                self.file_hashes[file_path] = current_hash

            self._stop_timer('total_file', 'total_file_success')
            return (True, False)

        except Exception as e:
            self.cache_manager.log_parse_error(
                file_path, e, current_hash, compile_args_hash, retry_count
            )

            error_msg = str(e)[:200]
            self._save_file_cache(
                file_path, [], current_hash, compile_args_hash,
                success=False, error_message=error_msg, retry_count=retry_count
            )

            self._stop_timer('total_file', 'total_file_exception')
            return (False, False)

    def print_timing_report(self):
        """Print a detailed timing report."""
        print("\n" + "="*80)
        print("PERFORMANCE PROFILING REPORT")
        print("="*80)

        def compute_stats(values):
            if not values:
                return {"count": 0, "total": 0, "avg": 0, "min": 0, "max": 0}
            return {
                "count": len(values),
                "total": sum(values),
                "avg": sum(values) / len(values),
                "min": min(values),
                "max": max(values)
            }

        categories = [
            ('total_file_success', 'Total per file (success)'),
            ('total_file_cached', 'Total per file (from cache)'),
            ('libclang_parse', 'libclang TU parsing'),
            ('ast_traversal', 'AST traversal'),
            ('bulk_write', 'Bulk symbol write'),
            ('lock_wait', 'Lock wait time'),
            ('cache_load', 'Cache load'),
            ('cache_save', 'Cache save'),
        ]

        for category, label in categories:
            stats = compute_stats(self.timings.get(category, []))
            if stats['count'] > 0:
                print(f"\n{label}:")
                print(f"  Count:   {stats['count']}")
                print(f"  Total:   {stats['total']:.3f}s")
                print(f"  Average: {stats['avg']:.3f}s")
                print(f"  Min:     {stats['min']:.3f}s")
                print(f"  Max:     {stats['max']:.3f}s")

        # Compute percentage breakdown for successful files
        success_timings = self.timings.get('total_file_success', [])
        if success_timings:
            avg_total = sum(success_timings) / len(success_timings)
            avg_parse = sum(self.timings.get('libclang_parse', [])) / len(self.timings.get('libclang_parse', [])) if self.timings.get('libclang_parse') else 0
            avg_traversal = sum(self.timings.get('ast_traversal', [])) / len(self.timings.get('ast_traversal', [])) if self.timings.get('ast_traversal') else 0
            avg_bulk_write = sum(self.timings.get('bulk_write', [])) / len(self.timings.get('bulk_write', [])) if self.timings.get('bulk_write') else 0
            avg_lock_wait = sum(self.timings.get('lock_wait', [])) / len(self.timings.get('lock_wait', [])) if self.timings.get('lock_wait') else 0

            print(f"\nPercentage breakdown (for successfully parsed files):")
            print(f"  libclang parsing: {(avg_parse/avg_total*100):.1f}%")
            print(f"  AST traversal:    {(avg_traversal/avg_total*100):.1f}%")
            print(f"  Bulk write:       {(avg_bulk_write/avg_total*100):.1f}%")
            print(f"  Lock waiting:     {(avg_lock_wait/avg_total*100):.1f}%")
            print(f"  Other (cache,etc):{((avg_total-avg_parse-avg_traversal-avg_bulk_write)/avg_total*100):.1f}%")

        print("\n" + "="*80)


def main():
    if len(sys.argv) > 1:
        project_root = sys.argv[1]
    else:
        project_root = "."

    print(f"Profiling analysis for project: {project_root}")
    print(f"Workers: {os.cpu_count()}")

    analyzer = ProfiledAnalyzer(project_root)

    # Run analysis
    start = time.time()
    file_count = analyzer.index_project(force=True, include_dependencies=False)
    elapsed = time.time() - start

    print(f"\nIndexed {file_count} files in {elapsed:.2f}s")
    if file_count > 0:
        print(f"Average: {elapsed/file_count:.3f}s per file")
    else:
        print("No files were successfully indexed")

    # Print detailed timing report
    analyzer.print_timing_report()

    # Save detailed timing data to JSON
    timing_file = Path(project_root) / ".clang_index" / "profiling.json"
    timing_file.parent.mkdir(parents=True, exist_ok=True)

    with open(timing_file, 'w') as f:
        json.dump({
            category: {
                "values": values,
                "count": len(values),
                "total": sum(values),
                "avg": sum(values) / len(values) if values else 0,
                "min": min(values) if values else 0,
                "max": max(values) if values else 0
            }
            for category, values in analyzer.timings.items()
        }, f, indent=2)

    print(f"\nDetailed timing data saved to: {timing_file}")


if __name__ == "__main__":
    main()
