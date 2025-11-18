"""Unit tests for database schema migration."""

import unittest
import sqlite3
import tempfile
import shutil
from pathlib import Path
from mcp_server.schema_migrations import SchemaMigration


class TestSchemaMigration(unittest.TestCase):
    """Test cases for schema migration system."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = Path(tempfile.mkdtemp())
        self.db_path = self.test_dir / "test.db"

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir)

    def test_fresh_database_initialization(self):
        """Test migration on fresh database."""
        # Create fresh database with initial schema
        conn = sqlite3.connect(str(self.db_path))

        # Create schema_version table (normally created by schema.sql)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at REAL NOT NULL,
                description TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO schema_version (version, applied_at, description)
            VALUES (1, julianday('now'), 'Initial schema')
        """)
        conn.commit()

        # Run migration
        migration = SchemaMigration(conn)
        self.assertTrue(migration.needs_migration())
        self.assertEqual(migration.get_current_version(), 1)

        migration.migrate()

        # Verify migration applied
        self.assertFalse(migration.needs_migration())
        self.assertEqual(migration.get_current_version(), 2)

        # Verify file_dependencies table exists
        cursor = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='file_dependencies'
        """)
        tables = cursor.fetchall()
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0][0], 'file_dependencies')

        # Verify indexes exist
        cursor = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND tbl_name='file_dependencies'
        """)
        indexes = cursor.fetchall()
        index_names = {row[0] for row in indexes}

        expected_indexes = {
            'idx_dep_source',
            'idx_dep_included',
            'idx_dep_direct',
            'idx_dep_detected'
        }

        self.assertTrue(expected_indexes.issubset(index_names))

        conn.close()

    def test_migration_idempotence(self):
        """Test that running migration multiple times is safe."""
        conn = sqlite3.connect(str(self.db_path))

        # Create schema_version table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at REAL NOT NULL,
                description TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO schema_version (version, applied_at, description)
            VALUES (1, julianday('now'), 'Initial schema')
        """)
        conn.commit()

        # First migration
        migration = SchemaMigration(conn)
        migration.migrate()
        self.assertEqual(migration.get_current_version(), 2)

        # Second migration (should be no-op)
        migration2 = SchemaMigration(conn)
        self.assertFalse(migration2.needs_migration())
        migration2.migrate()  # Should not raise error
        self.assertEqual(migration2.get_current_version(), 2)

        conn.close()

    def test_file_dependencies_table_structure(self):
        """Test that file_dependencies table has correct structure."""
        conn = sqlite3.connect(str(self.db_path))

        # Create schema_version table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at REAL NOT NULL,
                description TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO schema_version (version, applied_at, description)
            VALUES (1, julianday('now'), 'Initial schema')
        """)
        conn.commit()

        # Apply migration
        migration = SchemaMigration(conn)
        migration.migrate()

        # Get table info
        cursor = conn.execute("PRAGMA table_info(file_dependencies)")
        columns = cursor.fetchall()

        # Verify columns
        column_names = {col[1] for col in columns}
        expected_columns = {
            'id', 'source_file', 'included_file',
            'is_direct', 'include_depth', 'detected_at'
        }

        self.assertEqual(column_names, expected_columns)

        conn.close()

    def test_file_dependencies_unique_constraint(self):
        """Test that unique constraint on (source_file, included_file) works."""
        conn = sqlite3.connect(str(self.db_path))

        # Create schema_version and migrate
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at REAL NOT NULL,
                description TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO schema_version (version, applied_at, description)
            VALUES (1, julianday('now'), 'Initial schema')
        """)
        conn.commit()

        migration = SchemaMigration(conn)
        migration.migrate()

        # Insert first dependency
        conn.execute("""
            INSERT INTO file_dependencies
            (source_file, included_file, detected_at)
            VALUES ('main.cpp', 'header.h', 12345.0)
        """)
        conn.commit()

        # Try to insert duplicate (should fail)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("""
                INSERT INTO file_dependencies
                (source_file, included_file, detected_at)
                VALUES ('main.cpp', 'header.h', 12346.0)
            """)
            conn.commit()

        conn.close()

    def test_migration_history(self):
        """Test migration history tracking."""
        conn = sqlite3.connect(str(self.db_path))

        # Create schema_version table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at REAL NOT NULL,
                description TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO schema_version (version, applied_at, description)
            VALUES (1, julianday('now'), 'Initial schema')
        """)
        conn.commit()

        # Apply migration
        migration = SchemaMigration(conn)
        migration.migrate()

        # Get history
        history = migration.get_migration_history()

        # Should have 2 entries: version 1 (initial) and version 2 (new migration)
        self.assertEqual(len(history), 2)

        # Check versions
        versions = [h[0] for h in history]
        self.assertEqual(versions, [1, 2])

        # Check that migration 2 has description
        migration_2 = [h for h in history if h[0] == 2][0]
        self.assertIn('002', migration_2[2])  # Description should contain '002'

        conn.close()


if __name__ == '__main__':
    unittest.main()
