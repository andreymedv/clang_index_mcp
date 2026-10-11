"""Error tracking and monitoring for cache operations.

Implements the error-state channel (REQ-6.8.6): per-operation counters, the most
recent backend error, and per-operation-class degraded flags so callers can
distinguish an empty result from a degraded one.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Literal

# Handle both package and script imports
try:
    from .._core import diagnostics
except ImportError:
    import diagnostics  # type: ignore[no-redef]

OperationClass = Literal["read", "write"]

# Operation names starting with these prefixes persist state and belong to the
# "write" class; everything else is a "read" (decision D3: per class, not global).
_WRITE_PREFIXES = ("save_", "remove_", "ensure_", "write_", "delete_", "clear_", "set_")


def operation_class(operation: str) -> OperationClass:
    """Map an operation name to its degradation class ("read" or "write")."""
    return "write" if operation.startswith(_WRITE_PREFIXES) else "read"


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

    Implements error rate monitoring and automatic fallback logic, plus the
    error-state channel consumed by cache wrappers and tool handlers.

    Thread safety:
        All public methods are guarded by a single reentrant lock and may be
        called concurrently from indexing, writer, and query threads.
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

        self._lock = threading.RLock()

        # Error history (time-windowed)
        self.error_history: deque[ErrorRecord] = deque(maxlen=1000)

        # Operation counters
        self.operation_counts: dict[str, int] = {}
        self.error_counts: dict[str, int] = {}
        self.consecutive_errors: dict[str, int] = {}

        # Error-state channel (REQ-6.8.6)
        self._last_error: dict[str, Any] | None = None
        self._last_error_by_operation: dict[str, dict[str, Any]] = {}
        self._degraded_operations: set[str] = set()
        self._degraded_classes: dict[str, bool] = {"read": False, "write": False}

        # Recovery outcome tracking (last outcome plus totals)
        self.recovery_attempted: bool = False
        self.recovery_succeeded: bool = False
        self.recovery_attempts: int = 0
        self.recovery_successes: int = 0

        # Fallback state
        self.fallback_triggered = False
        self.fallback_reason: str | None = None

    def record_operation(self, operation: str):
        """
        Record a successful operation.

        A success resets the operation's consecutive-error counter and clears its
        degraded marking (including the operation class when no other degraded
        operation remains in that class).

        Args:
            operation: Operation name (e.g., 'save_symbol', 'load_cache')
        """
        with self._lock:
            self.operation_counts[operation] = self.operation_counts.get(operation, 0) + 1
            self.consecutive_errors[operation] = 0
            self._degraded_operations.discard(operation)
            self._refresh_class_flags()

    def record_error(
        self, error_type: str, error_message: str, operation: str, recoverable: bool = True
    ) -> bool:
        """
        Record an error occurrence and mark the operation as degraded.

        Args:
            error_type: Type of error (e.g., 'DatabaseLocked', 'Corruption')
            error_message: Error message
            operation: Operation that failed
            recoverable: Whether the error is recoverable

        Returns:
            True if fallback should be triggered, False otherwise
        """
        with self._lock:
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
            self.consecutive_errors[operation] = self.consecutive_errors.get(operation, 0) + 1

            error_state = {
                "operation": operation,
                "error_type": error_type,
                "message": error_message,
                "timestamp": record.timestamp,
            }
            self._last_error = error_state
            self._last_error_by_operation[operation] = error_state

            # The failed call "just ended degraded" for its operation and class.
            self._degraded_operations.add(operation)
            self._refresh_class_flags()

            # Check if fallback should be triggered
            should_fallback = False
            if not self.fallback_triggered:
                should_fallback = self._should_trigger_fallback()
                if should_fallback:
                    self._trigger_fallback(f"Error rate threshold exceeded: {error_type}")

        # Log outside the lock: a logging failure must not corrupt tracking state
        if recoverable:
            diagnostics.warning(f"Recoverable error in {operation}: {error_type}: {error_message}")
        else:
            diagnostics.error(
                f"Non-recoverable error in {operation}: {error_type}: {error_message}"
            )

        return should_fallback

    def mark_degraded(self, operation: str) -> None:
        """
        Explicitly mark a call as having ended degraded (REQ-6.8.6).

        Wrappers call this when a backend call failed and the safe value they
        return must not be read as a truthful "not found" / "empty" result.
        """
        with self._lock:
            self._degraded_operations.add(operation)
            self._refresh_class_flags()

    def is_degraded(self, operation: str) -> bool:
        """
        Return True if the operation's most recent call ended degraded.

        True when this operation is marked degraded or when its operation class
        (read/write) is currently degraded.
        """
        with self._lock:
            return (
                operation in self._degraded_operations
                or self._degraded_classes[operation_class(operation)]
            )

    def get_and_clear_degraded(self, operation: str) -> bool:
        """
        Atomically report whether the operation just ended degraded, and clear
        the per-operation marking so the next successful call reports False.

        This avoids check-then-act races for tool handlers that must decide
        between "not found" and "unavailable" right after a cache call.
        """
        with self._lock:
            degraded = (
                operation in self._degraded_operations
                or self._degraded_classes[operation_class(operation)]
            )
            self._degraded_operations.discard(operation)
            self._refresh_class_flags()
            return degraded

    def last_error_for(self, operation: str) -> dict[str, Any] | None:
        """Return the most recent error state for one operation, or None."""
        with self._lock:
            record = self._last_error_by_operation.get(operation)
            return dict(record) if record is not None else None

    def record_recovery(self, operation: str, attempted: bool, succeeded: bool) -> None:
        """
        Record the outcome of a recovery attempt (last outcome plus totals).

        Args:
            operation: Operation whose failure triggered recovery
            attempted: Whether recovery was attempted at all
            succeeded: Whether the attempted recovery succeeded
        """
        with self._lock:
            self.recovery_attempted = attempted
            self.recovery_succeeded = succeeded
            if attempted:
                self.recovery_attempts += 1
            if succeeded:
                self.recovery_successes += 1

    def _refresh_class_flags(self) -> None:
        """Recompute per-class degraded flags from the degraded operation set."""
        for cls in ("read", "write"):
            self._degraded_classes[cls] = any(
                operation_class(op) == cls for op in self._degraded_operations
            )

    def _get_recent_errors(self) -> tuple[list[ErrorRecord], int]:
        """Get recent errors within the time window and total operation count.

        Returns:
            Tuple of (recent_errors list, recent_operations count)
        """
        now = time.time()
        cutoff = now - self.window_seconds
        recent_errors = [e for e in self.error_history if e.timestamp >= cutoff]
        recent_operations = sum(self.operation_counts.values())
        return recent_errors, recent_operations

    def _should_trigger_fallback(self) -> bool:
        """
        Check if fallback should be triggered based on error rate.

        Returns:
            True if fallback should be triggered, False otherwise
        """
        recent_errors, recent_operations = self._get_recent_errors()

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
        with self._lock:
            recent_errors, recent_operations = self._get_recent_errors()

            if recent_operations == 0:
                return 0.0

            return len(recent_errors) / recent_operations

    def get_error_summary(self) -> dict[str, Any]:
        """
        Get summary of errors (additive error-state channel fields included).

        Returns:
            Dict with error statistics, per-operation counters, the most recent
            error state, degraded flags per operation class, and recovery outcome
        """
        with self._lock:
            recent_errors, _ = self._get_recent_errors()

            # Count by error type
            error_by_type: dict[str, int] = {}
            for error in recent_errors:
                error_by_type[error.error_type] = error_by_type.get(error.error_type, 0) + 1

            # Count by operation
            error_by_operation: dict[str, int] = {}
            for error in recent_errors:
                error_by_operation[error.operation] = error_by_operation.get(error.operation, 0) + 1

            # Per-operation counters (operations, errors, consecutive_errors)
            per_operation: dict[str, dict[str, int]] = {}
            for op in (
                set(self.operation_counts) | set(self.error_counts) | set(self.consecutive_errors)
            ):
                per_operation[op] = {
                    "operations": self.operation_counts.get(op, 0),
                    "errors": self.error_counts.get(op, 0),
                    "consecutive_errors": self.consecutive_errors.get(op, 0),
                }

            return {
                "total_errors": len(recent_errors),
                "total_operations": sum(self.operation_counts.values()),
                "error_rate": self.get_error_rate(),
                "errors_by_type": error_by_type,
                "errors_by_operation": error_by_operation,
                "fallback_triggered": self.fallback_triggered,
                "fallback_reason": self.fallback_reason,
                "window_seconds": self.window_seconds,
                # Error-state channel (REQ-6.8.6), additive keys only
                "per_operation": per_operation,
                "last_error": dict(self._last_error) if self._last_error else None,
                "degraded": dict(self._degraded_classes),
                "recovery_attempted": self.recovery_attempted,
                "recovery_succeeded": self.recovery_succeeded,
                "recovery_attempts": self.recovery_attempts,
                "recovery_successes": self.recovery_successes,
            }

    def reset(self):
        """Reset error tracker state."""
        with self._lock:
            self.error_history.clear()
            self.operation_counts.clear()
            self.error_counts.clear()
            self.consecutive_errors.clear()
            self._last_error = None
            self._last_error_by_operation.clear()
            self._degraded_operations.clear()
            self._degraded_classes = {"read": False, "write": False}
            self.recovery_attempted = False
            self.recovery_succeeded = False
            self.recovery_attempts = 0
            self.recovery_successes = 0
            self.fallback_triggered = False
            self.fallback_reason = None
