"""Shared mutable state container for MCP tool handlers.

Replaces the module-level globals in cpp_mcp_server.py that were accessed
via the service-locator pattern (`from .. import cpp_mcp_server as _server`).
Tool handlers now import the ``ctx`` singleton directly from this module,
breaking the dependency on the transport layer.
"""

from typing import TYPE_CHECKING

from .._persistence.session_manager import SessionManager
from .state_manager import AnalyzerStateManager

if TYPE_CHECKING:
    from ..cpp_analyzer import CppAnalyzer
    from .state_manager import BackgroundIndexer
    from .tool_call_logger import ToolCallLogger


class ToolContext:
    """Mutable container for shared MCP tool handler state."""

    def __init__(self) -> None:
        self.analyzer: CppAnalyzer | None = None
        self.state_manager: AnalyzerStateManager = AnalyzerStateManager()
        self.background_indexer: BackgroundIndexer | None = None
        self.session_manager: SessionManager = SessionManager()
        self.tool_call_logger: ToolCallLogger | None = None
        self.analyzer_initialized: bool = False


ctx = ToolContext()
