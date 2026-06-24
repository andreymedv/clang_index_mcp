"""Parser port for the symbols/domain layer."""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol

from ..._symbols.model import SymbolInfo


@dataclass
class ParseResult:
    """Result returned by a symbol parser after AST traversal."""

    symbols: List[SymbolInfo]
    call_sites: List[Any]
    type_aliases: List[Dict[str, Any]]
    processed_headers: Dict[str, str]


class SymbolParser(Protocol):
    """Port for AST-based symbol extraction."""

    def parse(
        self,
        tu: Any,
        source_file: str,
        should_extract_from_file: Optional[Callable[[str], bool]] = None,
    ) -> ParseResult:
        """Parse a translation unit and return extracted symbol data."""
        ...
