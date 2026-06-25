"""Database recovery operations for corrupted SQLite caches."""

import time
from pathlib import Path
from typing import Optional

from .._core import diagnostics


class RecoveryManager:
    """
    Manager for cache recovery operations.

    Provides methods to recover from various error scenarios.
    """

    @staticmethod
    def backup_database(db_path, backup_suffix: str = ".backup") -> Optional[str]:
        """
        Create a backup of the database file.

        Args:
            db_path: Path to database file
            backup_suffix: Suffix for backup file

        Returns:
            Path to backup file if successful, None otherwise
        """
        try:
            import shutil

            db_path = Path(db_path)
            if not db_path.exists():
                diagnostics.warning(f"Database file does not exist: {db_path}")
                return None

            # Create backup with timestamp
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_path = db_path.parent / f"{db_path.stem}_{timestamp}{backup_suffix}"

            shutil.copy2(db_path, backup_path)
            diagnostics.info(f"Database backup created: {backup_path}")

            return str(backup_path)

        except Exception as e:
            diagnostics.error(f"Failed to create database backup: {e}")
            return None

    @staticmethod
    def restore_from_backup(db_path, backup_path) -> bool:
        """
        Restore database from backup.

        Args:
            db_path: Path to database file
            backup_path: Path to backup file

        Returns:
            True if successful, False otherwise
        """
        try:
            import shutil

            backup_path = Path(backup_path)
            if not backup_path.exists():
                diagnostics.error(f"Backup file does not exist: {backup_path}")
                return False

            # Remove corrupted database
            db_path = Path(db_path)
            if db_path.exists():
                db_path.unlink()
                diagnostics.info(f"Removed corrupted database: {db_path}")

            # Restore from backup
            shutil.copy2(backup_path, db_path)
            diagnostics.info(f"Database restored from backup: {backup_path}")

            return True

        except Exception as e:
            diagnostics.error(f"Failed to restore from backup: {e}")
            return False

    @staticmethod
    def clear_cache(cache_dir) -> bool:
        """
        Clear all cache files (last resort recovery).

        Args:
            cache_dir: Path to cache directory

        Returns:
            True if successful, False otherwise
        """
        try:
            cache_dir = Path(cache_dir)
            if not cache_dir.exists():
                diagnostics.warning(f"Cache directory does not exist: {cache_dir}")
                return True

            # Remove SQLite database and related files
            for pattern in ["*.db", "*.db-wal", "*.db-shm", "*.backup"]:
                for file in cache_dir.glob(pattern):
                    try:
                        file.unlink()
                        diagnostics.info(f"Removed cache file: {file}")
                    except Exception as e:
                        diagnostics.warning(f"Failed to remove {file}: {e}")

            diagnostics.info(f"Cache cleared: {cache_dir}")
            return True

        except Exception as e:
            diagnostics.error(f"Failed to clear cache: {e}")
            return False

    @staticmethod
    def _check_db_integrity(conn) -> bool:
        """Run PRAGMA integrity_check and return True if database is OK."""
        cursor = conn.execute("PRAGMA integrity_check")
        results = [row[0] for row in cursor.fetchall()]
        if results == ["ok"]:
            diagnostics.info("Database integrity OK after repair attempt")
            return True
        diagnostics.warning(f"Database corruption detected: {results[:3]}")
        return False

    @staticmethod
    def _dump_schema(conn, dump_conn) -> None:
        """Copy schema (tables and indexes) from conn to dump_conn."""
        for line in conn.iterdump():
            if line.startswith("CREATE TABLE") or line.startswith("CREATE INDEX"):
                dump_conn.execute(line)

    @staticmethod
    def _copy_table_data(conn, dump_conn, table: str) -> None:
        """Attempt to copy all rows from one table into the repair database."""
        try:
            cursor = conn.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()
            if rows:
                placeholders = ",".join(["?"] * len(rows[0]))
                dump_conn.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
        except Exception as e:
            diagnostics.warning(f"Failed to copy table {table}: {e}")

    @staticmethod
    def _finalize_repair(conn, dump_conn, db_path, temp_backup) -> bool:
        """Commit, close connections, and replace original database with repaired copy."""
        dump_conn.commit()
        diagnostics.info("Partial data recovery successful")
        conn.close()
        dump_conn.close()
        db_path.unlink()
        temp_backup.rename(db_path)
        diagnostics.info("Database repair complete")
        return True

    @staticmethod
    def _cleanup_failed_repair(dump_conn, temp_backup) -> bool:
        """Close connections and remove temp file after a failed repair attempt."""
        dump_conn.close()
        if temp_backup.exists():
            temp_backup.unlink()
        return False

    @staticmethod
    def attempt_repair(db_path) -> bool:
        """
        Attempt to repair corrupted database.

        Uses SQLite's built-in recovery mechanisms:
        1. Try to dump and restore
        2. Try to open and run integrity_check
        3. Try to recover data using SQL DUMP

        Args:
            db_path: Path to database file

        Returns:
            True if repair successful, False otherwise
        """
        try:
            import sqlite3

            db_path = Path(db_path)
            if not db_path.exists():
                diagnostics.error(f"Database file does not exist: {db_path}")
                return False

            diagnostics.info(f"Attempting to repair database: {db_path}")

            conn = sqlite3.connect(str(db_path))

            if RecoveryManager._check_db_integrity(conn):
                conn.close()
                return True

            temp_backup = db_path.parent / f"{db_path.stem}_repair_temp.db"
            dump_conn = sqlite3.connect(str(temp_backup))

            try:
                RecoveryManager._dump_schema(conn, dump_conn)

                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]

                for table in tables:
                    RecoveryManager._copy_table_data(conn, dump_conn, table)

                return RecoveryManager._finalize_repair(conn, dump_conn, db_path, temp_backup)

            except Exception as e:
                diagnostics.error(f"Repair failed: {e}")
                return RecoveryManager._cleanup_failed_repair(dump_conn, temp_backup)

        except Exception as e:
            diagnostics.error(f"Failed to repair database: {e}")
            return False
