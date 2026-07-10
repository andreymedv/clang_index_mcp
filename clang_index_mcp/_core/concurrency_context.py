"""Concurrency context for C++ Analyzer.

Holds the main-process index lock. Worker processes each have their own
instance; thread-local buffers are no longer used because indexing workers
are single-threaded subprocesses.
"""

import threading


class ConcurrencyContext:
    """Manages the shared index lock for main-process concurrency."""

    def __init__(self):
        self.index_lock = threading.RLock()

    def get_lock(self):
        """Return the shared index lock."""
        return self.index_lock
