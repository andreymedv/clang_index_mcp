"""Database schema migration framework for SQLite cache."""

import sqlite3
import time
from pathlib import Path

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics


class SchemaMigration:
    """
    Manages database schema migrations.

    Provides versioned schema upgrades with:
    - Automatic version detection
    - Forward-only migrations (no downgrades)
    - Transaction-based application
    - Error handling and rollback

    Usage:
        migration = SchemaMigration(conn)
        if migration.needs_migration():
            migration.migrate()
    """

    CURRENT_VERSION = 3  # Updated for file_metadata failure tracking

    def __init__(self, conn: sqlite3.Connection):
        """
        Initialize schema migration manager.

        Args:
            conn: Active SQLite database connection
        """
        self.conn = conn
        self.migrations_dir = Path(__file__).parent / "migrations"

    def get_current_version(self) -> int:
        """
        Get current database schema version.

        Returns:
            Current version number (0 if no schema_version table exists)
        """
        try:
            cursor = self.conn.execute("SELECT MAX(version) FROM schema_version")
            version = cursor.fetchone()[0]
            return version if version is not None else 0

        except sqlite3.OperationalError:
            # schema_version table doesn't exist - brand new or very old DB
            return 0

    def needs_migration(self) -> bool:
        """
        Check if database needs migration.

        Returns:
            True if migration needed, False otherwise
        """
        current = self.get_current_version()
        return current < self.CURRENT_VERSION

    def check_version_compatibility(self) -> bool:
        """
        Check if database version is compatible with current code.

        Returns:
            True if compatible, False if database is newer than code

        Raises:
            RuntimeError: If database version is newer than supported
        """
        current = self.get_current_version()

        if current > self.CURRENT_VERSION:
            raise RuntimeError(
                f"Database schema version {current} is newer than "
                f"supported version {self.CURRENT_VERSION}. "
                f"Please update the application."
            )

        return True

    def migrate(self):
        """
        Apply pending migrations.

        Applies all migrations from current version to CURRENT_VERSION.

        Raises:
            RuntimeError: If migration fails
        """
        current = self.get_current_version()

        # Check compatibility first
        self.check_version_compatibility()

        if current >= self.CURRENT_VERSION:
            diagnostics.debug(f"Database already at version {current}, no migration needed")
            return

        diagnostics.info(f"Migrating database from version {current} to {self.CURRENT_VERSION}")

        # Apply each pending migration
        for version in range(current + 1, self.CURRENT_VERSION + 1):
            self._apply_migration(version)

        diagnostics.info("Database migration completed successfully")

    def _apply_migration(self, version: int):
        """
        Apply a single migration.

        Args:
            version: Migration version to apply

        Raises:
            FileNotFoundError: If migration file not found
            RuntimeError: If migration fails
        """
        # Find migration file
        pattern = f"{version:03d}_*.sql"
        migration_files = list(self.migrations_dir.glob(pattern))

        if not migration_files:
            raise FileNotFoundError(
                f"Migration file not found for version {version} "
                f"(searched for {pattern} in {self.migrations_dir})"
            )

        migration_file = migration_files[0]
        diagnostics.debug(f"Applying migration: {migration_file.name}")

        try:
            # Read migration SQL
            with open(migration_file, "r") as f:
                sql = f.read()

            # Check if migration was already applied (race condition protection)
            # Do this without a transaction to avoid locking issues
            cursor = self.conn.execute(
                "SELECT COUNT(*) FROM schema_version WHERE version = ?", (version,)
            )
            if cursor.fetchone()[0] > 0:
                # Another thread already applied this migration
                diagnostics.debug(f"Migration {version} already applied")
                return

            # Execute migration SQL if it contains actual statements
            # Skip only if file is empty or contains ONLY comments
            has_sql = False
            for line in sql.split("\n"):
                stripped = line.strip()
                if stripped and not stripped.startswith("--"):
                    has_sql = True
                    break

            if has_sql:
                # executescript() auto-commits and handles transactions internally
                self.conn.executescript(sql)

            # Record migration in schema_version table
            # Use INSERT OR IGNORE to handle race condition where another thread
            # might have inserted this between our check and now
            cursor = self.conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
                (version, time.time(), migration_file.stem),
            )
            self.conn.commit()

            # Check if we actually inserted it
            if cursor.rowcount > 0:
                diagnostics.debug(f"[OK] Migration {version} applied successfully")
            else:
                diagnostics.debug(f"Migration {version} was applied by another thread")

        except Exception as e:
            diagnostics.error(f"Migration {version} failed: {e}")
            raise RuntimeError(f"Migration {version} failed: {e}") from e

    def get_migration_history(self) -> list:
        """
        Get history of applied migrations.

        Returns:
            List of tuples (version, applied_at, description)
        """
        try:
            cursor = self.conn.execute(
                "SELECT version, applied_at, description FROM schema_version ORDER BY version"
            )
            return cursor.fetchall()

        except sqlite3.OperationalError:
            # No schema_version table
            return []
