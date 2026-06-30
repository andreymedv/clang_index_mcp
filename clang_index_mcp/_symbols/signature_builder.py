"""Human-readable C++ signature construction from libclang cursors.

This module isolates the string manipulation required to turn clang type
spellings into signatures such as ``int foo(const std::string&)``.  Keeping it
separate makes it testable without instantiating the full SymbolExtractor.
"""

from typing import Any, List

from clang.cindex import Cursor

from .._core import diagnostics


def get_type_spelling(cursor: Cursor):
    """Safely get cursor.type.spelling, returning None if unavailable."""
    if not cursor.type:
        return None
    return cursor.type.spelling or None


def get_return_type(cursor: Cursor) -> str:
    """Safely get cursor.result_type.spelling."""
    try:
        if cursor.result_type and cursor.result_type.spelling:
            return str(cursor.result_type.spelling)
    except Exception:
        pass
    return ""


def format_args(args: List[Any]) -> str:
    """Format a list of cursor arguments into a parameter string."""
    param_parts = []
    for arg in args:
        arg_type = arg.type.spelling if arg.type else ""
        arg_name = arg.spelling or ""
        if arg_name:
            param_parts.append(f"{arg_type} {arg_name}")
        else:
            param_parts.append(arg_type)
    return ", ".join(param_parts)


def extract_params_from_type_spelling(type_spelling: str) -> str:
    """Extract parameter types from a C function type spelling string."""
    if not type_spelling:
        return ""

    depth = 0
    start = -1
    for i, ch in enumerate(type_spelling):
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and start >= 0:
                return type_spelling[start + 1 : i]

    return ""


def extract_trailing_qualifiers(type_spelling: str) -> str:
    """Extract trailing qualifiers from type spelling."""
    if not type_spelling:
        return ""

    depth = 0
    last_close = -1
    for i, ch in enumerate(type_spelling):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                last_close = i

    if last_close >= 0 and last_close < len(type_spelling) - 1:
        qualifiers = type_spelling[last_close + 1 :]
        return qualifiers

    return ""


def assemble_signature(return_type: str, name: str, params_str: str, qualifiers: str) -> str:
    """Assemble the final human-readable signature string."""
    if return_type:
        return f"{return_type} {name}({params_str}){qualifiers}"
    return f"{name}({params_str}){qualifiers}"


def fallback_signature(cursor: Cursor) -> str:
    """Return cursor.type.spelling as a fallback, or empty string on failure."""
    try:
        return cursor.type.spelling if cursor.type else ""
    except Exception:
        return ""


def get_params_str(cursor: Cursor, type_spelling: str) -> str:
    """Get parameter string from cursor arguments or type spelling fallback."""
    try:
        args = list(cursor.get_arguments())
        if args:
            return format_args(args)
        return extract_params_from_type_spelling(type_spelling)
    except Exception:
        return extract_params_from_type_spelling(type_spelling)


def _try_build_human_readable_signature(cursor: Cursor) -> str:
    """Attempt to build signature without exception handling."""
    type_spelling = get_type_spelling(cursor)
    if type_spelling is None:
        return ""

    name = cursor.spelling or ""
    return_type = get_return_type(cursor)
    params_str = get_params_str(cursor, type_spelling)
    qualifiers = extract_trailing_qualifiers(type_spelling)

    return assemble_signature(return_type, name, params_str, qualifiers)


def build_human_readable_signature(cursor: Cursor) -> str:
    """Build a human-readable function signature from a libclang cursor."""
    try:
        return _try_build_human_readable_signature(cursor)
    except Exception as e:
        diagnostics.debug(f"Could not build human-readable signature for {cursor.spelling}: {e}")
        return fallback_signature(cursor)
