"""Shared DTO for indexing/refresh callback pairs."""

from dataclasses import dataclass
from typing import Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .._mcp.state_manager import AnalyzerStateManager


@dataclass
class IndexingCallbacks:
    """Progress and tool-availability callbacks forwarded through indexing layers."""

    progress: Optional[Callable[[Any], None]] = None
    wait_for_tools: Optional[Callable[..., Any]] = None

    @classmethod
    def from_state_manager(cls, state_manager: "AnalyzerStateManager") -> "IndexingCallbacks":
        """Build callbacks that report progress and tool waits into a state manager."""

        def progress_callback(progress: Any) -> None:
            """Callback to update progress in state manager."""
            state_manager.update_progress(progress)

        return cls(
            progress=progress_callback,
            wait_for_tools=state_manager.wait_for_tools_to_finish,
        )
