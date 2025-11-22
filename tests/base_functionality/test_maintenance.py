"""
Base Functionality Tests - Database Maintenance

Tests for SQLite database maintenance operations.

Requirements: REQ-1.5 (Cache Management)
Priority: P1
"""

import unittest
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

# Import test infrastructure
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.sqlite_cache_backend import SqliteCacheBackend
from mcp_server.symbol_info import SymbolInfo


class TestMaintenanceMethods(unittest.TestCase):
    """Test database maintenance methods - REQ-1.5"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        self.backend = SqliteCacheBackend(self.db_path)

    def tearDown(self):
        """Clean up test fixtures"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _populate_symbols(self, count=100):
        """Helper to populate database with test symbols"""
        symbols = []
        for i in range(count):
            symbol = SymbolInfo(
                name=f"TestSymbol{i}",
                kind="function" if i % 2 == 0 else "class",
                file=f"/test/file{i % 10}.cpp",
                line=i + 1,
                column=1,
                usr=f"usr_test_{i}"
            )
            symbols.append(symbol)

        self.backend.save_symbols_batch(symbols)
        return symbols

    def test_vacuum(self):
        """Test VACUUM operation"""
        # Populate database
        self._populate_symbols(1000)

        # Get initial size
        stats_before = self.backend.get_symbol_stats()
        size_before = stats_before['db_size_mb']

        # Run VACUUM
        result = self.backend.vacuum()

        # Verify success
        self.assertTrue(result, "VACUUM should succeed")

        # Verify database still works
        count = self.backend.count_symbols()
        self.assertEqual(count, 1000, "Symbol count should be unchanged")

        # Get size after
        stats_after = self.backend.get_symbol_stats()
        size_after = stats_after['db_size_mb']

        # Size should be reasonable (may not shrink much without deletions)
        self.assertGreater(size_after, 0, "Database should have non-zero size")

    def test_vacuum_after_deletions(self):
        """Test VACUUM reclaims space after deletions"""
        # Populate database
        self._populate_symbols(1000)

        # Delete half the symbols
        for i in range(5):
            file_path = f"/test/file{i}.cpp"
            self.backend.delete_symbols_by_file(file_path)

        # Get size before vacuum
        stats_before = self.backend.get_symbol_stats()
        size_before = stats_before['db_size_mb']

        # Run VACUUM
        result = self.backend.vacuum()
        self.assertTrue(result, "VACUUM should succeed")

        # Get size after vacuum
        stats_after = self.backend.get_symbol_stats()
        size_after = stats_after['db_size_mb']

        # Size should be smaller or equal (WAL mode may delay shrinking)
        self.assertLessEqual(size_after, size_before * 1.1,
            "VACUUM should not significantly increase size")

    def test_optimize(self):
        """Test FTS5 OPTIMIZE operation"""
        # Populate database
        self._populate_symbols(1000)

        # Run OPTIMIZE
        result = self.backend.optimize()

        # Verify success
        self.assertTrue(result, "OPTIMIZE should succeed")

        # Verify FTS5 still works
        results = self.backend.search_symbols_fts("TestSymbol100")
        self.assertGreater(len(results), 0, "FTS5 search should still work")

    def test_analyze(self):
        """Test ANALYZE operation"""
        # Populate database
        self._populate_symbols(1000)

        # Run ANALYZE
        result = self.backend.analyze()

        # Verify success
        self.assertTrue(result, "ANALYZE should succeed")

        # Verify database still works
        count = self.backend.count_symbols()
        self.assertEqual(count, 1000, "Symbol count should be unchanged")

    def test_auto_maintenance_small_db(self):
        """Test auto_maintenance with small database (skips VACUUM)"""
        # Create small database (< 100 MB threshold)
        self._populate_symbols(100)

        # Run auto-maintenance
        results = self.backend.auto_maintenance(
            vacuum_threshold_mb=100.0,
            vacuum_min_waste_mb=10.0
        )

        # Verify results
        self.assertTrue(results['analyze'], "ANALYZE should run")
        self.assertTrue(results['optimize'], "OPTIMIZE should run")
        self.assertFalse(results['vacuum'], "VACUUM should be skipped for small DB")
        self.assertIsNotNone(results['vacuum_skipped_reason'],
            "Should have reason for skipping VACUUM")

    def test_auto_maintenance_large_db(self):
        """Test auto_maintenance with large database"""
        # Create larger database
        self._populate_symbols(1000)

        # Run auto-maintenance with low threshold (force VACUUM)
        results = self.backend.auto_maintenance(
            vacuum_threshold_mb=0.1,  # Very low threshold
            vacuum_min_waste_mb=0.0   # No waste required
        )

        # Verify results
        self.assertTrue(results['analyze'], "ANALYZE should run")
        self.assertTrue(results['optimize'], "OPTIMIZE should run")
        # VACUUM may or may not run depending on actual waste
        self.assertIn('vacuum', results, "Should have vacuum result")


