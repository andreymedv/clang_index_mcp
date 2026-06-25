"""
Concurrency context for C++ Analyzer.

Manages locking strategy and thread-local buffers for parallel indexing.
Thread-local buffers exist to minimize lock contention during AST traversal;
the shared index lock is used only when merging collected results back into
the main process indexes.
"""

import threading
from typing import Any, List, Tuple


class ConcurrencyContext:
    """Manages synchronization primitives and thread-local state for parallel indexing."""

    def __init__(self):
        self.index_lock = threading.RLock()
        self._thread_local = threading.local()

    def get_lock(self):
        """Return the shared index lock."""
        return self.index_lock

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
