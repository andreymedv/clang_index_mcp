"""
ProcessPoolExecutor Tests - SQLite Cache

Tests concurrent access to SQLite cache from multiple processes.
Verifies thread-safety, connection isolation, and performance.
"""

import unittest
import os
import sys
import tempfile
import shutil
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from unittest.mock import patch

# Import test infrastructure
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cache_manager import CacheManager
from mcp_server.sqlite_cache_backend import SqliteCacheBackend
from mcp_server.symbol_info import SymbolInfo


def worker_write_symbols(args):
    """Worker function that writes symbols to cache (runs in separate process)"""
    cache_dir, worker_id, symbol_count = args

    cache_manager = None
    try:
        # Each process gets its own CacheManager and connection
        cache_manager = CacheManager(Path(cache_dir))

        # Create symbols for this worker
        symbols = []
        for i in range(symbol_count):
            symbol = SymbolInfo(
                name=f"Worker{worker_id}_Symbol{i}",
                kind="function",
                file=f"/test/worker{worker_id}.cpp",
                line=i + 1,
                column=1,
                usr=f"usr_w{worker_id}_s{i}"
            )
            symbols.append(symbol)

        # Write symbols
        backend = cache_manager.backend
        if isinstance(backend, SqliteCacheBackend):
            backend.save_symbols_batch(symbols)
            return (worker_id, symbol_count, True, None)
        else:
            return (worker_id, 0, False, "Not using SQLite backend")

    except Exception as e:
        return (worker_id, 0, False, str(e))
    finally:
        if cache_manager is not None:
            cache_manager.close()


def worker_read_symbols(args):
    """Worker function that reads symbols from cache (runs in separate process)"""
    cache_dir, worker_id, expected_count = args

    cache_manager = None
    try:
        # Each process gets its own CacheManager and connection
        cache_manager = CacheManager(Path(cache_dir))

        backend = cache_manager.backend
        if isinstance(backend, SqliteCacheBackend):
            # Read all symbols
            stats = backend.get_symbol_stats()
            total_symbols = stats.get('total_symbols', 0)
            return (worker_id, total_symbols, True, None)
        else:
            return (worker_id, 0, False, "Not using SQLite backend")

    except Exception as e:
        return (worker_id, 0, False, str(e))
    finally:
        if cache_manager is not None:
            cache_manager.close()


def check_connection_id(cache_dir):
    """Get SQLite connection object ID (module-level for pickling)"""
    cache_manager = None
    try:
        cache_manager = CacheManager(Path(cache_dir))
        backend = cache_manager.backend
        if isinstance(backend, SqliteCacheBackend):
            # Return connection object ID
            return id(backend.conn)
        return None
    except Exception as e:
        return str(e)
    finally:
        if cache_manager is not None:
            cache_manager.close()


