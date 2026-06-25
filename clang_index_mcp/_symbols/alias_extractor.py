"""Type alias extraction from libclang cursors.

Handles ``TYPEDEF_DECL``, ``TYPE_ALIAS_DECL`` and ``TYPE_ALIAS_TEMPLATE_DECL``
cursors and produces the normalized dictionaries consumed by SymbolExtractor.
"""

import json
import time
from typing import Any, Dict, List, Tuple

from clang.cindex import CursorKind

from .cursor_utils import extract_namespace, get_qualified_name


def extract_template_alias_info(
    cursor: Any,
) -> Tuple[str, str, str, str, str, int, int, List[dict]]:
    """Extract alias info from a TYPE_ALIAS_TEMPLATE_DECL cursor."""
    template_params = []
    type_alias_decl = None

    for child in cursor.get_children():
        if child.kind == CursorKind.TEMPLATE_TYPE_PARAMETER:
            template_params.append({"name": child.spelling, "kind": "type"})
        elif child.kind == CursorKind.TEMPLATE_NON_TYPE_PARAMETER:
            template_params.append(
                {"name": child.spelling, "kind": "non_type", "type": child.type.spelling}
            )
        elif child.kind == CursorKind.TYPE_ALIAS_DECL:
            type_alias_decl = child

    if type_alias_decl:
        alias_name = type_alias_decl.spelling
        qualified_name = get_qualified_name(type_alias_decl)

        try:
            underlying_type = type_alias_decl.underlying_typedef_type
            target_type = underlying_type.spelling
            canonical_type = underlying_type.get_canonical().spelling
        except AttributeError:
            target_type = type_alias_decl.type.spelling
            canonical_type = type_alias_decl.type.get_canonical().spelling
    else:
        alias_name = cursor.spelling
        qualified_name = get_qualified_name(cursor)
        target_type = ""
        canonical_type = ""

    file_path = str(cursor.location.file.name) if cursor.location.file else ""
    line = cursor.location.line
    column = cursor.location.column

    return (
        alias_name,
        qualified_name,
        target_type,
        canonical_type,
        file_path,
        line,
        column,
        template_params,
    )


def extract_simple_alias_info(
    cursor: Any,
) -> Tuple[str, str, str, str, str, int, int, str]:
    """Extract alias info from a TYPEDEF_DECL or TYPE_ALIAS_DECL cursor."""
    alias_name = cursor.spelling
    qualified_name = get_qualified_name(cursor)

    try:
        underlying_type = cursor.underlying_typedef_type
        target_type = underlying_type.spelling
        canonical_type = underlying_type.get_canonical().spelling
    except AttributeError:
        target_type = cursor.type.spelling
        canonical_type = cursor.type.get_canonical().spelling

    if cursor.kind == CursorKind.TYPE_ALIAS_DECL:
        alias_kind = "using"
    elif cursor.kind == CursorKind.TYPEDEF_DECL:
        alias_kind = "typedef"
    else:
        alias_kind = "unknown"

    file_path = str(cursor.location.file.name) if cursor.location.file else ""
    line = cursor.location.line
    column = cursor.location.column

    return (
        alias_name,
        qualified_name,
        target_type,
        canonical_type,
        file_path,
        line,
        column,
        alias_kind,
    )


def extract_alias_info(cursor: Any) -> Dict[str, Any]:
    """Extract type alias information from TYPEDEF_DECL, TYPE_ALIAS_DECL, or TYPE_ALIAS_TEMPLATE_DECL cursor."""
    is_template_alias = cursor.kind == CursorKind.TYPE_ALIAS_TEMPLATE_DECL

    if is_template_alias:
        (
            alias_name,
            qualified_name,
            target_type,
            canonical_type,
            file_path,
            line,
            column,
            template_params,
        ) = extract_template_alias_info(cursor)
        alias_kind = "using"
    else:
        (
            alias_name,
            qualified_name,
            target_type,
            canonical_type,
            file_path,
            line,
            column,
            alias_kind,
        ) = extract_simple_alias_info(cursor)
        template_params = []

    namespace = extract_namespace(qualified_name)

    return {
        "alias_name": alias_name,
        "qualified_name": qualified_name,
        "target_type": target_type,
        "canonical_type": canonical_type,
        "file": file_path,
        "line": line,
        "column": column,
        "alias_kind": alias_kind,
        "namespace": namespace,
        "is_template_alias": is_template_alias,
        "template_params": json.dumps(template_params) if template_params else None,
        "created_at": time.time(),
    }
