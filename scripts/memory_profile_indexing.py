#!/usr/bin/env python3
"""
Memory profiling script for MCP server indexing.

This script monitors memory usage during indexing and provides detailed
analysis of memory consumption patterns and hotspots.
"""

import os
import sys
import time
import gc
import tracemalloc
import resource
import threading
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.cpp_analyzer import CppAnalyzer


class MemoryMonitor:
    """Monitor memory usage during indexing."""

    def __init__(self, sample_interval: float = 5.0):
        self.sample_interval = sample_interval
        self.samples = []
        self.running = False
        self.thread = None
        self.start_time = None

    def _get_memory_info(self):
        """Get current memory usage info."""
        # Get process memory from /proc (Linux)
        try:
            with open("/proc/self/status", "r") as f:
                status = f.read()

            vm_rss = 0
            vm_size = 0
            vm_data = 0
            vm_peak = 0

            for line in status.split("\n"):
                if line.startswith("VmRSS:"):
                    vm_rss = int(line.split()[1]) * 1024  # Convert KB to bytes
                elif line.startswith("VmSize:"):
                    vm_size = int(line.split()[1]) * 1024
                elif line.startswith("VmData:"):
                    vm_data = int(line.split()[1]) * 1024
                elif line.startswith("VmPeak:"):
                    vm_peak = int(line.split()[1]) * 1024

        except Exception:
            # Fallback to resource module
            usage = resource.getrusage(resource.RUSAGE_SELF)
            vm_rss = usage.ru_maxrss * 1024  # On Linux, ru_maxrss is in KB
            vm_size = 0
            vm_data = 0
            vm_peak = vm_rss

        return {
            "rss_mb": vm_rss / (1024 * 1024),
            "vsize_mb": vm_size / (1024 * 1024),
            "data_mb": vm_data / (1024 * 1024),
            "peak_mb": vm_peak / (1024 * 1024),
        }

    def _sample_loop(self):
        """Background thread to sample memory."""
        while self.running:
            elapsed = time.time() - self.start_time
            mem_info = self._get_memory_info()

            sample = {"elapsed_sec": elapsed, "timestamp": datetime.now().isoformat(), **mem_info}
            self.samples.append(sample)

            # Print progress
            print(
                f"[{elapsed:.0f}s] RSS: {mem_info['rss_mb']:.1f} MB, "
                f"Peak: {mem_info['peak_mb']:.1f} MB"
            )

            time.sleep(self.sample_interval)

    def start(self):
        """Start memory monitoring."""
        self.running = True
        self.start_time = time.time()
        self.thread = threading.Thread(target=self._sample_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop memory monitoring."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)

    def get_summary(self):
        """Get summary statistics."""
        if not self.samples:
            return {}

        rss_values = [s["rss_mb"] for s in self.samples]

        return {
            "total_samples": len(self.samples),
            "duration_sec": self.samples[-1]["elapsed_sec"] if self.samples else 0,
            "rss_min_mb": min(rss_values),
            "rss_max_mb": max(rss_values),
            "rss_final_mb": rss_values[-1] if rss_values else 0,
            "peak_mb": max(s["peak_mb"] for s in self.samples),
        }


def analyze_object_sizes(analyzer):
    """Analyze sizes of major data structures in the analyzer."""
    print("\n" + "=" * 60)
    print("ANALYZING OBJECT SIZES")
    print("=" * 60)

    sizes = {}

    # Analyze class_index
    class_index_size = 0
    class_count = 0
    for name, symbols in analyzer.class_index.items():
        class_count += len(symbols)
        class_index_size += sys.getsizeof(name)
        class_index_size += sys.getsizeof(symbols)
        for sym in symbols:
            class_index_size += sys.getsizeof(sym)
            # Estimate size of symbol attributes
            class_index_size += sys.getsizeof(sym.name) if hasattr(sym, "name") else 0
            class_index_size += sys.getsizeof(sym.file) if hasattr(sym, "file") else 0
            class_index_size += sys.getsizeof(sym.signature) if hasattr(sym, "signature") else 0
            class_index_size += sys.getsizeof(sym.usr) if hasattr(sym, "usr") else 0
            if hasattr(sym, "base_classes") and sym.base_classes:
                class_index_size += sys.getsizeof(sym.base_classes)
                for bc in sym.base_classes:
                    class_index_size += sys.getsizeof(bc)

    sizes["class_index"] = {
        "size_mb": class_index_size / (1024 * 1024),
        "num_entries": len(analyzer.class_index),
        "num_symbols": class_count,
    }

    # Analyze function_index
    func_index_size = 0
    func_count = 0
    for name, symbols in analyzer.function_index.items():
        func_count += len(symbols)
        func_index_size += sys.getsizeof(name)
        func_index_size += sys.getsizeof(symbols)
        for sym in symbols:
            func_index_size += sys.getsizeof(sym)
            func_index_size += sys.getsizeof(sym.name) if hasattr(sym, "name") else 0
            func_index_size += sys.getsizeof(sym.file) if hasattr(sym, "file") else 0
            func_index_size += sys.getsizeof(sym.signature) if hasattr(sym, "signature") else 0
            func_index_size += sys.getsizeof(sym.usr) if hasattr(sym, "usr") else 0

    sizes["function_index"] = {
        "size_mb": func_index_size / (1024 * 1024),
        "num_entries": len(analyzer.function_index),
        "num_symbols": func_count,
    }

    # Analyze file_index
    file_index_size = 0
    file_symbol_count = 0
    for file_path, symbols in analyzer.file_index.items():
        file_symbol_count += len(symbols)
        file_index_size += sys.getsizeof(file_path)
        file_index_size += sys.getsizeof(symbols)
        for sym in symbols:
            file_index_size += sys.getsizeof(sym)

    sizes["file_index"] = {
        "size_mb": file_index_size / (1024 * 1024),
        "num_files": len(analyzer.file_index),
        "num_symbols": file_symbol_count,
    }

    # Analyze usr_index
    usr_index_size = 0
    for usr, sym in analyzer.usr_index.items():
        usr_index_size += sys.getsizeof(usr)
        usr_index_size += sys.getsizeof(sym)

    sizes["usr_index"] = {
        "size_mb": usr_index_size / (1024 * 1024),
        "num_entries": len(analyzer.usr_index),
    }

    # Analyze call graph
    call_graph_size = 0
    if hasattr(analyzer, "call_graph_analyzer"):
        cga = analyzer.call_graph_analyzer

        # call_graph dict
        for caller, callees in cga.call_graph.items():
            call_graph_size += sys.getsizeof(caller)
            call_graph_size += sys.getsizeof(callees)
            for callee in callees:
                call_graph_size += sys.getsizeof(callee)

        # reverse_call_graph dict
        for callee, callers in cga.reverse_call_graph.items():
            call_graph_size += sys.getsizeof(callee)
            call_graph_size += sys.getsizeof(callers)
            for caller in callers:
                call_graph_size += sys.getsizeof(caller)

        # call_sites (current session only)
        call_sites_size = sys.getsizeof(cga.call_sites)
        for cs in cga.call_sites:
            call_sites_size += sys.getsizeof(cs)
            call_sites_size += sys.getsizeof(cs.caller_usr)
            call_sites_size += sys.getsizeof(cs.callee_usr)
            call_sites_size += sys.getsizeof(cs.file)

        sizes["call_graph"] = {
            "size_mb": call_graph_size / (1024 * 1024),
            "num_callers": len(cga.call_graph),
            "num_callees": len(cga.reverse_call_graph),
        }

        sizes["call_sites_memory"] = {
            "size_mb": call_sites_size / (1024 * 1024),
            "num_call_sites": len(cga.call_sites),
        }

    # Analyze file_hashes
    file_hashes_size = 0
    for path, hash_val in analyzer.file_hashes.items():
        file_hashes_size += sys.getsizeof(path)
        file_hashes_size += sys.getsizeof(hash_val)

    sizes["file_hashes"] = {
        "size_mb": file_hashes_size / (1024 * 1024),
        "num_files": len(analyzer.file_hashes),
    }

    # Print results
    total_estimated = 0
    for name, info in sizes.items():
        size_mb = info["size_mb"]
        total_estimated += size_mb
        print(f"\n{name}:")
        for key, value in info.items():
            if key == "size_mb":
                print(f"  Size: {value:.2f} MB")
            else:
                print(f"  {key}: {value:,}")

    print(f"\n{'='*60}")
    print(f"TOTAL ESTIMATED IN-MEMORY SIZE: {total_estimated:.2f} MB")
    print(f"{'='*60}")

    return sizes


def run_tracemalloc_analysis():
    """Run tracemalloc to find top allocations."""
    print("\n" + "=" * 60)
    print("TRACEMALLOC TOP ALLOCATIONS")
    print("=" * 60)

    snapshot = tracemalloc.take_snapshot()

    # Group by filename
    stats = snapshot.statistics("filename")
    print("\nTop 20 files by memory allocation:")
    for i, stat in enumerate(stats[:20], 1):
        print(f"{i:2}. {stat.size / (1024*1024):.2f} MB - {stat.traceback}")

    # Group by lineno for our code
    print("\nTop allocations in mcp_server/:")
    stats = snapshot.statistics("lineno")
    mcp_stats = [s for s in stats if "mcp_server" in str(s.traceback)]
    for i, stat in enumerate(mcp_stats[:30], 1):
        print(f"{i:2}. {stat.size / (1024*1024):.2f} MB - {stat.traceback}")

    return snapshot


def main():
    if len(sys.argv) < 2:
        print("Usage: python memory_profile_indexing.py /path/to/project")
        print("Example: python memory_profile_indexing.py /home/user/my-cpp-project")
        sys.exit(1)

    project_path = sys.argv[1]

    if not os.path.isdir(project_path):
        print(f"Error: Project path does not exist: {project_path}")
        sys.exit(1)

    print("=" * 60)
    print("MCP SERVER MEMORY PROFILING")
    print("=" * 60)
    print(f"Project: {project_path}")
    print(f"Start time: {datetime.now().isoformat()}")
    print("=" * 60)

    # Start tracemalloc
    tracemalloc.start(25)  # Keep 25 frames for tracebacks

    # Start memory monitor
    monitor = MemoryMonitor(sample_interval=10.0)
    monitor.start()

    # Get initial memory
    initial_mem = monitor._get_memory_info()
    print(f"\nInitial memory: {initial_mem['rss_mb']:.1f} MB")

    try:
        # Create analyzer and start indexing
        print("\nCreating CppAnalyzer...")
        analyzer = CppAnalyzer(project_path)

        post_init_mem = monitor._get_memory_info()
        print(f"After CppAnalyzer init: {post_init_mem['rss_mb']:.1f} MB")

        print("\nStarting project indexing...")
        print("(This may take over an hour for large projects)")
        print("-" * 60)

        start_time = time.time()
        analyzer.index_project()
        elapsed = time.time() - start_time

        print("-" * 60)
        print(f"\nIndexing completed in {elapsed/60:.1f} minutes")

        # Get final memory
        final_mem = monitor._get_memory_info()
        print(f"Final memory: {final_mem['rss_mb']:.1f} MB")
        print(f"Memory growth: {final_mem['rss_mb'] - initial_mem['rss_mb']:.1f} MB")

        # Stop monitor
        monitor.stop()

        # Run detailed analysis
        sizes = analyze_object_sizes(analyzer)

        # Run tracemalloc analysis
        snapshot = run_tracemalloc_analysis()

        # Print summary
        summary = monitor.get_summary()
        print("\n" + "=" * 60)
        print("MEMORY MONITORING SUMMARY")
        print("=" * 60)
        print(f"Duration: {summary['duration_sec']/60:.1f} minutes")
        print(f"RSS Min: {summary['rss_min_mb']:.1f} MB")
        print(f"RSS Max: {summary['rss_max_mb']:.1f} MB")
        print(f"RSS Final: {summary['rss_final_mb']:.1f} MB")
        print(f"Peak Memory: {summary['peak_mb']:.1f} MB")

        # Save results to file
        results = {
            "project": project_path,
            "timestamp": datetime.now().isoformat(),
            "duration_minutes": elapsed / 60,
            "memory_summary": summary,
            "object_sizes": sizes,
            "samples": monitor.samples,
        }

        results_file = (
            Path(__file__).parent.parent / ".test-results" / "memory_profile_results.json"
        )
        results_file.parent.mkdir(exist_ok=True)
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nResults saved to: {results_file}")

        # Force garbage collection and measure again
        print("\n" + "=" * 60)
        print("AFTER GARBAGE COLLECTION")
        print("=" * 60)
        gc.collect()
        post_gc_mem = monitor._get_memory_info()
        print(f"After GC: {post_gc_mem['rss_mb']:.1f} MB")
        print(f"Freed by GC: {final_mem['rss_mb'] - post_gc_mem['rss_mb']:.1f} MB")

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        monitor.stop()

        # Still try to get partial results
        summary = monitor.get_summary()
        print(f"\nPartial results - Peak memory: {summary.get('peak_mb', 'N/A')} MB")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        monitor.stop()
        raise


if __name__ == "__main__":
    main()