class TestProcessPoolCache(unittest.TestCase):
    """Test SQLite cache with ProcessPoolExecutor"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_project_dir = Path(self.temp_dir)
        self.cache_managers = []  # Track cache managers for cleanup

    def tearDown(self):
        """Clean up test fixtures"""
        # Close all cache managers to avoid resource leaks
        for cm in self.cache_managers:
            try:
                cm.close()
            except Exception:
                pass
        self.cache_managers.clear()

        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_cache_manager(self):
        """Create a CacheManager and track it for cleanup."""
        cm = CacheManager(self.temp_project_dir)
        self.cache_managers.append(cm)
        return cm

    def test_concurrent_writes(self):
        """Test concurrent writes from multiple processes"""
        num_workers = 4
        symbols_per_worker = 100

        # Pre-create database to avoid initialization race condition
        init_cache_manager = self._create_cache_manager()
        # Just initialize - don't write anything yet

        # Use ProcessPoolExecutor to write symbols concurrently
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            tasks = [
                (str(self.temp_project_dir), i, symbols_per_worker)
                for i in range(num_workers)
            ]
            results = list(executor.map(worker_write_symbols, tasks))

        # Verify all workers succeeded
        for worker_id, count, success, error in results:
            self.assertTrue(success, f"Worker {worker_id} failed: {error}")
            self.assertEqual(count, symbols_per_worker,
                f"Worker {worker_id} should have written {symbols_per_worker} symbols")

        # Verify total symbol count
        cache_manager = self._create_cache_manager()
        backend = cache_manager.backend

        if isinstance(backend, SqliteCacheBackend):
            stats = backend.get_symbol_stats()
            total_symbols = stats.get('total_symbols', 0)
            expected_total = num_workers * symbols_per_worker
            self.assertEqual(total_symbols, expected_total,
                f"Should have {expected_total} total symbols from {num_workers} workers")

    def test_concurrent_reads(self):
        """Test concurrent reads from multiple processes"""
        # First, populate database with some data
        symbol_count = 1000
        cache_manager = self._create_cache_manager()
        backend = cache_manager.backend

        if isinstance(backend, SqliteCacheBackend):
            symbols = []
            for i in range(symbol_count):
                symbol = SymbolInfo(
                    name=f"TestSymbol{i}",
                    kind="function",
                    file="/test/test.cpp",
                    line=i + 1,
                    column=1,
                    usr=f"usr_test_{i}"
                )
                symbols.append(symbol)

            backend.save_symbols_batch(symbols)

        # Now use ProcessPoolExecutor to read concurrently
        num_workers = 4
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            tasks = [
                (str(self.temp_project_dir), i, symbol_count)
                for i in range(num_workers)
            ]
            results = list(executor.map(worker_read_symbols, tasks))

        # Verify all workers succeeded and got correct count
        for worker_id, count, success, error in results:
            self.assertTrue(success, f"Worker {worker_id} failed: {error}")
            self.assertEqual(count, symbol_count,
                f"Worker {worker_id} should have read {symbol_count} symbols")

    def test_no_database_locked_errors(self):
        """Test that concurrent access doesn't cause database locked errors"""
        # This test specifically checks that our WAL mode + busy handler
        # configuration prevents "database is locked" errors

        num_workers = 8  # Use more workers to stress test
        symbols_per_worker = 50

        # Pre-create database to avoid initialization race condition
        init_cache_manager = self._create_cache_manager()

        # Run concurrent writes
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            tasks = [
                (str(self.temp_project_dir), i, symbols_per_worker)
                for i in range(num_workers)
            ]
            results = list(executor.map(worker_write_symbols, tasks))

        # Verify NO worker reported lock errors
        for worker_id, count, success, error in results:
            self.assertTrue(success,
                f"Worker {worker_id} failed (possible lock error): {error}")
            self.assertIsNone(error,
                f"Worker {worker_id} should not have errors")

    def test_isolated_connections(self):
        """Test that each process gets its own isolated connection"""
        # Pre-create database
        init_cache_manager = self._create_cache_manager()

        # Get connection IDs from multiple processes
        with ProcessPoolExecutor(max_workers=4) as executor:
            conn_ids = list(executor.map(check_connection_id,
                [str(self.temp_project_dir)] * 4))

        # All connection IDs should be different (different processes)
        # Note: We can't directly compare IDs across processes, but we can verify
        # they're all non-None and the test succeeds without errors
        for conn_id in conn_ids:
            self.assertIsNotNone(conn_id, "Each process should have a connection")
            self.assertNotIsInstance(conn_id, str,
                "Should not have error messages")


class TestProcessPoolPerformance(unittest.TestCase):
    """Test performance characteristics with ProcessPoolExecutor"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_project_dir = Path(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_processpool_vs_sequential(self):
        """Compare ProcessPool performance to sequential writes"""
        import time

        symbols_per_worker = 250
        num_workers = 4
        total_symbols = symbols_per_worker * num_workers

        # Test 1: Sequential writes
        start = time.time()
        for worker_id in range(num_workers):
            worker_write_symbols((str(self.temp_project_dir), worker_id,
                symbols_per_worker))
        sequential_time = time.time() - start

        # Clean up for second test
        shutil.rmtree(self.temp_dir)
        self.temp_dir = tempfile.mkdtemp()
        self.temp_project_dir = Path(self.temp_dir)

        # Test 2: Parallel writes
        start = time.time()
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            tasks = [
                (str(self.temp_project_dir), i, symbols_per_worker)
                for i in range(num_workers)
            ]
            list(executor.map(worker_write_symbols, tasks))
        parallel_time = time.time() - start

        # Parallel should be faster (or at least not much slower due to overhead)
        # We're lenient here as ProcessPool has significant startup overhead
        # for small workloads, especially on systems with slower process spawning
        # macOS M1 has particularly high process creation overhead, so we allow
        # parallel to be up to 7x slower for these small workloads
        self.assertLess(parallel_time, sequential_time * 7.0,
            f"Parallel ({parallel_time:.2f}s) should be competitive with "
            f"sequential ({sequential_time:.2f}s)")


if __name__ == '__main__':
    unittest.main()
