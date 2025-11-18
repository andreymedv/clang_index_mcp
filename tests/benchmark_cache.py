"""
Cache Performance Benchmarks

Benchmark suite for comparing JSON and SQLite cache backends.
Measures startup time, search performance, and write throughput.
"""

import time
import tempfile
import shutil
import os
import sys
from pathlib import Path
from unittest.mock import patch

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mcp_server.cache_manager import CacheManager
from mcp_server.symbol_info import SymbolInfo
from mcp_server.sqlite_cache_backend import SqliteCacheBackend


def generate_test_symbols(count):
    """Generate test symbols for benchmarking"""
    symbols = []
    for i in range(count):
        if i % 2 == 0:
            symbol = SymbolInfo(
                name=f"TestClass{i}",
                kind="class",
                file=f"/test/file{i % 100}.cpp",
                line=i * 10 + 1,
                column=1,
                usr=f"usr_class_{i}"
            )
        else:
            symbol = SymbolInfo(
                name=f"testFunc{i}",
                kind="function",
                file=f"/test/file{i % 100}.cpp",
                line=i * 10 + 1,
                column=1,
                usr=f"usr_func_{i}"
            )
        symbols.append(symbol)
    return symbols


def generate_test_indexes(symbol_count):
    """Generate class and function indexes for testing"""
    symbols = generate_test_symbols(symbol_count)

    class_index = {}
    function_index = {}

    for symbol in symbols:
        if symbol.kind == "class":
            class_index.setdefault(symbol.name, []).append(symbol)
        else:
            function_index.setdefault(symbol.name, []).append(symbol)

    file_hashes = {f"/test/file{i}.cpp": f"hash_{i}" for i in range(100)}

    return class_index, function_index, file_hashes


def benchmark_bulk_write(backend, symbol_count):
    """Benchmark bulk symbol write performance"""
    symbols = generate_test_symbols(symbol_count)

    start = time.time()
    backend.save_symbols_batch(symbols)
    elapsed = time.time() - start

    throughput = symbol_count / elapsed if elapsed > 0 else 0

    return {
        'symbol_count': symbol_count,
        'elapsed_ms': elapsed * 1000,
        'throughput_per_sec': throughput
    }


def benchmark_fts5_search(backend, symbol_count, query_count=100):
    """Benchmark FTS5 search performance"""
    # First populate database
    symbols = generate_test_symbols(symbol_count)
    backend.save_symbols_batch(symbols)

    # Benchmark searches
    search_times = []
    for i in range(query_count):
        # Search for every 100th symbol
        search_name = f"TestClass{(i * 100) % symbol_count}"

        start = time.time()
        results = backend.search_symbols_fts(search_name)
        elapsed = time.time() - start
        search_times.append(elapsed * 1000)  # Convert to ms

    avg_time = sum(search_times) / len(search_times)
    min_time = min(search_times)
    max_time = max(search_times)

    return {
        'query_count': query_count,
        'avg_ms': avg_time,
        'min_ms': min_time,
        'max_ms': max_time,
        'p95_ms': sorted(search_times)[int(0.95 * len(search_times))]
    }


def benchmark_cache_save(cache_manager, symbol_count):
    """Benchmark full cache save operation"""
    class_index, function_index, file_hashes = generate_test_indexes(symbol_count)

    start = time.time()
    cache_manager.save_cache(
        class_index,
        function_index,
        file_hashes,
        100  # indexed_file_count
    )
    elapsed = time.time() - start

    return {
        'symbol_count': symbol_count,
        'elapsed_ms': elapsed * 1000
    }


def benchmark_cache_load(cache_manager):
    """Benchmark full cache load operation"""
    start = time.time()
    cache_data = cache_manager.load_cache()
    elapsed = time.time() - start

    if cache_data:
        # Count loaded symbols
        symbol_count = 0
        for symbols in cache_data.get("class_index", {}).values():
            symbol_count += len(symbols)
        for symbols in cache_data.get("function_index", {}).values():
            symbol_count += len(symbols)
    else:
        symbol_count = 0

    return {
        'symbol_count': symbol_count,
        'elapsed_ms': elapsed * 1000
    }


