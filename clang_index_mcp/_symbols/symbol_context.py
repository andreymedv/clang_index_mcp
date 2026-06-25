"""Symbol extraction and call-graph domain context."""

from dataclasses import dataclass
from typing import Any, Optional

from .symbol_extractor import SymbolExtractor
from .symbol_index_store import SymbolIndexStore


@dataclass
class SymbolContext:
    """In-memory symbol indexes, extraction, and call-graph services."""

    symbol_store: Optional[SymbolIndexStore] = None
    symbol_extractor: Optional[SymbolExtractor] = None
    call_graph_service: Optional[Any] = None
