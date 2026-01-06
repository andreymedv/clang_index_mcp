#!/usr/bin/env python3
"""
Dynamic memory growth analyzer for MCP server indexing.

Takes snapshots at regular intervals to identify which data structures
accumulate memory over time during indexing.
"""

import os
import sys
import time
import gc
import tracemalloc
import threading
import json
import pickle
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def get_process_memory_mb() -> float:
    """Get current process RSS memory in MB."""
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024  # kB to MB
    except Exception:
        pass
    return 0.0


def get_object_size_recursive(obj, seen=None, max_depth=5, current_depth=0) -> int:
    """Recursively calculate object size including referenced objects."""
    if seen is None:
        seen = set()

    if current_depth > max_depth:
        return 0

    obj_id = id(obj)
    if obj_id in seen:
        return 0
    seen.add(obj_id)

    size = sys.getsizeof(obj)

    if isinstance(obj, dict):
        for k, v in obj.items():
            size += get_object_size_recursive(k, seen, max_depth, current_depth + 1)
            size += get_object_size_recursive(v, seen, max_depth, current_depth + 1)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for item in obj:
            size += get_object_size_recursive(item, seen, max_depth, current_depth + 1)
    elif hasattr(obj, "__dict__"):
        size += get_object_size_recursive(obj.__dict__, seen, max_depth, current_depth + 1)
    elif hasattr(obj, "__slots__"):
        for slot in obj.__slots__:
            if hasattr(obj, slot):
                size += get_object_size_recursive(
                    getattr(obj, slot), seen, max_depth, current_depth + 1
                )

    return size