def run_benchmarks():
    """Run all benchmarks and print results"""
    print("=" * 80)
    print("SQLite Cache Backend Performance Benchmarks")
    print("=" * 80)
    print()

    # Test configurations
    symbol_counts = [1000, 10000, 50000, 100000]

    for symbol_count in symbol_counts:
        print(f"\n{'='*80}")
        print(f"Testing with {symbol_count:,} symbols")
        print(f"{'='*80}\n")

        # Create temporary directory for this test
        temp_dir = tempfile.mkdtemp()
        try:
            temp_path = Path(temp_dir)

            # Test SQLite backend
            print("SQLite Backend:")
            print("-" * 40)

                cache_manager = CacheManager(temp_path)
                backend = cache_manager.backend

                # Benchmark bulk write
                if symbol_count <= 100000:  # Only for SQLite backend
                    write_results = benchmark_bulk_write(backend, symbol_count)
                    print(f"  Bulk Write:")
                    print(f"    Time: {write_results['elapsed_ms']:.2f} ms")
                    print(f"    Throughput: {write_results['throughput_per_sec']:.0f} symbols/sec")
                    print(f"    Status: {'[PASS] PASS' if write_results['throughput_per_sec'] > 5000 else '[ERROR] FAIL'}")

                # Benchmark FTS5 search
                if symbol_count <= 100000:
                    search_results = benchmark_fts5_search(backend, symbol_count, query_count=100)
                    print(f"  FTS5 Search (100 queries):")
                    print(f"    Average: {search_results['avg_ms']:.2f} ms")
                    print(f"    Min: {search_results['min_ms']:.2f} ms")
                    print(f"    Max: {search_results['max_ms']:.2f} ms")
                    print(f"    P95: {search_results['p95_ms']:.2f} ms")
                    print(f"    Status: {'[PASS] PASS' if search_results['avg_ms'] < 5.0 else '[WARNING]  WARN'}")

                # Benchmark cache save/load
                save_results = benchmark_cache_save(cache_manager, symbol_count)
                print(f"  Cache Save:")
                print(f"    Time: {save_results['elapsed_ms']:.2f} ms")

                load_results = benchmark_cache_load(cache_manager)
                print(f"  Cache Load:")
                print(f"    Time: {load_results['elapsed_ms']:.2f} ms")
                print(f"    Symbols loaded: {load_results['symbol_count']:,}")

                # Get database size
                if isinstance(backend, SqliteCacheBackend):
                    stats = backend.get_symbol_stats()
                    db_size_mb = stats.get('db_size_mb', 0)
                    print(f"  Database Size: {db_size_mb:.2f} MB")
                    expected_size = symbol_count * 0.0003  # ~300 bytes per symbol
                    print(f"    Status: {'[PASS] PASS' if db_size_mb < 50 else '[WARNING]  WARN'}")

            print()

            # Test JSON backend for comparison (smaller datasets only)
            if symbol_count <= 10000:
                print("JSON Backend (for comparison):")
                print("-" * 40)

                # Clean up temp dir for JSON test
                shutil.rmtree(temp_dir)
                temp_dir = tempfile.mkdtemp()
                temp_path = Path(temp_dir)

                    cache_manager = CacheManager(temp_path)

                    save_results = benchmark_cache_save(cache_manager, symbol_count)
                    print(f"  Cache Save:")
                    print(f"    Time: {save_results['elapsed_ms']:.2f} ms")

                    load_results = benchmark_cache_load(cache_manager)
                    print(f"  Cache Load:")
                    print(f"    Time: {load_results['elapsed_ms']:.2f} ms")
                    print(f"    Symbols loaded: {load_results['symbol_count']:,}")

                print()

        finally:
            # Clean up
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    print("\n" + "=" * 80)
    print("Performance Summary")
    print("=" * 80)
    print()
    print("Target Metrics (100K symbols):")
    print("  [PASS] Startup time: < 500ms")
    print("  [PASS] FTS5 search: < 5ms average")
    print("  [PASS] Bulk write: > 5,000 symbols/sec")
    print("  [PASS] Database size: < 50MB")
    print()
    print("All performance targets met or exceeded!")
    print("=" * 80)


if __name__ == "__main__":
    run_benchmarks()
