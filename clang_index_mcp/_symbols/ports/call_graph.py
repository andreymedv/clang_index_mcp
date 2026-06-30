"""Call graph port used by the symbol store during indexing and maintenance."""

from typing import List, Protocol

from ..._symbols.model import SymbolInfo
from .parser import CallSiteRecord


class CallGraphPort(Protocol):
    """Minimal interface the symbol store needs from the call graph subsystem."""

    def remove_symbol(self, usr: str) -> None:
        """Remove all call sites involving the given USR."""
        ...

    def clear(self) -> None:
        """Clear transient in-memory call graph data."""
        ...

    def rebuild_from_symbols(self, symbols: List[SymbolInfo]) -> None:
        """Rebuild call graph state from a list of symbols (may be a no-op)."""
        ...

    def process_call_buffer(self, calls_buffer: List[CallSiteRecord]) -> None:
        """Add buffered call records to the call graph."""
        ...
