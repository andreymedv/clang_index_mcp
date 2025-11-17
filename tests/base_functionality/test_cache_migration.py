"""
Base Functionality Tests - Cache Migration

Tests for automatic JSON → SQLite cache migration.

Requirements: REQ-1.5 (Cache Management)
Priority: P1
"""

import unittest
import os
import sys
import tempfile
import shutil
import json
from pathlib import Path
from unittest.mock import Mock, patch

# Import test infrastructure
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cache_migration import (
    migrate_json_to_sqlite,
    verify_migration,
    create_migration_backup,
    should_migrate,
    create_migration_marker
)
from mcp_server.sqlite_cache_backend import SqliteCacheBackend
from mcp_server.symbol_info import SymbolInfo


class TestCacheMigration(unittest.TestCase):
    """Test cache migration functionality - REQ-1.5"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.cache_dir = Path(self.temp_dir) / "cache"
        self.cache_dir.mkdir(parents=True)
        self.db_path = self.cache_dir / "symbols.db"

    def tearDown(self):
        """Clean up test fixtures"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def create_json_cache(self, symbol_count=100):
        """Helper to create a test JSON cache"""
        # Create symbols
        symbols = []
        class_index = {}
        function_index = {}

        for i in range(symbol_count):
            if i % 2 == 0:
                # Create class
                symbol = SymbolInfo(
                    name=f"TestClass{i}",
                    kind="class",
                    file=f"/test/file{i % 10}.cpp",
                    line=i * 10 + 1,
                    column=1,
                    usr=f"usr_class_{i}"
                )
                symbols.append(symbol)
                class_index.setdefault(symbol.name, []).append(symbol.to_dict())
            else:
                # Create function
                symbol = SymbolInfo(
                    name=f"testFunc{i}",
                    kind="function",
                    file=f"/test/file{i % 10}.cpp",
                    line=i * 10 + 1,
                    column=1,
                    usr=f"usr_func_{i}"
                )
                symbols.append(symbol)
                function_index.setdefault(symbol.name, []).append(symbol.to_dict())

        # Create file_hashes
        file_hashes = {}
        for i in range(10):
            file_hashes[f"/test/file{i}.cpp"] = f"hash_{i}"

        # Create cache_info.json
        cache_data = {
            "version": "2.0",
            "include_dependencies": False,
            "config_file_path": None,
            "config_file_mtime": None,
            "compile_commands_path": None,
            "compile_commands_mtime": None,
            "class_index": class_index,
            "function_index": function_index,
            "file_hashes": file_hashes,
            "indexed_file_count": 10,
            "timestamp": 1234567890.0
        }

        cache_info_path = self.cache_dir / "cache_info.json"
        with open(cache_info_path, 'w') as f:
            json.dump(cache_data, f, indent=2)

        return symbols, cache_data

    def test_migrate_small_project(self):
        """Test migration of small project (100 symbols)"""
        # Create JSON cache with 100 symbols
        symbols, cache_data = self.create_json_cache(100)

        # Perform migration
        success, message = migrate_json_to_sqlite(self.cache_dir, self.db_path)

        # Verify migration succeeded
        self.assertTrue(success, f"Migration should succeed: {message}")
        self.assertIn("100 symbols", message.lower() or message.lower())

        # Verify database was created
        self.assertTrue(self.db_path.exists(), "Database file should exist")

        # Verify symbol count
        backend = SqliteCacheBackend(self.db_path)
        stats = backend.get_symbol_stats()

        # Account for duplicates (symbols in both indexes)
        unique_symbols = set()
        for symbol_dicts in cache_data["class_index"].values():
            for symbol_dict in symbol_dicts:
                unique_symbols.add(symbol_dict["usr"])
        for symbol_dicts in cache_data["function_index"].values():
            for symbol_dict in symbol_dicts:
                unique_symbols.add(symbol_dict["usr"])

        self.assertEqual(stats['total_symbols'], len(unique_symbols),
            "SQLite should contain all unique symbols")

    def test_migrate_medium_project(self):
        """Test migration of medium project (1000 symbols)"""
        # Create JSON cache with 1000 symbols
        symbols, cache_data = self.create_json_cache(1000)

        # Perform migration
        success, message = migrate_json_to_sqlite(self.cache_dir, self.db_path)

        # Verify migration succeeded
        self.assertTrue(success, f"Migration should succeed: {message}")

        # Verify database was created
        self.assertTrue(self.db_path.exists(), "Database file should exist")

        # Verify symbol count
        backend = SqliteCacheBackend(self.db_path)
        stats = backend.get_symbol_stats()
        self.assertEqual(stats['total_symbols'], 1000, "SQLite should contain 1000 symbols")

    def test_migration_verification(self):
        """Test migration verification"""
        # Create JSON cache
        symbols, cache_data = self.create_json_cache(100)

        # Perform migration
        migrate_success, migrate_msg = migrate_json_to_sqlite(self.cache_dir, self.db_path)
        self.assertTrue(migrate_success, "Migration should succeed")

        # Verify migration
        verify_success, verify_msg = verify_migration(self.cache_dir, self.db_path)

        # Should succeed
        self.assertTrue(verify_success, f"Verification should pass: {verify_msg}")
        self.assertIn("successful", verify_msg.lower())

    def test_backup_creation(self):
        """Test backup creation before migration"""
        # Create JSON cache
        symbols, cache_data = self.create_json_cache(50)

        # Create backup
        backup_success, backup_msg, backup_path = create_migration_backup(self.cache_dir)

        # Verify backup succeeded
        self.assertTrue(backup_success, f"Backup should succeed: {backup_msg}")
        self.assertIsNotNone(backup_path, "Backup path should be returned")
        self.assertTrue(backup_path.exists(), "Backup directory should exist")

        # Verify backup contains cache_info.json
        backup_cache_info = backup_path / "cache_info.json"
        self.assertTrue(backup_cache_info.exists(), "Backup should contain cache_info.json")

        # Verify backup contents match original
        with open(backup_cache_info, 'r') as f:
            backup_data = json.load(f)

        self.assertEqual(backup_data["version"], cache_data["version"],
            "Backup should have same version")
        self.assertEqual(backup_data["indexed_file_count"], cache_data["indexed_file_count"],
            "Backup should have same file count")

    def test_marker_prevents_remigration(self):
        """Test that marker file prevents re-migration"""
        marker_path = self.cache_dir / ".migrated_to_sqlite"

        # Create JSON cache
        symbols, cache_data = self.create_json_cache(50)

        # Initially, migration should be needed
        self.assertTrue(should_migrate(self.cache_dir, marker_path),
            "Migration should be needed without marker")

        # Create marker
        migration_info = {"test": "data"}
        marker_created = create_migration_marker(marker_path, migration_info)
        self.assertTrue(marker_created, "Marker creation should succeed")
        self.assertTrue(marker_path.exists(), "Marker file should exist")

        # Now migration should not be needed
        self.assertFalse(should_migrate(self.cache_dir, marker_path),
            "Migration should not be needed with marker")

    def test_migration_preserves_metadata(self):
        """Test that migration preserves cache metadata"""
        # Create JSON cache with metadata
        symbols, cache_data = self.create_json_cache(50)

        # Perform migration
        success, message = migrate_json_to_sqlite(self.cache_dir, self.db_path)
        self.assertTrue(success, "Migration should succeed")

        # Verify metadata was preserved
        backend = SqliteCacheBackend(self.db_path)

        include_deps = backend.get_cache_metadata("include_dependencies")
        self.assertEqual(include_deps, str(cache_data["include_dependencies"]),
            "include_dependencies should be preserved")

        indexed_count = backend.get_cache_metadata("indexed_file_count")
        self.assertEqual(indexed_count, str(cache_data["indexed_file_count"]),
            "indexed_file_count should be preserved")

    def test_migration_preserves_file_metadata(self):
        """Test that migration preserves file metadata"""
        # Create JSON cache
        symbols, cache_data = self.create_json_cache(100)

        # Perform migration
        success, message = migrate_json_to_sqlite(self.cache_dir, self.db_path)
        self.assertTrue(success, "Migration should succeed")

        # Verify file metadata
        backend = SqliteCacheBackend(self.db_path)

        for file_path, expected_hash in cache_data["file_hashes"].items():
            metadata = backend.get_file_metadata(file_path)
            self.assertIsNotNone(metadata, f"Metadata should exist for {file_path}")
            self.assertEqual(metadata["file_hash"], expected_hash,
                f"File hash should match for {file_path}")

    def test_migration_handles_no_json_cache(self):
        """Test migration handles missing JSON cache gracefully"""
        # Don't create JSON cache

        # Attempt migration
        success, message = migrate_json_to_sqlite(self.cache_dir, self.db_path)

        # Should fail gracefully
        self.assertFalse(success, "Migration should fail without JSON cache")
        self.assertIn("no json cache", message.lower())

    def test_migration_handles_invalid_version(self):
        """Test migration rejects unsupported cache version"""
        # Create cache with wrong version
        cache_data = {
            "version": "1.0",  # Wrong version
            "class_index": {},
            "function_index": {},
            "file_hashes": {}
        }

        cache_info_path = self.cache_dir / "cache_info.json"
        with open(cache_info_path, 'w') as f:
            json.dump(cache_data, f)

        # Attempt migration
        success, message = migrate_json_to_sqlite(self.cache_dir, self.db_path)

        # Should fail
        self.assertFalse(success, "Migration should fail with wrong version")
        self.assertIn("unsupported", message.lower())

    def test_verification_detects_count_mismatch(self):
        """Test verification detects symbol count mismatch"""
        # Create JSON cache
        symbols, cache_data = self.create_json_cache(100)

        # Perform partial migration (manually)
        backend = SqliteCacheBackend(self.db_path)
        # Only migrate half the symbols
        partial_symbols = symbols[:50]
        backend.save_symbols_batch(partial_symbols)

        # Verification should fail
        verify_success, verify_msg = verify_migration(self.cache_dir, self.db_path)

        self.assertFalse(verify_success, "Verification should fail with count mismatch")
        self.assertIn("mismatch", verify_msg.lower())

    def test_should_migrate_detects_json_cache(self):
        """Test should_migrate correctly detects JSON cache presence"""
        marker_path = self.cache_dir / ".migrated_to_sqlite"

        # Without JSON cache
        self.assertFalse(should_migrate(self.cache_dir, marker_path),
            "Should not migrate without JSON cache")

        # With JSON cache
        symbols, cache_data = self.create_json_cache(10)
        self.assertTrue(should_migrate(self.cache_dir, marker_path),
            "Should migrate with JSON cache and no marker")


