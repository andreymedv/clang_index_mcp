"""Recovery port for cache management.

This port abstracts error tracking and recovery operations so that the cache
manager does not depend directly on a concrete error-tracking implementation.
"""

from pathlib import Path
from typing import Any, Protocol


class CacheRecoveryPort(Protocol):
    """Port for recording cache errors and performing recovery actions."""

    def record_operation(self, operation: str) -> None:
        """Record a successful cache operation."""
        ...

    def record_error(
        self,
        error_type: str,
        error_message: str,
        operation: str,
        recoverable: bool = True,
    ) -> bool:
        """
        Record a cache error.

        Returns True if fallback mode should be triggered.
        """
        ...

    def record_recovery(self, operation: str, attempted: bool, succeeded: bool) -> None:
        """Record the outcome of a recovery attempt (REQ-6.8.6)."""
        ...

    def mark_degraded(self, operation: str) -> None:
        """Mark a call as having ended degraded (REQ-6.8.6)."""
        ...

    def is_degraded(self, operation: str) -> bool:
        """Return True if the operation's most recent call ended degraded."""
        ...

    def get_and_clear_degraded(self, operation: str) -> bool:
        """Atomically report degraded state for the last call and clear it."""
        ...

    def last_error_for(self, operation: str) -> dict[str, Any] | None:
        """Return the most recent error state for one operation, or None."""
        ...

    def get_error_summary(self) -> dict[str, Any]:
        """Return a summary of recent errors and operations."""
        ...

    def reset(self) -> None:
        """Reset error tracking state."""
        ...

    def backup_database(self, db_path: Path, backup_suffix: str = ".backup") -> str | None:
        """Create a backup of the database file."""
        ...

    def attempt_repair(self, db_path: Path) -> bool:
        """Attempt to repair a corrupted database file."""
        ...

    def clear_cache(self, cache_dir: Path) -> bool:
        """Clear all cache files as a last-resort recovery action."""
        ...
