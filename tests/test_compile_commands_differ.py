"""Unit tests for compile-commands diff/hash helpers on CompileCommandsManager."""

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from clang_index_mcp._compilation.compile_commands_manager import CompileCommandsManager
from clang_index_mcp.cpp_analyzer_config import CompileCommandsConfig


class TestCompileCommandsDiffer(unittest.TestCase):
    """Test cases for compile-commands diff and hash helpers."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = Path(tempfile.mkdtemp())
        self.db_path = self.test_dir / "test.db"
        self.conn = sqlite3.connect(str(self.db_path))

        # Create file_metadata table
        self.conn.execute("""
            CREATE TABLE file_metadata (
                file_path TEXT PRIMARY KEY,
                file_hash TEXT NOT NULL,
                compile_args_hash TEXT,
                indexed_at REAL NOT NULL,
                symbol_count INTEGER DEFAULT 0
            )
        """)
        self.conn.commit()

        # Create mock backend implementing CacheBackend protocol
        class MockBackend:
            def __init__(self, conn):
                self.conn = conn

            def set_compile_args_hash(self, file_path: str, args_hash: str) -> bool:
                cursor = self.conn.execute(
                    "UPDATE file_metadata SET compile_args_hash = ? WHERE file_path = ?",
                    (args_hash, file_path),
                )
                if cursor.rowcount == 0:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO file_metadata "
                        "(file_path, file_hash, compile_args_hash, indexed_at, symbol_count) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (file_path, "", args_hash, 0.0, 0),
                    )
                self.conn.commit()
                return True

            def get_compile_args_hash(self, file_path: str):
                cursor = self.conn.execute(
                    "SELECT compile_args_hash FROM file_metadata WHERE file_path = ?",
                    (file_path,),
                )
                row = cursor.fetchone()
                return row[0] if row else None

            def clear_compile_args_hashes(self) -> int:
                cursor = self.conn.execute("UPDATE file_metadata SET compile_args_hash = NULL")
                self.conn.commit()
                return cursor.rowcount or 0

        self.backend = MockBackend(self.conn)
        self.manager = CompileCommandsManager(
            self.test_dir,
            CompileCommandsConfig(compile_commands_enabled=False, fallback_to_hardcoded=False),
            cache_backend=self.backend,
        )

    def tearDown(self):
        """Clean up test fixtures."""
        self.conn.close()
        shutil.rmtree(self.test_dir)

    def test_compute_diff_no_changes(self):
        """Test diff when no changes."""
        commands = {"main.cpp": ["-std=c++17", "-O2"], "utils.cpp": ["-std=c++17"]}

        added, removed, changed = CompileCommandsManager.compute_commands_diff(commands, commands)

        self.assertEqual(len(added), 0)
        self.assertEqual(len(removed), 0)
        self.assertEqual(len(changed), 0)

    def test_compute_diff_added_file(self):
        """Test detecting added file."""
        old_commands = {"main.cpp": ["-std=c++17"]}

        new_commands = {"main.cpp": ["-std=c++17"], "new.cpp": ["-std=c++17"]}

        added, removed, changed = CompileCommandsManager.compute_commands_diff(
            old_commands, new_commands
        )

        self.assertEqual(added, {"new.cpp"})
        self.assertEqual(len(removed), 0)
        self.assertEqual(len(changed), 0)

    def test_compute_diff_removed_file(self):
        """Test detecting removed file."""
        old_commands = {"main.cpp": ["-std=c++17"], "old.cpp": ["-std=c++17"]}

        new_commands = {"main.cpp": ["-std=c++17"]}

        added, removed, changed = CompileCommandsManager.compute_commands_diff(
            old_commands, new_commands
        )

        self.assertEqual(len(added), 0)
        self.assertEqual(removed, {"old.cpp"})
        self.assertEqual(len(changed), 0)

    def test_compute_diff_changed_args(self):
        """Test detecting changed compilation arguments."""
        old_commands = {"main.cpp": ["-std=c++17", "-O2"]}

        new_commands = {"main.cpp": ["-std=c++20", "-O3"]}

        added, removed, changed = CompileCommandsManager.compute_commands_diff(
            old_commands, new_commands
        )

        self.assertEqual(len(added), 0)
        self.assertEqual(len(removed), 0)
        self.assertEqual(changed, {"main.cpp"})

    def test_compute_diff_multiple_changes(self):
        """Test detecting multiple types of changes."""
        old_commands = {
            "main.cpp": ["-std=c++17", "-O2"],
            "utils.cpp": ["-std=c++17"],
            "old.cpp": ["-std=c++11"],
        }

        new_commands = {
            "main.cpp": ["-std=c++20", "-O3"],  # Changed
            "utils.cpp": ["-std=c++17"],  # Unchanged
            "new.cpp": ["-std=c++17"],  # Added
            # old.cpp removed
        }

        added, removed, changed = CompileCommandsManager.compute_commands_diff(
            old_commands, new_commands
        )

        self.assertEqual(added, {"new.cpp"})
        self.assertEqual(removed, {"old.cpp"})
        self.assertEqual(changed, {"main.cpp"})

    def test_hash_args_stable(self):
        """Test that argument hashing is stable."""
        args = ["-std=c++17", "-O2", "-Wall"]

        hash1 = self.manager._hash_args(args)
        hash2 = self.manager._hash_args(args)

        self.assertEqual(hash1, hash2)

    def test_hash_args_different_order(self):
        """Test that argument order affects hash."""
        args1 = ["-std=c++17", "-O2"]
        args2 = ["-O2", "-std=c++17"]

        hash1 = self.manager._hash_args(args1)
        hash2 = self.manager._hash_args(args2)

        self.assertNotEqual(hash1, hash2)

    def test_hash_args_length(self):
        """Test that hash has expected length (full SHA-256)."""
        args = ["-std=c++17"]
        hash_value = self.manager._hash_args(args)

        # Should be 64 characters (full SHA-256 hex digest)
        self.assertEqual(len(hash_value), 64)

    def test_store_current_commands(self):
        """Test storing compilation commands."""
        commands = {"main.cpp": ["-std=c++17", "-O2"], "utils.cpp": ["-std=c++17"]}

        stored = self.manager.store_command_hashes(commands)

        self.assertEqual(stored, 2)

        # Verify stored in database
        cursor = self.conn.execute(
            """
            SELECT file_path, compile_args_hash FROM file_metadata
            WHERE file_path IN (?, ?)
        """,
            ("main.cpp", "utils.cpp"),
        )

        results = cursor.fetchall()
        self.assertEqual(len(results), 2)

        # Verify hashes are not empty and have full SHA-256 length
        for file_path, args_hash in results:
            self.assertTrue(args_hash)
            self.assertEqual(len(args_hash), 64)

    def test_get_stored_commands_hash(self):
        """Test retrieving stored command hash."""
        commands = {"main.cpp": ["-std=c++17", "-O2"]}

        self.manager.store_command_hashes(commands)

        # Get stored hash
        stored_hash = self.manager.get_stored_args_hash("main.cpp")

        # Should match what we expect
        expected_hash = self.manager._hash_args(["-std=c++17", "-O2"])
        self.assertEqual(stored_hash, expected_hash)

    def test_get_stored_commands_hash_nonexistent(self):
        """Test getting hash for file not in cache."""
        hash_value = self.manager.get_stored_args_hash("nonexistent.cpp")

        self.assertEqual(hash_value, "")

    def test_has_args_changed_same(self):
        """Test has_args_changed with same args."""
        # Store initial commands
        commands = {"main.cpp": ["-std=c++17", "-O2"]}
        self.manager.store_command_hashes(commands)

        # Check if changed (should be False)
        changed = self.manager.has_args_changed("main.cpp", ["-std=c++17", "-O2"])

        self.assertFalse(changed)

    def test_has_args_changed_different(self):
        """Test has_args_changed with different args."""
        # Store initial commands
        commands = {"main.cpp": ["-std=c++17", "-O2"]}
        self.manager.store_command_hashes(commands)

        # Check with different args (should be True)
        changed = self.manager.has_args_changed("main.cpp", ["-std=c++20", "-O3"])

        self.assertTrue(changed)

    def test_has_args_changed_new_file(self):
        """Test has_args_changed for file not in cache."""
        # Conservative: should return True for new files
        changed = self.manager.has_args_changed("new.cpp", ["-std=c++17"])

        self.assertTrue(changed)

    def test_clear_stored_commands(self):
        """Test clearing all stored commands."""
        # Store commands
        commands = {"main.cpp": ["-std=c++17"], "utils.cpp": ["-std=c++17"]}
        self.manager.store_command_hashes(commands)

        # Clear
        cleared = self.manager.clear_stored_command_hashes()

        self.assertEqual(cleared, 2)

        # Verify cleared
        cursor = self.conn.execute("""
            SELECT COUNT(*) FROM file_metadata
            WHERE compile_args_hash IS NOT NULL
        """)

        count = cursor.fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
