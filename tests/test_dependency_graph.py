"""Unit tests for DependencyGraphBuilder."""

import unittest
import sqlite3
import tempfile
import shutil
from pathlib import Path
from mcp_server.dependency_graph import DependencyGraphBuilder


class TestDependencyGraphBuilder(unittest.TestCase):
    """Test cases for DependencyGraphBuilder class."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = Path(tempfile.mkdtemp())
        self.db_path = self.test_dir / "test.db"
        self.conn = sqlite3.connect(str(self.db_path))

        # Create file_dependencies table
        self.conn.execute("""
            CREATE TABLE file_dependencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT NOT NULL,
                included_file TEXT NOT NULL,
                is_direct BOOLEAN NOT NULL DEFAULT 1,
                include_depth INTEGER NOT NULL DEFAULT 1,
                detected_at REAL NOT NULL,
                UNIQUE(source_file, included_file)
            )
        """)
        self.conn.execute(
            "CREATE INDEX idx_dep_source ON file_dependencies(source_file)"
        )
        self.conn.execute(
            "CREATE INDEX idx_dep_included ON file_dependencies(included_file)"
        )
        self.conn.commit()

        self.builder = DependencyGraphBuilder(self.conn)

    def tearDown(self):
        """Clean up test fixtures."""
        self.conn.close()
        shutil.rmtree(self.test_dir)

    def test_update_dependencies_simple(self):
        """Test updating dependencies for a single file."""
        source = "/project/main.cpp"
        includes = ["/project/utils.h", "/project/config.h"]

        count = self.builder.update_dependencies(source, includes)

        self.assertEqual(count, 2)

        # Verify database
        cursor = self.conn.execute("""
            SELECT included_file FROM file_dependencies
            WHERE source_file = ?
            ORDER BY included_file
        """, (source,))

        result = [row[0] for row in cursor.fetchall()]
        self.assertEqual(result, ["/project/config.h", "/project/utils.h"])

    def test_update_dependencies_replaces_old(self):
        """Test that updating dependencies replaces old ones."""
        source = "/project/main.cpp"

        # First update
        self.builder.update_dependencies(source, ["/project/old.h"])

        # Second update (should replace)
        self.builder.update_dependencies(source, ["/project/new.h"])

        # Verify only new dependency exists
        cursor = self.conn.execute("""
            SELECT included_file FROM file_dependencies
            WHERE source_file = ?
        """, (source,))

        result = [row[0] for row in cursor.fetchall()]
        self.assertEqual(result, ["/project/new.h"])

    def test_find_dependents_simple(self):
        """Test finding direct dependents of a header."""
        # Setup: main.cpp and test.cpp both include utils.h
        self.builder.update_dependencies("/project/main.cpp", ["/project/utils.h"])
        self.builder.update_dependencies("/project/test.cpp", ["/project/utils.h"])

        # Find dependents
        dependents = self.builder.find_dependents("/project/utils.h")

        self.assertEqual(len(dependents), 2)
        self.assertIn("/project/main.cpp", dependents)
        self.assertIn("/project/test.cpp", dependents)

    def test_find_dependents_no_results(self):
        """Test finding dependents when none exist."""
        dependents = self.builder.find_dependents("/project/nonexistent.h")
        self.assertEqual(len(dependents), 0)

    def test_find_transitive_dependents_chain(self):
        """Test finding transitive dependents through a chain."""
        # Setup dependency chain:
        # main.cpp → includes → utils.h → includes → config.h
        self.builder.update_dependencies("/project/main.cpp", ["/project/utils.h"])
        self.builder.update_dependencies("/project/utils.h", ["/project/config.h"])

        # When config.h changes, both utils.h and main.cpp should be affected
        dependents = self.builder.find_transitive_dependents("/project/config.h")

        self.assertEqual(len(dependents), 2)
        self.assertIn("/project/utils.h", dependents)
        self.assertIn("/project/main.cpp", dependents)

    def test_find_transitive_dependents_multiple_paths(self):
        """Test finding transitive dependents with multiple paths."""
        # Setup:
        # main.cpp → utils.h → config.h
        # test.cpp → config.h (direct)
        self.builder.update_dependencies("/project/main.cpp", ["/project/utils.h"])
        self.builder.update_dependencies("/project/utils.h", ["/project/config.h"])
        self.builder.update_dependencies("/project/test.cpp", ["/project/config.h"])

        # All three files should be affected by config.h change
        dependents = self.builder.find_transitive_dependents("/project/config.h")

        self.assertEqual(len(dependents), 3)
        self.assertIn("/project/main.cpp", dependents)
        self.assertIn("/project/utils.h", dependents)
        self.assertIn("/project/test.cpp", dependents)

    def test_find_transitive_dependents_circular(self):
        """Test handling circular dependencies."""
        # Setup circular dependency (via header guards):
        # a.h → b.h → c.h → a.h
        self.builder.update_dependencies("/project/a.h", ["/project/b.h"])
        self.builder.update_dependencies("/project/b.h", ["/project/c.h"])
        self.builder.update_dependencies("/project/c.h", ["/project/a.h"])

        # Should not infinite loop, should return all files
        dependents = self.builder.find_transitive_dependents("/project/a.h")

        # All three headers should be in the result
        self.assertEqual(len(dependents), 3)
        self.assertIn("/project/a.h", dependents)
        self.assertIn("/project/b.h", dependents)
        self.assertIn("/project/c.h", dependents)

    def test_remove_file_dependencies(self):
        """Test removing all dependencies for a file."""
        source = "/project/main.cpp"
        includes = ["/project/utils.h", "/project/config.h"]

        # Add dependencies
        self.builder.update_dependencies(source, includes)

        # Also add dependency where main.cpp is included
        self.builder.update_dependencies("/project/other.cpp", [source])

        # Remove all dependencies for main.cpp
        removed = self.builder.remove_file_dependencies(source)

        # Should remove 3 records:
        # - main.cpp → utils.h
        # - main.cpp → config.h
        # - other.cpp → main.cpp
        self.assertEqual(removed, 3)

        # Verify no dependencies remain
        cursor = self.conn.execute("""
            SELECT COUNT(*) FROM file_dependencies
            WHERE source_file = ? OR included_file = ?
        """, (source, source))

        self.assertEqual(cursor.fetchone()[0], 0)

    def test_get_dependency_stats_empty(self):
        """Test getting stats from empty dependency graph."""
        stats = self.builder.get_dependency_stats()

        self.assertEqual(stats["total_dependencies"], 0)
        self.assertEqual(stats["unique_source_files"], 0)
        self.assertEqual(stats["unique_included_files"], 0)
        self.assertEqual(stats["avg_includes_per_file"], 0.0)

    def test_get_dependency_stats_populated(self):
        """Test getting stats from populated dependency graph."""
        # Setup: 2 source files with varying includes
        self.builder.update_dependencies(
            "/project/main.cpp",
            ["/project/a.h", "/project/b.h", "/project/c.h"]
        )
        self.builder.update_dependencies(
            "/project/test.cpp",
            ["/project/a.h"]
        )

        stats = self.builder.get_dependency_stats()

        self.assertEqual(stats["total_dependencies"], 4)
        self.assertEqual(stats["unique_source_files"], 2)
        self.assertEqual(stats["unique_included_files"], 3)
        self.assertEqual(stats["avg_includes_per_file"], 2.0)

    def test_get_include_count(self):
        """Test getting include count for a file."""
        source = "/project/main.cpp"
        includes = ["/project/a.h", "/project/b.h", "/project/c.h"]

        self.builder.update_dependencies(source, includes)

        count = self.builder.get_include_count(source)
        self.assertEqual(count, 3)

    def test_get_include_count_nonexistent(self):
        """Test getting include count for file with no includes."""
        count = self.builder.get_include_count("/project/nonexistent.cpp")
        self.assertEqual(count, 0)

    def test_clear_all_dependencies(self):
        """Test clearing all dependencies."""
        # Setup some dependencies
        self.builder.update_dependencies("/project/main.cpp", ["/project/a.h"])
        self.builder.update_dependencies("/project/test.cpp", ["/project/b.h"])

        # Clear all
        cleared = self.builder.clear_all_dependencies()
        self.assertEqual(cleared, 2)

        # Verify empty
        stats = self.builder.get_dependency_stats()
        self.assertEqual(stats["total_dependencies"], 0)

    def test_update_dependencies_with_duplicates(self):
        """Test that duplicate includes are handled correctly."""
        source = "/project/main.cpp"
        includes = ["/project/a.h", "/project/a.h", "/project/b.h"]

        # Should only insert unique dependencies
        count = self.builder.update_dependencies(source, includes)

        # Should insert 2 (a.h once, b.h once)
        self.assertEqual(count, 2)

        # Verify database
        cursor = self.conn.execute("""
            SELECT COUNT(*) FROM file_dependencies WHERE source_file = ?
        """, (source,))

        self.assertEqual(cursor.fetchone()[0], 2)

    def test_dependency_persistence(self):
        """Test that dependencies persist across builder instances."""
        source = "/project/main.cpp"
        includes = ["/project/a.h", "/project/b.h"]

        # Update with first builder
        self.builder.update_dependencies(source, includes)

        # Create new builder with same connection
        builder2 = DependencyGraphBuilder(self.conn)

        # Should be able to query dependencies
        dependents = builder2.find_dependents("/project/a.h")
        self.assertIn(source, dependents)


if __name__ == '__main__':
    unittest.main()