class TestCacheManagerMigration(unittest.TestCase):
    """Test CacheManager integration with migration"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_project_dir = Path(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_cache_manager_auto_migrates(self):
        """Test that CacheManager automatically migrates on first SQLite use"""
        from mcp_server.cache_manager import CacheManager
        from mcp_server.sqlite_cache_backend import SqliteCacheBackend

        # Create cache manager to get cache directory
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "0"}):
            cache_manager_json = CacheManager(self.temp_project_dir)
            cache_dir = cache_manager_json.cache_dir

        # Create JSON cache manually
        cache_data = {
            "version": "2.0",
            "include_dependencies": False,
            "config_file_path": None,
            "config_file_mtime": None,
            "compile_commands_path": None,
            "compile_commands_mtime": None,
            "class_index": {
                "TestClass": [{
                    "usr": "usr_test",
                    "name": "TestClass",
                    "kind": "class",
                    "file": "/test.cpp",
                    "line": 1,
                    "column": 1,
                    "signature": "",
                    "is_project": True,
                    "namespace": "",
                    "access": "public",
                    "parent_class": "",
                    "base_classes": "[]",
                    "calls": "[]",
                    "called_by": "[]"
                }]
            },
            "function_index": {},
            "file_hashes": {"/test.cpp": "hash123"},
            "indexed_file_count": 1,
            "timestamp": 1234567890.0
        }

        cache_info_path = cache_dir / "cache_info.json"
        with open(cache_info_path, 'w') as f:
            json.dump(cache_data, f)

        # Create new cache manager with SQLite enabled
        with patch.dict(os.environ, {"CLANG_INDEX_USE_SQLITE": "1"}):
            cache_manager_sqlite = CacheManager(self.temp_project_dir)

            # Should have automatically migrated
            self.assertIsInstance(cache_manager_sqlite.backend, SqliteCacheBackend,
                "Should use SQLite backend after auto-migration")

            # Verify migration marker exists
            marker_path = cache_dir / ".migrated_to_sqlite"
            self.assertTrue(marker_path.exists(), "Migration marker should exist")

            # Verify symbols were migrated
            backend = cache_manager_sqlite.backend
            stats = backend.get_symbol_stats()
            self.assertEqual(stats['total_symbols'], 1, "Should have migrated 1 symbol")


if __name__ == '__main__':
    unittest.main()
