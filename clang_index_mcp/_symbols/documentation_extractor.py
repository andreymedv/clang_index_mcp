"""Documentation comment extraction from libclang cursors.

This module isolates the logic that pulls ``brief_comment`` / ``raw_comment``
from clang cursors and normalizes them, so SymbolExtractor does not need to own
every small AST helper.
"""

from typing import Any, Dict, Optional

from .._core import diagnostics


def extract_brief_comment(cursor: Any) -> Optional[str]:
    """Extract and truncate brief comment from cursor."""
    brief_comment = cursor.brief_comment
    if not brief_comment:
        return None
    brief = str(brief_comment).strip()
    if len(brief) > 200:
        brief = brief[:200]
    return brief


def extract_raw_doc_comment(cursor: Any) -> Optional[str]:
    """Extract and truncate full documentation comment from cursor."""
    raw_comment = cursor.raw_comment
    if not raw_comment:
        return None
    doc_comment = str(raw_comment).strip()
    if len(doc_comment) > 4000:
        doc_comment = doc_comment[:3997] + "..."
    return doc_comment


def extract_brief_from_doc(doc_comment: str) -> Optional[str]:
    """Extract first meaningful line from a documentation comment."""
    for line in doc_comment.split("\n"):
        cleaned = line.strip().lstrip("/*!/").lstrip("*").strip()
        if cleaned and not cleaned.startswith("@"):
            if len(cleaned) > 200:
                cleaned = cleaned[:200]
            return cleaned
    return None


def extract_documentation(cursor: Any) -> Dict[str, Optional[str]]:
    """Extract documentation from cursor comments."""
    result: Dict[str, Optional[str]] = {"brief": None, "doc_comment": None}

    try:
        result["brief"] = extract_brief_comment(cursor)

        doc_comment = extract_raw_doc_comment(cursor)
        if doc_comment:
            result["doc_comment"] = doc_comment
            if not result["brief"]:
                result["brief"] = extract_brief_from_doc(doc_comment)

    except Exception as e:
        diagnostics.debug(f"Could not extract documentation for {cursor.spelling}: {e}")

    return result