def format_size(size_bytes: int) -> str:
    """Format size in human-readable form."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


class MemorySnapshot:
    """Captures memory state at a point in time."""

    def __init__(self, snapshot_id: int, timestamp: float, analyzer=None):
        self.snapshot_id = snapshot_id
        self.timestamp = timestamp
        self.process_rss_mb = get_process_memory_mb()
        self.tracemalloc_snapshot = tracemalloc.take_snapshot()
        self.analyzer_structures = {}
        self.structure_counts = {}

        if analyzer:
            self._analyze_structures(analyzer)

    def _analyze_structures(self, analyzer):
        """Analyze CppAnalyzer internal data structures."""
        structures = {}
        counts = {}

        # Main indexes
        if hasattr(analyzer, "class_index"):
            structures["class_index"] = get_object_size_recursive(analyzer.class_index, max_depth=3)
            counts["class_index"] = len(analyzer.class_index) if analyzer.class_index else 0

        if hasattr(analyzer, "function_index"):
            structures["function_index"] = get_object_size_recursive(
                analyzer.function_index, max_depth=3
            )
            counts["function_index"] = (
                len(analyzer.function_index) if analyzer.function_index else 0
            )

        if hasattr(analyzer, "file_index"):
            structures["file_index"] = get_object_size_recursive(analyzer.file_index, max_depth=3)
            counts["file_index"] = len(analyzer.file_index) if analyzer.file_index else 0

        if hasattr(analyzer, "usr_index"):
            structures["usr_index"] = get_object_size_recursive(analyzer.usr_index, max_depth=3)
            counts["usr_index"] = len(analyzer.usr_index) if analyzer.usr_index else 0

        # Symbol storage
        if hasattr(analyzer, "symbols"):
            structures["symbols"] = get_object_size_recursive(analyzer.symbols, max_depth=3)
            counts["symbols"] = len(analyzer.symbols) if analyzer.symbols else 0

        # Cache manager
        if hasattr(analyzer, "cache_manager") and analyzer.cache_manager:
            cm = analyzer.cache_manager
            structures["cache_manager"] = sys.getsizeof(cm)
            if hasattr(cm, "_backend") and cm._backend:
                backend = cm._backend
                structures["cache_backend"] = sys.getsizeof(backend)

        # Compile commands manager
        if hasattr(analyzer, "compile_commands_manager") and analyzer.compile_commands_manager:
            ccm = analyzer.compile_commands_manager
            structures["compile_commands_manager"] = sys.getsizeof(ccm)
            if hasattr(ccm, "file_to_command_map"):
                structures["file_to_command_map"] = get_object_size_recursive(
                    ccm.file_to_command_map, max_depth=2
                )
                counts["file_to_command_map"] = (
                    len(ccm.file_to_command_map) if ccm.file_to_command_map else 0
                )

        # Header tracker
        if hasattr(analyzer, "header_tracker") and analyzer.header_tracker:
            ht = analyzer.header_tracker
            structures["header_tracker"] = sys.getsizeof(ht)
            if hasattr(ht, "header_to_source"):
                structures["header_to_source"] = get_object_size_recursive(
                    ht.header_to_source, max_depth=2
                )
                counts["header_to_source"] = len(ht.header_to_source) if ht.header_to_source else 0
            if hasattr(ht, "source_headers"):
                structures["source_headers"] = get_object_size_recursive(
                    ht.source_headers, max_depth=2
                )
                counts["source_headers"] = len(ht.source_headers) if ht.source_headers else 0

        # Call graph analyzer
        if hasattr(analyzer, "call_graph_analyzer") and analyzer.call_graph_analyzer:
            cga = analyzer.call_graph_analyzer
            structures["call_graph_analyzer"] = sys.getsizeof(cga)
            if hasattr(cga, "callers"):
                structures["callers"] = get_object_size_recursive(cga.callers, max_depth=2)
                counts["callers"] = len(cga.callers) if cga.callers else 0
            if hasattr(cga, "callees"):
                structures["callees"] = get_object_size_recursive(cga.callees, max_depth=2)
                counts["callees"] = len(cga.callees) if cga.callees else 0

        # Dependency graph
        if hasattr(analyzer, "dependency_graph") and analyzer.dependency_graph:
            dg = analyzer.dependency_graph
            structures["dependency_graph"] = sys.getsizeof(dg)
            if hasattr(dg, "dependencies"):
                structures["dg_dependencies"] = get_object_size_recursive(
                    dg.dependencies, max_depth=2
                )
                counts["dg_dependencies"] = len(dg.dependencies) if dg.dependencies else 0
            if hasattr(dg, "dependents"):
                structures["dg_dependents"] = get_object_size_recursive(dg.dependents, max_depth=2)
                counts["dg_dependents"] = len(dg.dependents) if dg.dependents else 0

        # Error tracking
        if hasattr(analyzer, "error_tracker") and analyzer.error_tracker:
            et = analyzer.error_tracker
            structures["error_tracker"] = sys.getsizeof(et)
            if hasattr(et, "errors"):
                structures["et_errors"] = get_object_size_recursive(et.errors, max_depth=2)
                counts["et_errors"] = len(et.errors) if et.errors else 0

        # State manager
        if hasattr(analyzer, "state_manager") and analyzer.state_manager:
            sm = analyzer.state_manager
            structures["state_manager"] = sys.getsizeof(sm)

        # Incremental analyzer
        if hasattr(analyzer, "incremental_analyzer") and analyzer.incremental_analyzer:
            ia = analyzer.incremental_analyzer
            structures["incremental_analyzer"] = sys.getsizeof(ia)
            if hasattr(ia, "file_hashes"):
                structures["file_hashes"] = get_object_size_recursive(ia.file_hashes, max_depth=2)
                counts["file_hashes"] = len(ia.file_hashes) if ia.file_hashes else 0

        self.analyzer_structures = structures
        self.structure_counts = counts

    def get_top_allocations(self, limit: int = 20) -> List[tuple]:
        """Get top memory allocations from tracemalloc."""
        stats = self.tracemalloc_snapshot.statistics("lineno")
        return [(str(stat.traceback), stat.size) for stat in stats[:limit]]


class MemoryGrowthAnalyzer:
    """Analyzes memory growth patterns over time."""

    def __init__(self, snapshot_interval_sec: float = 180.0):  # 3 minutes
        self.snapshot_interval = snapshot_interval_sec
        self.snapshots: List[MemorySnapshot] = []
        self.analyzer = None
        self.running = False
        self.monitor_thread = None
        self.start_time = None
        self.output_file = None

    def start_monitoring(self, analyzer, output_file: str = None):
        """Start background memory monitoring."""
        self.analyzer = analyzer
        self.start_time = time.time()
        self.running = True
        self.output_file = output_file or f"/tmp/memory_growth_{int(time.time())}.json"

        # Start tracemalloc
        tracemalloc.start(25)

        # Take initial snapshot
        self._take_snapshot()

        # Start monitoring thread
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

        print(f"Memory monitoring started. Output: {self.output_file}")
        print(f"Snapshot interval: {self.snapshot_interval}s")

    def _monitor_loop(self):
        """Background loop taking periodic snapshots."""
        while self.running:
            time.sleep(self.snapshot_interval)
            if self.running:
                self._take_snapshot()

    def _take_snapshot(self):
        """Take a memory snapshot."""
        gc.collect()  # Force GC before snapshot
        snapshot = MemorySnapshot(
            snapshot_id=len(self.snapshots),
            timestamp=time.time() - self.start_time,
            analyzer=self.analyzer,
        )
        self.snapshots.append(snapshot)

        elapsed = snapshot.timestamp
        print(
            f"\n[SNAPSHOT {snapshot.snapshot_id}] t={elapsed:.0f}s, RSS={snapshot.process_rss_mb:.1f} MB"
        )

        # Print structure sizes
        if snapshot.analyzer_structures:
            print("  Structure sizes:")
            for name, size in sorted(snapshot.analyzer_structures.items(), key=lambda x: -x[1])[
                :10
            ]:
                count = snapshot.structure_counts.get(name, "?")
                print(f"    {name}: {format_size(size)} ({count} items)")

        # Save incremental results
        self._save_results()

    def stop_monitoring(self):
        """Stop monitoring and generate final report."""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)

        # Take final snapshot
        self._take_snapshot()

        # Generate and print analysis
        self._analyze_growth()
        self._save_results()

        tracemalloc.stop()

    def _analyze_growth(self):
        """Analyze memory growth patterns."""
        if len(self.snapshots) < 2:
            print("Not enough snapshots for growth analysis")
            return

        print("\n" + "=" * 70)
        print("MEMORY GROWTH ANALYSIS")
        print("=" * 70)

        first = self.snapshots[0]
        last = self.snapshots[-1]

        # Overall RSS growth
        rss_growth = last.process_rss_mb - first.process_rss_mb
        duration = last.timestamp - first.timestamp
        print(f"\nOverall memory growth: {rss_growth:.1f} MB over {duration:.0f}s")
        print(f"Growth rate: {rss_growth / (duration / 60):.1f} MB/minute")

        # Structure growth analysis
        print("\n" + "-" * 50)
        print("STRUCTURE GROWTH (first → last snapshot):")
        print("-" * 50)

        growth_data = []
        for name in first.analyzer_structures:
            if name in last.analyzer_structures:
                first_size = first.analyzer_structures[name]
                last_size = last.analyzer_structures[name]
                growth = last_size - first_size
                first_count = first.structure_counts.get(name, 0)
                last_count = last.structure_counts.get(name, 0)
                count_growth = (
                    last_count - first_count
                    if isinstance(first_count, int) and isinstance(last_count, int)
                    else "?"
                )
                growth_data.append(
                    (name, first_size, last_size, growth, first_count, last_count, count_growth)
                )

        # Sort by absolute growth
        growth_data.sort(key=lambda x: -abs(x[3]))

        for (
            name,
            first_size,
            last_size,
            growth,
            first_count,
            last_count,
            count_growth,
        ) in growth_data:
            if growth != 0:
                sign = "+" if growth > 0 else ""
                count_info = f"({first_count} → {last_count})" if count_growth != "?" else ""
                print(
                    f"  {name}: {format_size(first_size)} → {format_size(last_size)} ({sign}{format_size(growth)}) {count_info}"
                )

        # Identify potential memory leaks
        print("\n" + "-" * 50)
        print("POTENTIAL MEMORY ACCUMULATION ISSUES:")
        print("-" * 50)

        issues_found = False
        for (
            name,
            first_size,
            last_size,
            growth,
            first_count,
            last_count,
            count_growth,
        ) in growth_data:
            # Flag structures with significant growth
            if growth > 10 * 1024 * 1024:  # > 10 MB growth
                issues_found = True
                growth_rate = growth / (duration / 60) if duration > 0 else 0
                print(f"\n  ⚠️  {name}")
                print(f"      Growth: {format_size(growth)} ({growth_rate:.1f} MB/min)")
                if count_growth != "?" and count_growth > 0:
                    print(f"      Item count: {first_count} → {last_count} (+{count_growth})")
                    avg_item_size = growth / count_growth if count_growth > 0 else 0
                    print(f"      Avg item size: {format_size(int(avg_item_size))}")

        if not issues_found:
            print("  No significant memory accumulation detected.")

        # Compare tracemalloc snapshots
        print("\n" + "-" * 50)
        print("TOP MEMORY ALLOCATION CHANGES (tracemalloc):")
        print("-" * 50)

        try:
            diff_stats = last.tracemalloc_snapshot.compare_to(first.tracemalloc_snapshot, "lineno")
            for stat in diff_stats[:15]:
                if stat.size_diff > 1024 * 1024:  # > 1 MB
                    print(f"  {format_size(stat.size_diff):>10} | {stat.traceback}")
        except Exception as e:
            print(f"  Error comparing snapshots: {e}")

    def _save_results(self):
        """Save results to JSON file."""
        data = {
            "start_time": self.start_time,
            "snapshot_interval_sec": self.snapshot_interval,
            "snapshots": [],
        }

        for snap in self.snapshots:
            snap_data = {
                "id": snap.snapshot_id,
                "timestamp_sec": snap.timestamp,
                "process_rss_mb": snap.process_rss_mb,
                "structures": {k: v for k, v in snap.analyzer_structures.items()},
                "counts": {k: v for k, v in snap.structure_counts.items()},
            }
            data["snapshots"].append(snap_data)

        try:
            with open(self.output_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving results: {e}")

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of memory growth analysis."""
        if len(self.snapshots) < 2:
            return {"error": "Not enough snapshots"}

        first = self.snapshots[0]
        last = self.snapshots[-1]

        return {
            "duration_sec": last.timestamp,
            "rss_growth_mb": last.process_rss_mb - first.process_rss_mb,
            "snapshots_taken": len(self.snapshots),
            "output_file": self.output_file,
        }


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: python memory_growth_analyzer.py /path/to/project [snapshot_interval_minutes]"
        )
        print("Example: python memory_growth_analyzer.py /home/user/project 3")
        sys.exit(1)

    project_path = sys.argv[1]
    snapshot_interval_min = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0

    if not os.path.isdir(project_path):
        print(f"Error: Project path does not exist: {project_path}")
        sys.exit(1)

    print("=" * 70)
    print("MEMORY GROWTH ANALYZER")
    print("=" * 70)
    print(f"Project: {project_path}")
    print(f"Snapshot interval: {snapshot_interval_min} minutes")
    print(f"Start time: {datetime.now().isoformat()}")
    print("=" * 70)

    # Import analyzer
    from mcp_server.cpp_analyzer import CppAnalyzer

    # Create analyzer
    print("\nCreating CppAnalyzer...")
    analyzer = CppAnalyzer(project_path)

    # Create memory growth analyzer
    growth_analyzer = MemoryGrowthAnalyzer(snapshot_interval_sec=snapshot_interval_min * 60)

    # Start monitoring
    growth_analyzer.start_monitoring(analyzer)

    print("\nStarting project indexing...")
    print("(Memory snapshots will be taken every {:.0f} minutes)".format(snapshot_interval_min))
    print("-" * 70)

    try:
        # Run indexing
        analyzer.index_project()

        print("\n" + "-" * 70)
        print("Indexing complete!")

    except KeyboardInterrupt:
        print("\n\nIndexing interrupted by user.")
    except Exception as e:
        print(f"\nError during indexing: {e}")
        import traceback

        traceback.print_exc()
    finally:
        # Stop monitoring and generate report
        growth_analyzer.stop_monitoring()

        summary = growth_analyzer.get_summary()
        print("\n" + "=" * 70)
        print("FINAL SUMMARY")
        print("=" * 70)
        print(f"Duration: {summary.get('duration_sec', 0):.0f} seconds")
        print(f"RSS growth: {summary.get('rss_growth_mb', 0):.1f} MB")
        print(f"Snapshots taken: {summary.get('snapshots_taken', 0)}")
        print(f"Results saved to: {summary.get('output_file', 'N/A')}")


if __name__ == "__main__":
    main()
