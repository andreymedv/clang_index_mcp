"""Adapter implementing the cache recovery port with concrete error tracking."""

from pathlib import Path
from typing import Any, Dict, Optional, Union

from .._core.error_tracking import ErrorTracker
from .._persistence.recovery import RecoveryManager
from .._persistence.ports.recovery import CacheRecoveryPort


class ErrorTrackingAdapter:
    """Adapter that exposes ErrorTracker + RecoveryManager as CacheRecoveryPort."""

    def __init__(
        self,
        error_tracker: Optional[ErrorTracker] = None,
        recovery_manager: Optional[RecoveryManager] = None,
    ):
        self._error_tracker = error_tracker or ErrorTracker()
        self._recovery_manager = recovery_manager or RecoveryManager()

    def record_operation(self, operation: str) -> None:
        self._error_tracker.record_operation(operation)

    def record_error(
        self,
        error_type: str,
        error_message: str,
        operation: str,
        recoverable: bool = True,
    ) -> bool:
        return self._error_tracker.record_error(error_type, error_message, operation, recoverable)

    def get_error_summary(self) -> Dict[str, Any]:
        return self._error_tracker.get_error_summary()

    def reset(self) -> None:
        self._error_tracker.reset()

    def backup_database(
        self, db_path: Union[str, Path], backup_suffix: str = ".backup"
    ) -> Optional[str]:
        return self._recovery_manager.backup_database(db_path, backup_suffix)

    def attempt_repair(self, db_path: Union[str, Path]) -> bool:
        return self._recovery_manager.attempt_repair(db_path)

    def clear_cache(self, cache_dir: Union[str, Path]) -> bool:
        return self._recovery_manager.clear_cache(cache_dir)


# Re-export for typing convenience
CacheRecoveryPort.register(ErrorTrackingAdapter)
