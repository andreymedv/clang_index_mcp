"""Synchronization port for the symbols/domain layer."""

from typing import Protocol


class LockProvider(Protocol):
    """Minimal lock abstraction used by the symbol index.

    Any object implementing the context-manager lock protocol is acceptable,
    e.g. threading.Lock, threading.RLock, or a multiprocessing-safe lock.
    """

    def __enter__(self) -> bool:
        """Acquire the lock."""
        ...

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Release the lock."""
        ...
