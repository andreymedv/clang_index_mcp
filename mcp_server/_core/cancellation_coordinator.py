"""
Cancellation coordinator for C++ Analyzer indexing operations.

Provides cooperative cancellation: a flag protected by a lock,
checked periodically by indexing loops.
"""

import threading

from .._core import diagnostics


class CancellationCoordinator:
    """Manages cooperative cancellation of long-running indexing operations."""

    def __init__(self):
        self._interrupted: bool = False
        self._interrupt_lock = threading.Lock()

    def interrupt(self):
        """Request cancellation of ongoing indexing."""
        with self._interrupt_lock:
            self._interrupted = True
        diagnostics.info("Indexing interrupt requested")

    def is_interrupted(self) -> bool:
        """Check if indexing has been interrupted."""
        with self._interrupt_lock:
            return self._interrupted

    def reset(self):
        """Clear the interrupt flag for a new indexing run."""
        with self._interrupt_lock:
            self._interrupted = False
