"""Parser port for the symbols/domain layer."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from clang.cindex import TranslationUnit

from ..._symbols.model import SymbolInfo


@dataclass(frozen=True)
class CallSiteRecord:
    """A single call record produced during AST traversal."""

    caller_usr: str
    callee_usr: str
    file: str | None
    line: int | None
    column: int | None
    display_name: str | None = None
    template_project_types: str | None = None


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
    template_params: str | None = None
    created_at: float = 0.0


@dataclass
class ParseResult:
    """Result returned by a symbol parser after AST traversal."""

    symbols: list[SymbolInfo]
    call_sites: list[CallSiteRecord]
    type_aliases: list[TypeAliasRecord]
    processed_headers: dict[str, str]


class SymbolParser(Protocol):
    """Port for AST-based symbol extraction."""

    def parse(
        self,
        tu: TranslationUnit,
        source_file: str,
        should_extract_from_file: Callable[[str], bool] | None = None,
    ) -> ParseResult:
        """Parse a translation unit and return extracted symbol data."""
        ...
