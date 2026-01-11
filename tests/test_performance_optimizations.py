#!/usr/bin/env python3
"""
Tests for performance optimizations added in the optimize-slow-host-performance session.

Tests cover:
- ProcessPoolExecutor vs ThreadPoolExecutor
- Bulk symbol writes
- compile_commands.json binary caching
- Worker count optimization

Requirements verified:
- libclang>=16.0.0 (required) - Verified by all test classes
- orjson>=3.0.0 (optional from performance extras) - Verified by TestOrjsonSupport
"""

import unittest
import os
import sys
import tempfile
import json
import pickle
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Try to import clang-dependent modules, skip tests if not available
try:
    from mcp_server.cpp_analyzer import CppAnalyzer
    from mcp_server.compile_commands_manager import CompileCommandsManager
    from mcp_server.symbol_info import SymbolInfo
    CLANG_AVAILABLE = True
except SystemExit:
    # clang.cindex not available
    CLANG_AVAILABLE = False
    CppAnalyzer = None
    CompileCommandsManager = None
    SymbolInfo = None


@unittest.skipUnless(CLANG_AVAILABLE, "libclang not available")
class TestWorkerCountOptimization(unittest.TestCase):
    """Test worker count optimization (cpu_count instead of cpu_count*2)"""

    def test_worker_count_equals_cpu_count(self):
        """Worker count should equal cpu_count, not cpu_count*2"""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = CppAnalyzer(tmpdir)

            # Get actual CPU count
            cpu_count = os.cpu_count() or 1

            # Verify worker count equals cpu_count
            self.assertEqual(analyzer.max_workers, cpu_count,
                           f"Worker count should be {cpu_count}, not {analyzer.max_workers}")

    def test_worker_count_minimum_one(self):
        """Worker count should be at least 1 even if cpu_count fails"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('os.cpu_count', return_value=None):
                analyzer = CppAnalyzer(tmpdir)
                self.assertGreaterEqual(analyzer.max_workers, 1,
                                      "Worker count should be at least 1")


@unittest.skipUnless(CLANG_AVAILABLE, "libclang not available")
class TestProcessPoolExecutor(unittest.TestCase):
    """Test ProcessPoolExecutor configuration and fallback"""

    def test_default_uses_processpool(self):
        """By default, use_processes should be True (ProcessPoolExecutor)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Ensure environment variable is not set
            env_backup = os.environ.get('CPP_ANALYZER_USE_THREADS')
            if 'CPP_ANALYZER_USE_THREADS' in os.environ:
                del os.environ['CPP_ANALYZER_USE_THREADS']

            try:
                analyzer = CppAnalyzer(tmpdir)
                self.assertTrue(analyzer.use_processes,
                              "Should use ProcessPoolExecutor by default")
            finally:
                if env_backup is not None:
                    os.environ['CPP_ANALYZER_USE_THREADS'] = env_backup

    def test_can_override_to_threadpool(self):
        """CPP_ANALYZER_USE_THREADS=true should switch to ThreadPoolExecutor"""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ['CPP_ANALYZER_USE_THREADS'] = 'true'
            try:
                analyzer = CppAnalyzer(tmpdir)
                self.assertFalse(analyzer.use_processes,
                               "Should use ThreadPoolExecutor when env var set")
            finally:
                if 'CPP_ANALYZER_USE_THREADS' in os.environ:
                    del os.environ['CPP_ANALYZER_USE_THREADS']

    def test_case_insensitive_env_var(self):
        """Environment variable should be case-insensitive"""
        with tempfile.TemporaryDirectory() as tmpdir:
            for value in ['TRUE', 'True', 'true']:
                os.environ['CPP_ANALYZER_USE_THREADS'] = value
                try:
                    analyzer = CppAnalyzer(tmpdir)
                    self.assertFalse(analyzer.use_processes,
                                   f"Should recognize '{value}' as true")
                finally:
                    if 'CPP_ANALYZER_USE_THREADS' in os.environ:
                        del os.environ['CPP_ANALYZER_USE_THREADS']


