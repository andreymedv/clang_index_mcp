#!/usr/bin/env python3
"""
Diagnose if Python's Global Interpreter Lock (GIL) is limiting parallelism.

This script compares ThreadPoolExecutor vs ProcessPoolExecutor performance
to determine if the GIL is a bottleneck for C++ analysis.

The GIL allows only one Python thread to execute at a time, even on multi-core systems.
While libclang (C library) releases the GIL during parsing, any Python code still
requires the GIL, which can limit parallelism.

Usage:
    python scripts/diagnose_gil.py [project_root]
"""

import sys
import os
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_file_worker(file_path: str):
    """Worker function to parse a single file (for ProcessPoolExecutor)."""
    from mcp_server.cpp_analyzer import CppAnalyzer
    import tempfile

    # Create a minimal analyzer just for this file
    # Use a unique temp directory for cache to avoid conflicts
    with tempfile.TemporaryDirectory() as tmpdir:
        analyzer = CppAnalyzer(tmpdir)
        start = time.time()
        success, cached = analyzer.index_file(file_path, force=True)
        elapsed = time.time() - start
        return (file_path, success, elapsed)


def test_with_threads(files, max_workers):
    """Test parsing with ThreadPoolExecutor."""
    print(f"\nTesting with ThreadPoolExecutor ({max_workers} workers)...")

    from mcp_server.cpp_analyzer import CppAnalyzer
    analyzer = CppAnalyzer(".")

    start = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(analyzer.index_file, f, True) for f in files]
        results = [f.result() for f in futures]

    elapsed = time.time() - start
    successful = sum(1 for success, _ in results if success)

    print(f"  Completed: {successful}/{len(files)} files")
    print(f"  Time: {elapsed:.2f}s")
    print(f"  Rate: {len(files)/elapsed:.2f} files/sec")

    return elapsed


def test_with_processes(files, max_workers):
    """Test parsing with ProcessPoolExecutor."""
    print(f"\nTesting with ProcessPoolExecutor ({max_workers} workers)...")

    start = time.time()

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(parse_file_worker, f) for f in files]
        results = [f.result() for f in futures]

    elapsed = time.time() - start
    successful = sum(1 for _, success, _ in results if success)

    print(f"  Completed: {successful}/{len(files)} files")
    print(f"  Time: {elapsed:.2f}s")
    print(f"  Rate: {len(files)/elapsed:.2f} files/sec")

    return elapsed


def main():
    if len(sys.argv) > 1:
        project_root = sys.argv[1]
    else:
        project_root = "."

    print("="*80)
    print("GIL BOTTLENECK DIAGNOSTIC")
    print("="*80)

    # Find C++ files
    from mcp_server.file_scanner import FileScanner
    scanner = FileScanner(project_root)
    all_files = scanner.find_cpp_files()

    if not all_files:
        print("No C++ files found!")
        return

    # Take a sample for testing (to keep it quick)
    sample_size = min(20, len(all_files))
    test_files = all_files[:sample_size]

    print(f"\nProject: {project_root}")
    print(f"Testing with {sample_size} files (sample from {len(all_files)} total)")
    print(f"CPU count: {os.cpu_count()}")

    # Test with different worker counts
    for worker_count in [1, 2, 4, os.cpu_count()]:
        if worker_count > os.cpu_count():
            continue

        print(f"\n{'='*80}")
        print(f"Testing with {worker_count} workers:")
        print('='*80)

        thread_time = test_with_threads(test_files, worker_count)
        process_time = test_with_processes(test_files, worker_count)

        speedup = thread_time / process_time if process_time > 0 else 0
        print(f"\n  ProcessPool speedup: {speedup:.2f}x")

        if speedup > 1.5:
            print("  ⚠️  WARNING: ProcessPool is significantly faster!")
            print("  ⚠️  This indicates GIL contention is limiting ThreadPool performance!")

    print("\n" + "="*80)
    print("ANALYSIS:")
    print("="*80)
    print("""
If ProcessPoolExecutor is significantly faster (1.5x+), the GIL is likely the bottleneck.
This happens because:
1. ThreadPoolExecutor uses Python threads (limited by GIL)
2. Even though libclang releases GIL during parsing, Python code still needs it
3. ProcessPoolExecutor uses separate processes (no shared GIL)

Recommendations if GIL is the bottleneck:
- Switch to ProcessPoolExecutor for parallel parsing
- Reduce worker count for ThreadPoolExecutor (less contention)
- Optimize Python code between libclang calls
    """)


if __name__ == "__main__":
    main()
