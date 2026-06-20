"""Shared DTO for indexing/refresh callback pairs."""

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class IndexingCallbacks:
    """Progress and tool-availability callbacks forwarded through indexing layers."""

    progress: Optional[Callable[[Any], None]] = None
    wait_for_tools: Optional[Callable[..., Any]] = None
