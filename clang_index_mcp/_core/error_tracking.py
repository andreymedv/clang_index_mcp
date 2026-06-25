"""Error tracking and monitoring for cache operations."""

import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, Optional

# Handle both package and script imports
try:
    from .._core import diagnostics
except ImportError:
    import diagnostics  # type: ignore[no-redef]


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

    def record_error(
        self, error_type: str, error_message: str, operation: str, recoverable: bool = True
    ) -> bool:
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
            recoverable=recoverable,
        )

        self.error_history.append(record)
        self.error_counts[operation] = self.error_counts.get(operation, 0) + 1

        # Log error
        if recoverable:
            diagnostics.warning(f"Recoverable error in {operation}: {error_type}: {error_message}")
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
        Trigger fallback mode due to high error rate.

        Args:
            reason: Reason for fallback
        """
        self.fallback_triggered = True
        self.fallback_reason = reason
        diagnostics.error(f"Triggering fallback mode: {reason}")

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

    def get_error_summary(self) -> Dict[str, Any]:
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
            "total_errors": len(recent_errors),
            "total_operations": sum(self.operation_counts.values()),
            "error_rate": self.get_error_rate(),
            "errors_by_type": error_by_type,
            "errors_by_operation": error_by_operation,
            "fallback_triggered": self.fallback_triggered,
            "fallback_reason": self.fallback_reason,
            "window_seconds": self.window_seconds,
        }

    def reset(self):
        """Reset error tracker state."""
        self.error_history.clear()
        self.operation_counts.clear()
        self.error_counts.clear()
        self.fallback_triggered = False
        self.fallback_reason = None