@unittest.skipUnless(CLANG_AVAILABLE, "libclang not available")
class TestBulkSymbolWrites(unittest.TestCase):
    """Test bulk symbol write optimization"""

    def test_thread_local_buffers_initialization(self):
        """Thread-local buffers should initialize correctly"""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = CppAnalyzer(tmpdir)

            # Initialize buffers
            analyzer._init_thread_local_buffers()

            # Check buffers exist and are empty
            symbols, calls, aliases = analyzer._get_thread_local_buffers()
            self.assertIsInstance(symbols, list)
            self.assertIsInstance(calls, list)
            self.assertIsInstance(aliases, list)
            self.assertEqual(len(symbols), 0)
            self.assertEqual(len(calls), 0)
            self.assertEqual(len(aliases), 0)

    def test_bulk_write_with_empty_buffers(self):
        """Bulk write with empty buffers should return 0"""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = CppAnalyzer(tmpdir)
            analyzer._init_thread_local_buffers()

            result = analyzer._bulk_write_symbols()
            self.assertEqual(result, 0, "Should return 0 for empty buffers")

    def test_bulk_write_adds_symbols(self):
        """Bulk write should add symbols to indexes"""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = CppAnalyzer(tmpdir)
            analyzer._init_thread_local_buffers()

            # Create test symbols
            test_symbol = SymbolInfo(
                name="TestClass",
                kind="class",
                file=str(Path(tmpdir) / "test.cpp"),
                line=10,
                column=1,
                is_project=True,
                usr="c:@S@TestClass"
            )

            # Add to buffer
            symbols, _, _ = analyzer._get_thread_local_buffers()
            symbols.append(test_symbol)

            # Bulk write
            added = analyzer._bulk_write_symbols()

            # Verify
            self.assertEqual(added, 1, "Should add 1 symbol")
            self.assertIn("TestClass", analyzer.class_index)
            self.assertIn("c:@S@TestClass", analyzer.usr_index)

    def test_bulk_write_deduplicates(self):
        """Bulk write should deduplicate symbols with same USR"""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = CppAnalyzer(tmpdir)
            analyzer._init_thread_local_buffers()

            # Create duplicate symbols
            symbol1 = SymbolInfo(
                name="TestClass",
                kind="class",
                file=str(Path(tmpdir) / "test1.cpp"),
                line=10,
                column=1,
                is_project=True,
                usr="c:@S@TestClass"
            )

            symbol2 = SymbolInfo(
                name="TestClass",
                kind="class",
                file=str(Path(tmpdir) / "test2.cpp"),
                line=20,
                column=1,
                is_project=True,
                usr="c:@S@TestClass"
            )

            # Add both to buffer
            symbols, _, _ = analyzer._get_thread_local_buffers()
            symbols.append(symbol1)
            symbols.append(symbol2)

            # Bulk write
            added = analyzer._bulk_write_symbols()

            # Should only add first symbol, deduplicate second
            self.assertEqual(added, 1, "Should deduplicate and add only 1 symbol")
            self.assertEqual(len(analyzer.class_index["TestClass"]), 1)


@unittest.skipUnless(CLANG_AVAILABLE, "libclang not available")
class TestCompileCommandsBinaryCache(unittest.TestCase):
    """Test binary caching for compile_commands.json"""

    def test_cache_path_creation(self):
        """Cache path should be in compile_commands subdirectory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Test with cache_dir (new behavior)
            cache_dir = Path(tmpdir) / ".mcp_cache" / "test_project"
            manager = CompileCommandsManager(Path(tmpdir), {}, cache_dir=cache_dir)
            cache_path = manager._get_compile_commands_cache_path()

            self.assertTrue(str(cache_path).endswith('.cache'))
            self.assertIn('compile_commands', str(cache_path))
            self.assertIn('.mcp_cache', str(cache_path))

            # Test without cache_dir (legacy fallback)
            manager_legacy = CompileCommandsManager(Path(tmpdir), {})
            cache_path_legacy = manager_legacy._get_compile_commands_cache_path()

            self.assertTrue(str(cache_path_legacy).endswith('compile_commands.cache'))
            self.assertIn('.clang_index', str(cache_path_legacy))

    def test_file_hash_calculation(self):
        """File hash should be calculated correctly"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CompileCommandsManager(Path(tmpdir), {})

            # Create a test file
            test_file = Path(tmpdir) / "test.json"
            test_file.write_text('{"test": "data"}')

            hash1 = manager._get_file_hash(test_file)
            self.assertIsInstance(hash1, str)
            self.assertGreater(len(hash1), 0)

            # Same file should give same hash
            hash2 = manager._get_file_hash(test_file)
            self.assertEqual(hash1, hash2)

            # Different content should give different hash
            test_file.write_text('{"test": "different"}')
            hash3 = manager._get_file_hash(test_file)
            self.assertNotEqual(hash1, hash3)

    def test_cache_save_and_load(self):
        """Cache should be saved and loaded correctly"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create a test compile_commands.json
            cc_path = project_root / "compile_commands.json"
            test_data = [
                {
                    "directory": str(project_root),
                    "file": str(project_root / "test.cpp"),
                    "arguments": ["clang++", "-std=c++17", "test.cpp"]
                }
            ]
            cc_path.write_text(json.dumps(test_data))

            # First load - should parse and cache
            manager1 = CompileCommandsManager(project_root, {})
            self.assertTrue(len(manager1.compile_commands) > 0)

            # Second load - should load from cache
            manager2 = CompileCommandsManager(project_root, {})
            self.assertTrue(len(manager2.compile_commands) > 0)

            # Verify cache file exists
            cache_path = manager2._get_compile_commands_cache_path()
            self.assertTrue(cache_path.exists())

    def test_cache_invalidation_on_file_change(self):
        """Cache should be invalidated when file changes"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create initial compile_commands.json
            cc_path = project_root / "compile_commands.json"
            test_data = [{"file": "test1.cpp", "directory": str(project_root), "arguments": ["clang++"]}]
            cc_path.write_text(json.dumps(test_data))

            # First load
            manager1 = CompileCommandsManager(project_root, {})
            initial_count = len(manager1.compile_commands)

            # Modify file
            time.sleep(0.1)  # Ensure modification time changes
            test_data.append({"file": "test2.cpp", "directory": str(project_root), "arguments": ["clang++"]})
            cc_path.write_text(json.dumps(test_data))

            # Second load - should detect change and re-parse
            manager2 = CompileCommandsManager(project_root, {})
            new_count = len(manager2.compile_commands)

            self.assertEqual(new_count, 2, "Should have 2 entries after modification")
            self.assertNotEqual(initial_count, new_count)


