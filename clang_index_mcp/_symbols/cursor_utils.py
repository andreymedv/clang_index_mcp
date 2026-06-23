"""Low-level cursor utilities shared across symbol extraction modules.

These helpers depend only on libclang cursor objects and the core diagnostics
logger.  Extracting them from SymbolExtractor breaks circular dependencies
between the main extractor and smaller focused extractors (e.g. alias extraction).
"""

from typing import Any

from clang.cindex import CursorKind

from .._core import diagnostics


def get_qualified_name(cursor: Any) -> str:
    """Build fully qualified name by walking up semantic parent chain."""
    parts = []
    current = cursor
    max_depth = 100
    depth = 0
    visited = set()

    while current and depth < max_depth:
        cursor_id = id(current)
        if cursor_id in visited:
            diagnostics.warning(
                f"Circular reference detected in semantic parent chain for {cursor.spelling}"
            )
            break
        visited.add(cursor_id)

        if current.kind == CursorKind.TRANSLATION_UNIT:
            break

        if current.spelling:
            parts.append(current.spelling)
        elif current.kind == CursorKind.NAMESPACE and current.is_anonymous():
            parts.append("(anonymous namespace)")

        current = current.semantic_parent
        depth += 1

    if depth >= max_depth:
        diagnostics.warning(
            f"Maximum depth ({max_depth}) exceeded when building qualified name for {cursor.spelling}"
        )

    parts.reverse()
    return "::".join(parts) if parts else cursor.spelling


def extract_namespace(qualified_name: str) -> str:
    """Extract namespace portion from qualified name."""
    if "::" not in qualified_name:
        return ""

    parts = qualified_name.split("::")
    return "::".join(parts[:-1])