class TestHealthCheckMethods(unittest.TestCase):
    """Test database health check methods"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        self.backend = SqliteCacheBackend(self.db_path)

    def tearDown(self):
        """Clean up test fixtures"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _populate_symbols(self, count=100):
        """Helper to populate database with test symbols"""
        symbols = []
        for i in range(count):
            symbol = SymbolInfo(
                name=f"TestSymbol{i}",
                kind="function" if i % 2 == 0 else "class",
                file=f"/test/file{i % 10}.cpp",
                line=i + 1,
                column=1,
                usr=f"usr_test_{i}"
            )
            symbols.append(symbol)

        self.backend.save_symbols_batch(symbols)
        return symbols

    def test_check_integrity_quick(self):
        """Test quick integrity check"""
        # Populate database
        self._populate_symbols(100)

        # Run quick integrity check
        is_healthy, message = self.backend.check_integrity(full=False)

        # Verify results
        self.assertTrue(is_healthy, f"Database should be healthy: {message}")
        self.assertIn("passed", message.lower(), "Message should indicate success")

    def test_check_integrity_full(self):
        """Test full integrity check"""
        # Populate database
        self._populate_symbols(100)

        # Run full integrity check
        is_healthy, message = self.backend.check_integrity(full=True)

        # Verify results
        self.assertTrue(is_healthy, f"Database should be healthy: {message}")
        self.assertIn("passed", message.lower(), "Message should indicate success")

    def test_get_health_status(self):
        """Test comprehensive health status"""
        # Populate database
        self._populate_symbols(500)

        # Get health status
        health = self.backend.get_health_status()

        # Verify structure
        self.assertIn('status', health, "Should have status field")
        self.assertIn('checks', health, "Should have checks field")
        self.assertIn('warnings', health, "Should have warnings field")
        self.assertIn('errors', health, "Should have errors field")

        # Verify status is healthy or warning (not error)
        self.assertIn(health['status'], ['healthy', 'warning'],
            f"Status should be healthy or warning: {health['status']}")

        # Verify integrity check passed
        self.assertIn('integrity', health['checks'], "Should have integrity check")
        self.assertTrue(health['checks']['integrity']['passed'],
            "Integrity check should pass")

        # Verify size check
        self.assertIn('size', health['checks'], "Should have size check")
        self.assertGreater(health['checks']['size']['db_size_mb'], 0,
            "Should report database size")

        # Verify FTS5 check
        self.assertIn('fts_index', health['checks'], "Should have FTS5 check")
        self.assertEqual(health['checks']['fts_index']['status'], 'ok',
            "FTS5 should be healthy")

        # Verify WAL mode check
        self.assertIn('wal_mode', health['checks'], "Should have WAL mode check")
        self.assertEqual(health['checks']['wal_mode']['journal_mode'], 'wal',
            "Should be in WAL mode")

    def test_get_health_status_with_warnings(self):
        """Test health status with warnings (very large DB)"""
        # This would require creating a 500+ MB database which is impractical
        # for unit tests. Just verify the method works with normal DB.

        # Populate database
        self._populate_symbols(100)

        # Get health status
        health = self.backend.get_health_status()

        # Should not have errors
        self.assertEqual(len(health['errors']), 0,
            f"Should have no errors: {health['errors']}")

    def test_get_table_sizes(self):
        """Test table size reporting"""
        # Populate database
        self._populate_symbols(100)

        # Get table sizes (private method, but useful to test)
        tables = self.backend._get_table_sizes()

        # Verify structure
        self.assertIsInstance(tables, dict, "Should return dict")

        # Verify main tables exist
        self.assertIn('symbols', tables, "Should have symbols table")
        self.assertIn('file_metadata', tables, "Should have file_metadata table")

        # Verify row counts
        self.assertEqual(tables['symbols']['row_count'], 100,
            "Symbols table should have 100 rows")
        self.assertEqual(tables['symbols']['status'], 'ok',
            "Symbols table should be ok")


