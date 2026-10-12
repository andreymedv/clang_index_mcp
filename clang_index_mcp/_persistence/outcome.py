"""Typed outcome contract for cache backend calls (REQ-6.8.5).

`BackendOutcome[T]` separates a legitimate domain value (including None for
"not found") from a backend error, so callers never have to guess whether a
None return means empty or failed.
"""

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class BackendOutcome(Generic[T]):
    """Result of a wrapped backend call.

    Attributes:
        value: Backend return value. Present when ``ok`` is True; may be None
            for methods whose domain includes "not found".
        error: Exception raised by the backend (or by failure handling). Present
            when ``ok`` is False.
        recovered: True only when recovery succeeded and the retried call also
            succeeded (REQ-6.8.5).
    """

    value: T | None = None
    error: Exception | None = None
    recovered: bool = False

    @property
    def ok(self) -> bool:
        """True when the call completed without error (value may still be None)."""
        return self.error is None
