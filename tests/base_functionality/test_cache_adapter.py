"""
Base Functionality Tests - Cache Adapter Pattern

Tests for cache backend adapter pattern and feature flag.

Requirements: REQ-1.5 (Cache Management)
Priority: P1
"""

import unittest
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch

# Import test infrastructure
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cache_manager import CacheManager
from mcp_server.json_cache_backend import JsonCacheBackend
from mcp_server.sqlite_cache_backend import SqliteCacheBackend
from mcp_server.symbol_info import SymbolInfo


class TestCacheAdapter(unittest.TestCase):
    """Test cache adapter pattern and backend selection - REQ-1.5"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_project_dir = Path(self.temp_dir)
        (self.temp_project_dir / "src").mkdir(parents=True)

    def tearDown(self):
        """Clean up test fixtures"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_sqlite_backend_selected_with_flag_on(self):
        """Test that SQLite backend is selected when feature flag is enabled"""
        # Set feature flag to enable SQLite
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "1"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Verify SQLite backend is used
            self.assertIsInstance(cache_manager.backend, SqliteCacheBackend,
                "Should use SQLite backend when CLANG_INDEX_USE_SQLITE=1")

    def test_sqlite_backend_selected_with_flag_true(self):
        """Test that SQLite backend is selected when feature flag is 'true'"""
        # Set feature flag to enable SQLite (string 'true')
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "true"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Verify SQLite backend is used
            self.assertIsInstance(cache_manager.backend, SqliteCacheBackend,
                "Should use SQLite backend when CLANG_INDEX_USE_SQLITE=true")

    def test_json_backend_selected_with_flag_off(self):
        """Test that JSON backend is selected when feature flag is disabled"""
        # Set feature flag to disable SQLite
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "0"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Verify JSON backend is used
            self.assertIsInstance(cache_manager.backend, JsonCacheBackend,
                "Should use JSON backend when CLANG_INDEX_USE_SQLITE=0")

    def test_json_backend_selected_with_flag_false(self):
        """Test that JSON backend is selected when feature flag is 'false'"""
        # Set feature flag to disable SQLite (string 'false')
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "false"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Verify JSON backend is used
            self.assertIsInstance(cache_manager.backend, JsonCacheBackend,
                "Should use JSON backend when CLANG_INDEX_USE_SQLITE=false")

    def test_sqlite_backend_default(self):
        """Test that SQLite backend is the default when flag is not set"""
        # Ensure flag is not set
        env_without_flag = {k: v for k, v in os.environ.items()
                           if k != "CLANG_INDEX_USE_SQLITE"}

        with patch.dict(os.environ, env_without_flag, clear=True):
            cache_manager = CacheManager(self.temp_project_dir)

            # Verify SQLite backend is used by default
            self.assertIsInstance(cache_manager.backend, SqliteCacheBackend,
                "Should use SQLite backend by default")

    def test_fallback_to_json_on_sqlite_error(self):
        """Test that CacheManager falls back to JSON when SQLite fails to initialize"""
        # Set feature flag to enable SQLite
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "1"}):
            # Mock the SqliteCacheBackend import to raise an error
            with patch('mcp_server.sqlite_cache_backend.SqliteCacheBackend',
                      side_effect=Exception("SQLite init failed")):
                cache_manager = CacheManager(self.temp_project_dir)

                # Verify it fell back to JSON backend
                self.assertIsInstance(cache_manager.backend, JsonCacheBackend,
                    "Should fall back to JSON backend when SQLite initialization fails")

    def test_json_backend_compatibility(self):
        """Test that JSON backend implements all required methods"""
        # Create JSON backend
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "0"}):
            cache_manager = CacheManager(self.temp_project_dir)
            backend = cache_manager.backend

            # Verify all required methods are present
            self.assertTrue(hasattr(backend, 'save_cache'), "JSON backend must have save_cache")
            self.assertTrue(hasattr(backend, 'load_cache'), "JSON backend must have load_cache")
            self.assertTrue(hasattr(backend, 'save_file_cache'), "JSON backend must have save_file_cache")
            self.assertTrue(hasattr(backend, 'load_file_cache'), "JSON backend must have load_file_cache")
            self.assertTrue(hasattr(backend, 'remove_file_cache'), "JSON backend must have remove_file_cache")

    def test_sqlite_backend_compatibility(self):
        """Test that SQLite backend implements all required methods"""
        # Create SQLite backend
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "1"}):
            cache_manager = CacheManager(self.temp_project_dir)
            backend = cache_manager.backend

            # Verify all required methods are present
            self.assertTrue(hasattr(backend, 'save_cache'), "SQLite backend must have save_cache")
            self.assertTrue(hasattr(backend, 'load_cache'), "SQLite backend must have load_cache")
            self.assertTrue(hasattr(backend, 'save_file_cache'), "SQLite backend must have save_file_cache")
            self.assertTrue(hasattr(backend, 'load_file_cache'), "SQLite backend must have load_file_cache")
            self.assertTrue(hasattr(backend, 'remove_file_cache'), "SQLite backend must have remove_file_cache")

    def test_cache_manager_delegates_save_cache(self):
        """Test that CacheManager delegates save_cache to backend"""
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "0"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Mock the backend's save_cache method
            cache_manager.backend.save_cache = Mock(return_value=True)

            # Call CacheManager's save_cache
            result = cache_manager.save_cache({}, {}, {}, 0)

            # Verify delegation occurred
            self.assertTrue(cache_manager.backend.save_cache.called,
                "CacheManager should delegate save_cache to backend")
            self.assertTrue(result, "Should return backend's result")

    def test_cache_manager_delegates_load_cache(self):
        """Test that CacheManager delegates load_cache to backend"""
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "0"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Mock the backend's load_cache method
            mock_data = {"class_index": {}, "function_index": {}}
            cache_manager.backend.load_cache = Mock(return_value=mock_data)

            # Call CacheManager's load_cache
            result = cache_manager.load_cache()

            # Verify delegation occurred
            self.assertTrue(cache_manager.backend.load_cache.called,
                "CacheManager should delegate load_cache to backend")
            self.assertEqual(result, mock_data, "Should return backend's result")

    def test_cache_manager_delegates_save_file_cache(self):
        """Test that CacheManager delegates save_file_cache to backend"""
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "0"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Mock the backend's save_file_cache method
            cache_manager.backend.save_file_cache = Mock(return_value=True)

            # Call CacheManager's save_file_cache
            symbols = [SymbolInfo("usr1", "TestClass", "class", "/test.cpp", 1, 1)]
            result = cache_manager.save_file_cache("/test.cpp", symbols, "hash123")

            # Verify delegation occurred
            self.assertTrue(cache_manager.backend.save_file_cache.called,
                "CacheManager should delegate save_file_cache to backend")
            self.assertTrue(result, "Should return backend's result")

    def test_cache_manager_delegates_load_file_cache(self):
        """Test that CacheManager delegates load_file_cache to backend"""
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "0"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Mock the backend's load_file_cache method
            mock_data = {
                'symbols': [],
                'success': True,
                'error_message': None,
                'retry_count': 0
            }
            cache_manager.backend.load_file_cache = Mock(return_value=mock_data)

            # Call CacheManager's load_file_cache
            result = cache_manager.load_file_cache("/test.cpp", "hash123")

            # Verify delegation occurred
            self.assertTrue(cache_manager.backend.load_file_cache.called,
                "CacheManager should delegate load_file_cache to backend")
            self.assertEqual(result, mock_data, "Should return backend's result")

    def test_cache_manager_delegates_remove_file_cache(self):
        """Test that CacheManager delegates remove_file_cache to backend"""
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "0"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Mock the backend's remove_file_cache method
            cache_manager.backend.remove_file_cache = Mock(return_value=True)

            # Call CacheManager's remove_file_cache
            result = cache_manager.remove_file_cache("/test.cpp")

            # Verify delegation occurred
            self.assertTrue(cache_manager.backend.remove_file_cache.called,
                "CacheManager should delegate remove_file_cache to backend")
            self.assertTrue(result, "Should return backend's result")

    def test_json_backend_basic_operations(self):
        """Test basic JSON backend save/load operations"""
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "0"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Create test data
            class_index = {
                "TestClass": [SymbolInfo("usr1", "TestClass", "class", "/test.cpp", 1, 1)]
            }
            function_index = {
                "testFunc": [SymbolInfo("usr2", "testFunc", "function", "/test.cpp", 5, 1)]
            }
            file_hashes = {"/test.cpp": "hash123"}

            # Save cache
            result = cache_manager.save_cache(class_index, function_index, file_hashes, 1)
            self.assertTrue(result, "Should successfully save cache")

            # Load cache
            loaded = cache_manager.load_cache()
            self.assertIsNotNone(loaded, "Should successfully load cache")
            self.assertIn("class_index", loaded, "Loaded cache should contain class_index")
            self.assertIn("function_index", loaded, "Loaded cache should contain function_index")

    def test_sqlite_backend_basic_operations(self):
        """Test basic SQLite backend save/load operations"""
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "1"}):
            cache_manager = CacheManager(self.temp_project_dir)

            # Create test data
            class_index = {
                "TestClass": [SymbolInfo("usr1", "TestClass", "class", "/test.cpp", 1, 1)]
            }
            function_index = {
                "testFunc": [SymbolInfo("usr2", "testFunc", "function", "/test.cpp", 5, 1)]
            }
            file_hashes = {"/test.cpp": "hash123"}

            # Save cache
            result = cache_manager.save_cache(class_index, function_index, file_hashes, 1)
            self.assertTrue(result, "Should successfully save cache")

            # Load cache
            loaded = cache_manager.load_cache()
            self.assertIsNotNone(loaded, "Should successfully load cache")
            self.assertIn("class_index", loaded, "Loaded cache should contain class_index")
            self.assertIn("function_index", loaded, "Loaded cache should contain function_index")


if __name__ == '__main__':
    unittest.main()
