"""Parser port for the symbols/domain layer."""

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Protocol

from clang.cindex import TranslationUnit

from ..._symbols.model import SymbolInfo


@dataclass(frozen=True)
class CallSiteRecord:
    """A single call record produced during AST traversal."""

    caller_usr: str
    callee_usr: str
    file: Optional[str]
    line: Optional[int]
    column: Optional[int]
    display_name: Optional[str] = None
    template_project_types: Optional[str] = None


@dataclass(frozen=True)
class TypeAliasRecord:
    """A type alias record produced during AST traversal."""

    alias_name: str
    qualified_name: str
    target_type: str
    canonical_type: str
    file: str
    line: int
    column: int
    alias_kind: str
    namespace: str
    is_template_alias: bool
    template_params: Optional[str] = None
    created_at: float = 0.0


@dataclass
class ParseResult:
    """Result returned by a symbol parser after AST traversal."""

    symbols: List[SymbolInfo]
    call_sites: List[CallSiteRecord]
    type_aliases: List[TypeAliasRecord]
    processed_headers: Dict[str, str]


class SymbolParser(Protocol):
    """Port for AST-based symbol extraction."""

    def parse(
        self,
        tu: TranslationUnit,
        source_file: str,
        should_extract_from_file: Optional[Callable[[str], bool]] = None,
    ) -> ParseResult:
        """Parse a translation unit and return extracted symbol data."""
        ...
