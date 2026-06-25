"""Presentation/serialization helpers for SymbolInfo.

These functions build response-shaped dictionaries from the domain entity.
They live outside symbol_info.py to keep the entity pure.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .symbol_info import SymbolInfo


def build_location_objects(info: "SymbolInfo") -> dict:
    """Build declaration/definition location objects from SymbolInfo for tool responses.

    Replaces flat file/line/start_line/end_line/header_* fields with nested objects.

    When the symbol has a split declaration/definition (e.g., declared in .h, defined in .cpp):
        {"declaration": {"file": ..., "line": ..., "start_line": ..., "end_line": ...},
         "definition":  {"file": ..., "line": ..., "start_line": ..., "end_line": ...}}

    When there is only one location:
        {"definition": {"file": ..., "line": ..., ...}}   -- if is_definition
        {"declaration": {"file": ..., "line": ..., ...}}  -- if only a declaration

    None values for start_line/end_line are omitted.
    """

    def _loc(file: str, line: int, start: "int | None", end: "int | None") -> dict:
        d: dict = {"file": file, "line": line}
        if start is not None:
            d["start_line"] = start
        if end is not None:
            d["end_line"] = end
        return d

    if info.header_file:
        # Split case: info.file = declaration location, info.header_file = definition location
        return {
            "declaration": _loc(info.file, info.line, info.start_line, info.end_line),
            "definition": _loc(
                info.header_file,
                info.header_line,  # type: ignore[arg-type]
                info.header_start_line,
                info.header_end_line,
            ),
        }
    else:
        loc = _loc(info.file, info.line, info.start_line, info.end_line)
        if info.is_definition:
            return {"definition": loc}
        else:
            return {"declaration": loc}


def omit_empty(d: dict) -> dict:
    """Filter None values from a response dict.

    Keeps False, 0, empty strings, and empty lists (which may convey
    meaningful information such as namespace="" for global scope).
    Used to reduce token count in MCP tool responses.
    """
    return {k: v for k, v in d.items() if v is not None}


def symbol_info_to_dict(info: "SymbolInfo") -> dict:
    """Convert a SymbolInfo to a dictionary for JSON serialization."""
    return {
        "name": info.name,
        "qualified_name": info.qualified_name,
        "kind": info.kind,
        "file": info.file,
        "line": info.line,
        "column": info.column,
        "signature": info.signature,
        "is_project": info.is_project,
        "namespace": info.namespace,
        "access": info.access,
        "parent_class": info.parent_class,
        "base_classes": info.base_classes,
        "usr": info.usr,
        "is_template_specialization": info.is_template_specialization,
        "is_template": info.is_template,
        "template_kind": info.template_kind,
        "template_parameters": info.template_parameters,
        "specialization_of": info.primary_template_usr,
        "start_line": info.start_line,
        "end_line": info.end_line,
        "header_file": info.header_file,
        "header_line": info.header_line,
        "header_start_line": info.header_start_line,
        "header_end_line": info.header_end_line,
        "brief": info.brief,
        "doc_comment": info.doc_comment,
        "is_virtual": info.is_virtual,
        "is_pure_virtual": info.is_pure_virtual,
        "is_const": info.is_const,
        "is_static": info.is_static,
        "is_definition": info.is_definition,
    }