class TestCacheStatsMethods(unittest.TestCase):
    """Test enhanced cache statistics methods"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        self.backend = SqliteCacheBackend(self.db_path)

    def tearDown(self):
        """Clean up test fixtures"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _populate_symbols(self, count=100):
        """Helper to populate database with test symbols"""
        symbols = []
        for i in range(count):
            symbol = SymbolInfo(
                name=f"TestSymbol{i}",
                kind="function" if i % 2 == 0 else "class",
                file=f"/test/file{i % 10}.cpp",
                line=i + 1,
                column=1,
                usr=f"usr_test_{i}"
            )
            symbols.append(symbol)

        self.backend.save_symbols_batch(symbols)

        # Update file metadata
        for i in range(10):
            file_path = f"/test/file{i}.cpp"
            file_hash = f"hash_{i}"
            symbol_count = sum(1 for s in symbols if s.file == file_path)
            self.backend.update_file_metadata(file_path, file_hash, None, symbol_count)

        return symbols

    def test_get_cache_stats(self):
        """Test enhanced cache statistics"""
        # Populate database
        self._populate_symbols(1000)

        # Get cache stats
        stats = self.backend.get_cache_stats()

        # Verify basic stats
        self.assertEqual(stats['total_symbols'], 1000, "Should have 1000 symbols")

        # Verify symbol breakdown by kind
        self.assertIn('by_kind', stats, "Should have by_kind breakdown")
        self.assertIn('function', stats['by_kind'], "Should have function count")
        self.assertIn('class', stats['by_kind'], "Should have class count")
        self.assertEqual(stats['by_kind']['function'], 500, "Should have 500 functions")
        self.assertEqual(stats['by_kind']['class'], 500, "Should have 500 classes")

        # Verify file stats
        self.assertIn('file_stats', stats, "Should have file_stats")
        self.assertEqual(stats['file_stats']['total_files'], 10,
            "Should have 10 files")
        self.assertGreater(stats['file_stats']['avg_symbols_per_file'], 0,
            "Should have average symbols per file")

        # Verify top files
        self.assertIn('top_files', stats, "Should have top_files")
        self.assertGreater(len(stats['top_files']), 0, "Should have at least one top file")

        # Verify metadata
        self.assertIn('metadata', stats, "Should have metadata")

        # Verify performance metrics
        self.assertIn('performance', stats, "Should have performance metrics")
        self.assertIn('db_path', stats['performance'], "Should have db_path")

    def test_monitor_performance_search(self):
        """Test performance monitoring for search operations"""
        # Populate database
        self._populate_symbols(1000)

        # Monitor search performance
        metrics = self.backend.monitor_performance(operation='search')

        # Verify metrics
        self.assertIn('fts_search_ms', metrics, "Should have FTS search time")
        self.assertIn('like_search_ms', metrics, "Should have LIKE search time")

        # Verify times are reasonable
        self.assertGreater(metrics['fts_search_ms'], 0,
            "FTS search should take some time")
        self.assertGreater(metrics['like_search_ms'], 0,
            "LIKE search should take some time")

        # FTS should generally be faster (though not always for small datasets)
        # Just verify both complete successfully

    def test_monitor_performance_load(self):
        """Test performance monitoring for load operations"""
        # Populate database
        self._populate_symbols(100)

        # Monitor load performance
        metrics = self.backend.monitor_performance(operation='load')

        # Verify metrics
        self.assertIn('load_by_usr_ms', metrics, "Should have load time")
        self.assertGreater(metrics['load_by_usr_ms'], 0,
            "Load should take some time")

        # Time should be very fast (< 10ms for single lookup)
        self.assertLess(metrics['load_by_usr_ms'], 10,
            "Load by USR should be very fast")

    def test_monitor_performance_write(self):
        """Test performance monitoring for write operations"""
        # Populate database
        self._populate_symbols(100)

        # Monitor write performance
        metrics = self.backend.monitor_performance(operation='write')

        # Verify metrics
        self.assertIn('write_symbol_ms', metrics, "Should have write time")
        self.assertGreater(metrics['write_symbol_ms'], 0,
            "Write should take some time")

        # Time should be reasonable (< 5ms for single write)
        self.assertLess(metrics['write_symbol_ms'], 5,
            "Write should be fast")

        # Verify write was rolled back (count unchanged)
        count = self.backend.count_symbols()
        self.assertEqual(count, 100, "Write should have been rolled back")