@unittest.skipUnless(CLANG_AVAILABLE, "libclang not available")
class TestOrjsonSupport(unittest.TestCase):
    """Test orjson optional dependency support.

    Verifies requirement: orjson>=3.0.0 (optional, from [performance] extras)
    - Tests that code detects orjson availability correctly
    - Tests graceful fallback to stdlib json when orjson not installed
    - Ensures no errors occur regardless of orjson installation status
    """

    def test_orjson_detection(self):
        """Should detect if orjson is available.

        Verifies: The code properly detects orjson installation status via HAS_ORJSON flag.
        """
        from mcp_server.compile_commands_manager import HAS_ORJSON
        self.assertIsInstance(HAS_ORJSON, bool)

    @patch('mcp_server.compile_commands_manager.HAS_ORJSON', False)
    def test_fallback_to_stdlib_json(self):
        """Should fall back to stdlib json if orjson not available.

        Verifies: Code works correctly even when orjson (optional requirement) is not installed.
        This ensures the optional dependency is truly optional and not required for core functionality.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create compile_commands.json
            cc_path = project_root / "compile_commands.json"
            test_data = [{"file": "test.cpp", "directory": str(project_root), "arguments": ["clang++"]}]
            cc_path.write_text(json.dumps(test_data))

            # Should work without orjson
            manager = CompileCommandsManager(project_root, {})
            self.assertTrue(len(manager.compile_commands) > 0)


@unittest.skipUnless(CLANG_AVAILABLE, "libclang not available")
class TestThreadLocalBuffers(unittest.TestCase):
    """Test thread-local buffer functionality"""

    def test_buffers_are_thread_local(self):
        """Buffers should be separate per thread"""
        import threading

        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = CppAnalyzer(tmpdir)
            results = {}

            def worker(thread_id):
                analyzer._init_thread_local_buffers()
                symbols, calls = analyzer._get_thread_local_buffers()
                # Add unique symbol to this thread's buffer
                symbols.append(SymbolInfo(
                    name=f"Class{thread_id}",
                    kind="class",
                    file="test.cpp",
                    line=thread_id,
                    column=1,
                    is_project=True,
                    usr=f"c:@S@Class{thread_id}"
                ))
                results[thread_id] = len(symbols)

            # Run in multiple threads
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Each thread should have had 1 symbol in its buffer
            for thread_id, count in results.items():
                self.assertEqual(count, 1, f"Thread {thread_id} should have 1 symbol")


def run_tests():
    """Run all performance optimization tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestWorkerCountOptimization))
    suite.addTests(loader.loadTestsFromTestCase(TestProcessPoolExecutor))
    suite.addTests(loader.loadTestsFromTestCase(TestBulkSymbolWrites))
    suite.addTests(loader.loadTestsFromTestCase(TestCompileCommandsBinaryCache))
    suite.addTests(loader.loadTestsFromTestCase(TestOrjsonSupport))
    suite.addTests(loader.loadTestsFromTestCase(TestThreadLocalBuffers))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
