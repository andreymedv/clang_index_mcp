"""
Concurrency context for C++ Analyzer.

Manages locking strategy and thread-local buffers for parallel indexing.
The lock choice (real RLock vs no-op) is determined by the _needs_locking
flag, and thread-local buffers exist to minimize lock contention.
"""

import threading
from typing import Any, List, Tuple


class _NoOpLock:
    """A no-op context manager that doesn't actually acquire any lock."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class ConcurrencyContext:
    """Manages synchronization primitives and thread-local state for parallel indexing."""

    def __init__(self, needs_locking: bool = True):
        self.index_lock = threading.RLock()
        self._no_op_lock = _NoOpLock()
        self._needs_locking = needs_locking
        self._thread_local = threading.local()

    def get_lock(self):
        """
        Return appropriate lock based on execution context.

        Returns index_lock when locks are needed (ThreadPoolExecutor or shared instance),
        or a no-op lock when locks are unnecessary (ProcessPoolExecutor worker).
        """
        return self.index_lock if self._needs_locking else self._no_op_lock

    def init_thread_local_buffers(self):
        """Initialize thread-local buffers for collecting symbols during parsing."""
        self._thread_local.collected_symbols: List[Any] = []
        self._thread_local.collected_calls: List[Any] = []
        self._thread_local.collected_aliases: List[Any] = []

    def get_thread_local_buffers(self) -> Tuple[List[Any], List[Any], List[Any]]:
        """Get thread-local buffers, initializing if needed."""
        if not hasattr(self._thread_local, "collected_symbols"):
            self.init_thread_local_buffers()
        return (
            self._thread_local.collected_symbols,
            self._thread_local.collected_calls,
            self._thread_local.collected_aliases,
        )
