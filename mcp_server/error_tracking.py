"""Error tracking and monitoring for cache operations."""

import time
from typing import Dict, List, Optional
from collections import deque
from dataclasses import dataclass, field

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics


@dataclass
class ErrorRecord:
    """Record of an error occurrence."""
    timestamp: float
    error_type: str
    error_message: str
    operation: str
    recoverable: bool


class ErrorTracker:
    """
    Track and monitor errors for cache operations.

    Implements error rate monitoring and automatic fallback logic.
    """

    def __init__(self, window_seconds: float = 300.0, fallback_threshold: float = 0.05):
        """
        Initialize error tracker.

        Args:
            window_seconds: Time window for error rate calculation (default: 5 minutes)
            fallback_threshold: Error rate threshold for automatic fallback (default: 5%)
        """
        self.window_seconds = window_seconds
        self.fallback_threshold = fallback_threshold

        # Error history (time-windowed)
        self.error_history: deque[ErrorRecord] = deque(maxlen=1000)

        # Operation counters
        self.operation_counts: Dict[str, int] = {}
        self.error_counts: Dict[str, int] = {}

        # Fallback state
        self.fallback_triggered = False
        self.fallback_reason: Optional[str] = None

    def record_operation(self, operation: str):
        """
        Record a successful operation.

        Args:
            operation: Operation name (e.g., 'save_symbol', 'load_cache')
        """
        self.operation_counts[operation] = self.operation_counts.get(operation, 0) + 1

    def record_error(self, error_type: str, error_message: str,
                    operation: str, recoverable: bool = True) -> bool:
        """
        Record an error occurrence.

        Args:
            error_type: Type of error (e.g., 'DatabaseLocked', 'Corruption')
            error_message: Error message
            operation: Operation that failed
            recoverable: Whether the error is recoverable

        Returns:
            True if fallback should be triggered, False otherwise
        """
        # Create error record
        record = ErrorRecord(
            timestamp=time.time(),
            error_type=error_type,
            error_message=error_message,
            operation=operation,
            recoverable=recoverable
        )

        self.error_history.append(record)
        self.error_counts[operation] = self.error_counts.get(operation, 0) + 1

        # Log error
        if recoverable:
            diagnostics.warning(
                f"Recoverable error in {operation}: {error_type}: {error_message}"
            )
        else:
            diagnostics.error(
                f"Non-recoverable error in {operation}: {error_type}: {error_message}"
            )

        # Check if fallback should be triggered
        if not self.fallback_triggered:
            should_fallback = self._should_trigger_fallback()
            if should_fallback:
                self._trigger_fallback(f"Error rate threshold exceeded: {error_type}")
                return True

        return False

    def _should_trigger_fallback(self) -> bool:
        """
        Check if fallback should be triggered based on error rate.

        Returns:
            True if fallback should be triggered, False otherwise
        """
        # Remove old errors outside the time window
        now = time.time()
        cutoff = now - self.window_seconds

        # Count errors and operations in window
        recent_errors = [e for e in self.error_history if e.timestamp >= cutoff]
        recent_operations = sum(self.operation_counts.values())

        if recent_operations == 0:
            return False

        error_rate = len(recent_errors) / recent_operations

        # Trigger fallback if error rate exceeds threshold
        if error_rate >= self.fallback_threshold:
            diagnostics.warning(
                f"Error rate {error_rate:.1%} exceeds threshold {self.fallback_threshold:.1%} "
                f"({len(recent_errors)} errors / {recent_operations} operations)"
            )
            return True

        return False

    def _trigger_fallback(self, reason: str):
        """
        Trigger fallback to JSON backend.

        Args:
            reason: Reason for fallback
        """
        self.fallback_triggered = True
        self.fallback_reason = reason
        diagnostics.error(f"Triggering fallback to JSON backend: {reason}")

    def get_error_rate(self) -> float:
        """
        Get current error rate within the time window.

        Returns:
            Error rate (0.0 to 1.0)
        """
        now = time.time()
        cutoff = now - self.window_seconds

        recent_errors = [e for e in self.error_history if e.timestamp >= cutoff]
        recent_operations = sum(self.operation_counts.values())

        if recent_operations == 0:
            return 0.0

        return len(recent_errors) / recent_operations

    def get_error_summary(self) -> Dict[str, any]:
        """
        Get summary of errors.

        Returns:
            Dict with error statistics
        """
        now = time.time()
        cutoff = now - self.window_seconds

        recent_errors = [e for e in self.error_history if e.timestamp >= cutoff]

        # Count by error type
        error_by_type: Dict[str, int] = {}
        for error in recent_errors:
            error_by_type[error.error_type] = error_by_type.get(error.error_type, 0) + 1

        # Count by operation
        error_by_operation: Dict[str, int] = {}
        for error in recent_errors:
            error_by_operation[error.operation] = error_by_operation.get(error.operation, 0) + 1

        return {
            'total_errors': len(recent_errors),
            'total_operations': sum(self.operation_counts.values()),
            'error_rate': self.get_error_rate(),
            'errors_by_type': error_by_type,
            'errors_by_operation': error_by_operation,
            'fallback_triggered': self.fallback_triggered,
            'fallback_reason': self.fallback_reason,
            'window_seconds': self.window_seconds
        }

    def reset(self):
        """Reset error tracker state."""
        self.error_history.clear()
        self.operation_counts.clear()
        self.error_counts.clear()
        self.fallback_triggered = False
        self.fallback_reason = None


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
            from pathlib import Path

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
            from pathlib import Path

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
            import shutil
            from pathlib import Path

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
            from pathlib import Path

            db_path = Path(db_path)
            if not db_path.exists():
                diagnostics.error(f"Database file does not exist: {db_path}")
                return False

            diagnostics.info(f"Attempting to repair database: {db_path}")

            # Try to open database
            conn = sqlite3.connect(str(db_path))

            # Run integrity check
            cursor = conn.execute("PRAGMA integrity_check")
            results = [row[0] for row in cursor.fetchall()]

            if results == ['ok']:
                diagnostics.info("Database integrity OK after repair attempt")
                conn.close()
                return True

            # Try to recover by dumping and recreating
            diagnostics.warning(f"Database corruption detected: {results[:3]}")

            # Create temporary backup
            temp_backup = db_path.parent / f"{db_path.stem}_repair_temp.db"

            # Try to dump recoverable data
            dump_conn = sqlite3.connect(str(temp_backup))

            try:
                # Copy schema
                for line in conn.iterdump():
                    if line.startswith('CREATE TABLE') or line.startswith('CREATE INDEX'):
                        dump_conn.execute(line)

                # Try to copy data (may fail on corrupted rows)
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]

                for table in tables:
                    try:
                        cursor = conn.execute(f"SELECT * FROM {table}")
                        # This may fail on corrupted rows
                        rows = cursor.fetchall()
                        if rows:
                            placeholders = ','.join(['?'] * len(rows[0]))
                            dump_conn.executemany(
                                f"INSERT INTO {table} VALUES ({placeholders})",
                                rows
                            )
                    except Exception as e:
                        diagnostics.warning(f"Failed to copy table {table}: {e}")

                dump_conn.commit()
                diagnostics.info("Partial data recovery successful")

                # Close connections
                conn.close()
                dump_conn.close()

                # Replace original with repaired
                db_path.unlink()
                temp_backup.rename(db_path)

                diagnostics.info("Database repair complete")
                return True

            except Exception as e:
                diagnostics.error(f"Repair failed: {e}")
                dump_conn.close()
                if temp_backup.exists():
                    temp_backup.unlink()
                return False

        except Exception as e:
            diagnostics.error(f"Failed to repair database: {e}")
            return False
