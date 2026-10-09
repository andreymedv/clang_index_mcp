"""Symbol extraction and call-graph domain context."""

from dataclasses import dataclass

from .ports.call_graph_service import CallGraphServiceProtocol
from .symbol_extractor import SymbolExtractor
from .symbol_index_store import SymbolIndexStore


@dataclass
class SymbolContext:
    """In-memory symbol indexes, extraction, and call-graph services."""

    symbol_store: SymbolIndexStore | None = None
    symbol_extractor: SymbolExtractor | None = None
    call_graph_service: CallGraphServiceProtocol | None = None
