#!/usr/bin/env python3
"""
Unit tests for configuration change detection feature.

This test suite verifies that the MCP server properly detects changes to
configuration files and compile_commands.json, and invalidates the cache
to trigger full re-indexing.
"""

import unittest
import json
import tempfile
import time
import shutil
from pathlib import Path
from typing import Dict, Any

# Import the modules to test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.cache_manager import CacheManager
from mcp_server.symbol_info import SymbolInfo


class TestConfigChangeDetection(unittest.TestCase):
    """Test suite for configuration change detection"""

    def setUp(self):
        """Set up test fixtures"""
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_config_detect_"))
        self.cache_manager = CacheManager(self.test_dir)

        # Create sample cache data
        self.sample_class_index = {}
        self.sample_function_index = {}
        self.sample_file_hashes = {
            str(self.test_dir / "test.cpp"): "abc123"
        }
        self.sample_indexed_count = 1

    def tearDown(self):
        """Clean up test fixtures"""
        # Close cache manager to avoid resource leaks
        if hasattr(self, 'cache_manager') and self.cache_manager is not None:
            try:
                self.cache_manager.close()
            except Exception:
                pass

        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def _create_config_file(self) -> Path:
        """Create a test configuration file"""
        config_file = self.test_dir / ".cpp-analyzer-config.json"
        config_file.write_text(json.dumps({
            "exclude_directories": [".git"],
            "include_dependencies": False
        }, indent=2))
        return config_file

    def _create_compile_commands_file(self) -> Path:
        """Create a test compile_commands.json file"""
        cc_file = self.test_dir / "compile_commands.json"
        cc_file.write_text(json.dumps([
            {
                "directory": str(self.test_dir),
                "file": str(self.test_dir / "test.cpp"),
                "arguments": ["-std=c++17"]
            }
        ], indent=2))
        return cc_file

    def test_cache_stores_config_metadata(self):
        """Test that cache properly stores configuration metadata"""
        config_file = self._create_config_file()
        cc_file = self._create_compile_commands_file()

        config_mtime = config_file.stat().st_mtime
        cc_mtime = cc_file.stat().st_mtime

        # Save cache with metadata
        success = self.cache_manager.save_cache(
            self.sample_class_index,
            self.sample_function_index,
            self.sample_file_hashes,
            self.sample_indexed_count,
            include_dependencies=False,
            config_file_path=config_file,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_file,
            compile_commands_mtime=cc_mtime
        )

        self.assertTrue(success, "Cache save should succeed")

        # Load the cache file and verify it exists (SQLite backend)
        cache_file = self.cache_manager.cache_dir / "symbols.db"
        self.assertTrue(cache_file.exists(), "Cache file should exist")

        # Verify metadata is stored by loading cache with same params
        # The SQLite backend stores metadata internally
        cache_data = self.cache_manager.load_cache(
            include_dependencies=False,
            config_file_path=config_file,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_file,
            compile_commands_mtime=cc_mtime
        )
        self.assertIsNotNone(cache_data, "Should be able to load cache with matching metadata")

    def test_cache_valid_when_config_unchanged(self):
        """Test that cache is valid when configuration hasn't changed"""
        config_file = self._create_config_file()
        cc_file = self._create_compile_commands_file()

        config_mtime = config_file.stat().st_mtime
        cc_mtime = cc_file.stat().st_mtime

        # Save cache
        self.cache_manager.save_cache(
            self.sample_class_index,
            self.sample_function_index,
            self.sample_file_hashes,
            self.sample_indexed_count,
            include_dependencies=False,
            config_file_path=config_file,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_file,
            compile_commands_mtime=cc_mtime
        )

        # Load cache with same metadata - should succeed
        cache_data = self.cache_manager.load_cache(
            include_dependencies=False,
            config_file_path=config_file,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_file,
            compile_commands_mtime=cc_mtime
        )

        self.assertIsNotNone(cache_data, "Cache should be valid when config unchanged")

    def test_cache_invalid_when_config_modified(self):
        """Test that cache is invalidated when config file is modified"""
        config_file = self._create_config_file()
        cc_file = self._create_compile_commands_file()

        original_mtime = config_file.stat().st_mtime
        cc_mtime = cc_file.stat().st_mtime

        # Save cache with original config
        self.cache_manager.save_cache(
            self.sample_class_index,
            self.sample_function_index,
            self.sample_file_hashes,
            self.sample_indexed_count,
            include_dependencies=False,
            config_file_path=config_file,
            config_file_mtime=original_mtime,
            compile_commands_path=cc_file,
            compile_commands_mtime=cc_mtime
        )

        # Wait and modify config file
        time.sleep(0.1)
        config_file.write_text(json.dumps({
            "exclude_directories": [".git", "build"],  # Modified
            "include_dependencies": False
        }, indent=2))

        new_mtime = config_file.stat().st_mtime
        self.assertNotEqual(original_mtime, new_mtime, "Config file mtime should change")

        # Load cache with new mtime - should be invalidated
        cache_data = self.cache_manager.load_cache(
            include_dependencies=False,
            config_file_path=config_file,
            config_file_mtime=new_mtime,
            compile_commands_path=cc_file,
            compile_commands_mtime=cc_mtime
        )

        self.assertIsNone(cache_data, "Cache should be invalidated when config modified")

    def test_cache_invalid_when_compile_commands_modified(self):
        """Test that cache is invalidated when compile_commands.json is modified"""
        config_file = self._create_config_file()
        cc_file = self._create_compile_commands_file()

        config_mtime = config_file.stat().st_mtime
        original_cc_mtime = cc_file.stat().st_mtime

        # Save cache with original compile_commands
        self.cache_manager.save_cache(
            self.sample_class_index,
            self.sample_function_index,
            self.sample_file_hashes,
            self.sample_indexed_count,
            include_dependencies=False,
            config_file_path=config_file,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_file,
            compile_commands_mtime=original_cc_mtime
        )

        # Wait and modify compile_commands.json
        time.sleep(0.1)
        cc_file.write_text(json.dumps([
            {
                "directory": str(self.test_dir),
                "file": str(self.test_dir / "test.cpp"),
                "arguments": ["-std=c++20"]  # Modified
            }
        ], indent=2))

        new_cc_mtime = cc_file.stat().st_mtime
        self.assertNotEqual(original_cc_mtime, new_cc_mtime, "compile_commands mtime should change")

        # Load cache with new mtime - should be invalidated
        cache_data = self.cache_manager.load_cache(
            include_dependencies=False,
            config_file_path=config_file,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_file,
            compile_commands_mtime=new_cc_mtime
        )

        self.assertIsNone(cache_data, "Cache should be invalidated when compile_commands modified")

    def test_cache_invalid_when_config_deleted(self):
        """Test that cache is invalidated when config file is deleted"""
        config_file = self._create_config_file()
        cc_file = self._create_compile_commands_file()

        config_mtime = config_file.stat().st_mtime
        cc_mtime = cc_file.stat().st_mtime

        # Save cache with config file
        self.cache_manager.save_cache(
            self.sample_class_index,
            self.sample_function_index,
            self.sample_file_hashes,
            self.sample_indexed_count,
            include_dependencies=False,
            config_file_path=config_file,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_file,
            compile_commands_mtime=cc_mtime
        )

        # Delete config file
        config_file.unlink()

        # Load cache with no config - should be invalidated
        cache_data = self.cache_manager.load_cache(
            include_dependencies=False,
            config_file_path=None,
            config_file_mtime=None,
            compile_commands_path=cc_file,
            compile_commands_mtime=cc_mtime
        )

        self.assertIsNone(cache_data, "Cache should be invalidated when config deleted")

    def test_cache_invalid_when_compile_commands_deleted(self):
        """Test that cache is invalidated when compile_commands.json is deleted"""
        config_file = self._create_config_file()
        cc_file = self._create_compile_commands_file()

        config_mtime = config_file.stat().st_mtime
        cc_mtime = cc_file.stat().st_mtime

        # Save cache with compile_commands
        self.cache_manager.save_cache(
            self.sample_class_index,
            self.sample_function_index,
            self.sample_file_hashes,
            self.sample_indexed_count,
            include_dependencies=False,
            config_file_path=config_file,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_file,
            compile_commands_mtime=cc_mtime
        )

        # Delete compile_commands.json
        cc_file.unlink()

        # Load cache with no compile_commands - should be invalidated
        cache_data = self.cache_manager.load_cache(
            include_dependencies=False,
            config_file_path=config_file,
            config_file_mtime=config_mtime,
            compile_commands_path=None,
            compile_commands_mtime=None
        )

        self.assertIsNone(cache_data, "Cache should be invalidated when compile_commands deleted")

    def test_cache_invalid_when_config_created(self):
        """Test that cache is invalidated when config file is created"""
        cc_file = self._create_compile_commands_file()
        cc_mtime = cc_file.stat().st_mtime

        # Save cache without config file
        self.cache_manager.save_cache(
            self.sample_class_index,
            self.sample_function_index,
            self.sample_file_hashes,
            self.sample_indexed_count,
            include_dependencies=False,
            config_file_path=None,
            config_file_mtime=None,
            compile_commands_path=cc_file,
            compile_commands_mtime=cc_mtime
        )

        # Create config file
        config_file = self._create_config_file()
        config_mtime = config_file.stat().st_mtime

        # Load cache with new config - should be invalidated
        cache_data = self.cache_manager.load_cache(
            include_dependencies=False,
            config_file_path=config_file,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_file,
            compile_commands_mtime=cc_mtime
        )

        self.assertIsNone(cache_data, "Cache should be invalidated when config created")

    def test_cache_invalid_when_compile_commands_created(self):
        """Test that cache is invalidated when compile_commands.json is created"""
        config_file = self._create_config_file()
        config_mtime = config_file.stat().st_mtime

        # Save cache without compile_commands
        self.cache_manager.save_cache(
            self.sample_class_index,
            self.sample_function_index,
            self.sample_file_hashes,
            self.sample_indexed_count,
            include_dependencies=False,
            config_file_path=config_file,
            config_file_mtime=config_mtime,
            compile_commands_path=None,
            compile_commands_mtime=None
        )

        # Create compile_commands.json
        cc_file = self._create_compile_commands_file()
        cc_mtime = cc_file.stat().st_mtime

        # Load cache with new compile_commands - should be invalidated
        cache_data = self.cache_manager.load_cache(
            include_dependencies=False,
            config_file_path=config_file,
            config_file_mtime=config_mtime,
            compile_commands_path=cc_file,
            compile_commands_mtime=cc_mtime
        )

        self.assertIsNone(cache_data, "Cache should be invalidated when compile_commands created")

    def test_cache_invalid_when_config_path_changed(self):
        """Test that cache is invalidated when config file path changes"""
        config_file1 = self._create_config_file()
        cc_file = self._create_compile_commands_file()

        config_mtime1 = config_file1.stat().st_mtime
        cc_mtime = cc_file.stat().st_mtime

        # Save cache with first config
        self.cache_manager.save_cache(
            self.sample_class_index,
            self.sample_function_index,
            self.sample_file_hashes,
            self.sample_indexed_count,
            include_dependencies=False,
            config_file_path=config_file1,
            config_file_mtime=config_mtime1,
            compile_commands_path=cc_file,
            compile_commands_mtime=cc_mtime
        )

        # Create a different config file (simulating CPP_ANALYZER_CONFIG change)
        config_file2 = self.test_dir / "alternate-config.json"
        config_file2.write_text(json.dumps({
            "exclude_directories": [".git"],
            "include_dependencies": False
        }, indent=2))
        config_mtime2 = config_file2.stat().st_mtime

        # Load cache with different config path - should be invalidated
        cache_data = self.cache_manager.load_cache(
            include_dependencies=False,
            config_file_path=config_file2,
            config_file_mtime=config_mtime2,
            compile_commands_path=cc_file,
            compile_commands_mtime=cc_mtime
        )

        self.assertIsNone(cache_data, "Cache should be invalidated when config path changes")

    def test_backward_compatibility_with_old_cache(self):
        """Test that old cache format without timestamps is handled gracefully"""
        # Skip this test - it's testing JSON backward compatibility which doesn't apply to SQLite backend
        self.skipTest("JSON backward compatibility test not applicable to SQLite backend")


def suite():
    """Create test suite"""
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestConfigChangeDetection))
    return suite


if __name__ == '__main__':
    unittest.main(verbosity=2)