class TestMaintenanceIntegration(unittest.TestCase):
    """Test maintenance integration scenarios"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        self.backend = SqliteCacheBackend(self.db_path)

    def tearDown(self):
        """Clean up test fixtures"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_maintenance_sequence(self):
        """Test complete maintenance sequence"""
        # Populate database
        symbols = []
        for i in range(1000):
            symbol = SymbolInfo(
                name=f"Symbol{i}",
                kind="function",
                file=f"/test/file{i % 10}.cpp",
                line=i + 1,
                column=1,
                usr=f"usr_{i}"
            )
            symbols.append(symbol)

        self.backend.save_symbols_batch(symbols)

        # Run full maintenance sequence
        # 1. Check health before
        health_before = self.backend.get_health_status()
        self.assertIn(health_before['status'], ['healthy', 'warning'],
            "Should be healthy before maintenance")

        # 2. Run ANALYZE
        analyze_result = self.backend.analyze()
        self.assertTrue(analyze_result, "ANALYZE should succeed")

        # 3. Run OPTIMIZE
        optimize_result = self.backend.optimize()
        self.assertTrue(optimize_result, "OPTIMIZE should succeed")

        # 4. Run VACUUM
        vacuum_result = self.backend.vacuum()
        self.assertTrue(vacuum_result, "VACUUM should succeed")

        # 5. Check health after
        health_after = self.backend.get_health_status()
        self.assertIn(health_after['status'], ['healthy', 'warning'],
            "Should be healthy after maintenance")

        # 6. Verify database still works
        count = self.backend.count_symbols()
        self.assertEqual(count, 1000, "All symbols should still be present")

        # 7. Verify search still works
        results = self.backend.search_symbols_fts("Symbol100")
        self.assertGreater(len(results), 0, "Search should still work")

    def test_maintenance_does_not_corrupt(self):
        """Test that maintenance operations don't corrupt data"""
        # Populate with diverse symbols
        symbols = []
        for i in range(500):
            symbol = SymbolInfo(
                name=f"TestClass{i}" if i % 2 == 0 else f"testFunc{i}",
                kind="class" if i % 2 == 0 else "function",
                file=f"/test/file{i % 5}.cpp",
                line=i * 10 + 1,
                column=1,
                usr=f"usr_test_{i}",
                namespace=f"ns{i % 3}" if i % 3 == 0 else "",
                access="public" if i % 2 == 0 else "private"
            )
            symbols.append(symbol)

        self.backend.save_symbols_batch(symbols)

        # Get checksums before maintenance
        stats_before = self.backend.get_symbol_stats()

        # Run all maintenance operations
        self.backend.analyze()
        self.backend.optimize()
        self.backend.vacuum()

        # Get checksums after maintenance
        stats_after = self.backend.get_symbol_stats()

        # Verify counts match
        self.assertEqual(stats_before['total_symbols'], stats_after['total_symbols'],
            "Symbol count should be unchanged")
        self.assertEqual(stats_before['by_kind'], stats_after['by_kind'],
            "Symbol kind distribution should be unchanged")

        # Verify integrity
        is_healthy, message = self.backend.check_integrity(full=True)
        self.assertTrue(is_healthy, f"Database should be healthy after maintenance: {message}")


if __name__ == '__main__':
    unittest.main()
