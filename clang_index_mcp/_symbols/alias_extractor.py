"""Type alias extraction from libclang cursors.

Handles ``TYPEDEF_DECL``, ``TYPE_ALIAS_DECL`` and ``TYPE_ALIAS_TEMPLATE_DECL``
cursors and produces the normalized dictionaries consumed by SymbolExtractor.
"""

import json
import time
from dataclasses import dataclass

from clang.cindex import Cursor, CursorKind

from .._symbols.ports.parser import TypeAliasRecord
from .cursor_utils import extract_namespace, get_qualified_name, iter_template_params


def _extract_location(cursor: Cursor) -> tuple[str, int, int]:
    """Extract file path, line, and column from a cursor's location."""
    file_path = str(cursor.location.file.name) if cursor.location.file else ""
    return file_path, cursor.location.line, cursor.location.column


def _underlying_typedef_type(cursor: Cursor) -> tuple[str, str]:
    """Extract target and canonical type spellings, falling back to the cursor's own type."""
    try:
        underlying_type = cursor.underlying_typedef_type
        target_type = underlying_type.spelling
        canonical_type = underlying_type.get_canonical().spelling
    except AttributeError:
        target_type = cursor.type.spelling
        canonical_type = cursor.type.get_canonical().spelling
    return target_type, canonical_type


@dataclass
class AliasInfoBase:
    """Base information extracted from any type alias cursor."""

    alias_name: str
    qualified_name: str
    target_type: str
    canonical_type: str
    file_path: str
    line: int
    column: int


@dataclass
class TemplateAliasInfo(AliasInfoBase):
    """Information extracted from a TYPE_ALIAS_TEMPLATE_DECL cursor."""

    template_params: list[dict]


@dataclass
class SimpleAliasInfo(AliasInfoBase):
    """Information extracted from a TYPEDEF_DECL or TYPE_ALIAS_DECL cursor."""

    alias_kind: str


def extract_template_alias_info(cursor: Cursor) -> TemplateAliasInfo:
    """Extract alias info from a TYPE_ALIAS_TEMPLATE_DECL cursor."""
    template_params = []
    type_alias_decl = None

    for child in cursor.get_children():
        if child.kind == CursorKind.TYPE_ALIAS_DECL:
            type_alias_decl = child

    for child in iter_template_params(cursor):
        if child.kind == CursorKind.TEMPLATE_TYPE_PARAMETER:
            template_params.append({"name": child.spelling, "kind": "type"})
        elif child.kind == CursorKind.TEMPLATE_NON_TYPE_PARAMETER:
            template_params.append(
                {"name": child.spelling, "kind": "non_type", "type": child.type.spelling}
            )

    if type_alias_decl:
        alias_name = type_alias_decl.spelling
        qualified_name = get_qualified_name(type_alias_decl)
        target_type, canonical_type = _underlying_typedef_type(type_alias_decl)
    else:
        alias_name = cursor.spelling
        qualified_name = get_qualified_name(cursor)
        target_type = ""
        canonical_type = ""

    file_path, line, column = _extract_location(cursor)

    return TemplateAliasInfo(
        alias_name=alias_name,
        qualified_name=qualified_name,
        target_type=target_type,
        canonical_type=canonical_type,
        file_path=file_path,
        line=line,
        column=column,
        template_params=template_params,
    )


def extract_simple_alias_info(cursor: Cursor) -> SimpleAliasInfo:
    """Extract alias info from a TYPEDEF_DECL or TYPE_ALIAS_DECL cursor."""
    alias_name = cursor.spelling
    qualified_name = get_qualified_name(cursor)
    target_type, canonical_type = _underlying_typedef_type(cursor)

    if cursor.kind == CursorKind.TYPE_ALIAS_DECL:
        alias_kind = "using"
    elif cursor.kind == CursorKind.TYPEDEF_DECL:
        alias_kind = "typedef"
    else:
        alias_kind = "unknown"

    file_path, line, column = _extract_location(cursor)

    return SimpleAliasInfo(
        alias_name=alias_name,
        qualified_name=qualified_name,
        target_type=target_type,
        canonical_type=canonical_type,
        file_path=file_path,
        line=line,
        column=column,
        alias_kind=alias_kind,
    )


def extract_alias_info(cursor: Cursor) -> TypeAliasRecord:
    """Extract type alias information from TYPEDEF_DECL, TYPE_ALIAS_DECL, or TYPE_ALIAS_TEMPLATE_DECL cursor."""
    is_template_alias = cursor.kind == CursorKind.TYPE_ALIAS_TEMPLATE_DECL

    if is_template_alias:
        template_info = extract_template_alias_info(cursor)
        alias_kind = "using"
        template_params = template_info.template_params
        base_info: AliasInfoBase = template_info
    else:
        simple_info = extract_simple_alias_info(cursor)
        alias_kind = simple_info.alias_kind
        template_params = []
        base_info = simple_info

    namespace = extract_namespace(base_info.qualified_name)

    return TypeAliasRecord(
        alias_name=base_info.alias_name,
        qualified_name=base_info.qualified_name,
        target_type=base_info.target_type,
        canonical_type=base_info.canonical_type,
        file=base_info.file_path,
        line=base_info.line,
        column=base_info.column,
        alias_kind=alias_kind,
        namespace=namespace,
        is_template_alias=is_template_alias,
        template_params=json.dumps(template_params) if template_params else None,
        created_at=time.time(),
    )
