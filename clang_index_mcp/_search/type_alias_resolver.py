"""Type alias resolution helpers for the query engine.

Centralizes lookup of canonical types, alias details, and ambiguity handling so
that type-alias queries are isolated from the rest of query-engine logic.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

from .._search.pattern_matcher import matches_qualified_pattern
from .._search.ports.search_deps import SearchDependencies
from .._symbols.model import SymbolInfo

if TYPE_CHECKING:
    pass


def get_alias_details_from_db(alias_names: List[str], cache_manager) -> List[Dict[str, Any]]:
    """Query the cache backend for detailed information about a set of aliases."""
    return cast(List[Dict[str, Any]], cache_manager.get_type_alias_details(alias_names))


def get_info_for_known_alias(type_name: str, cache_manager) -> Optional[Dict[str, Any]]:
    """Attempt to get type alias info from the cache if type_name is a known alias."""
    return cast(Optional[Dict[str, Any]], cache_manager.get_type_alias_info(type_name))


def find_type_matches(
    type_name: str,
    context: SearchDependencies,
) -> List[SymbolInfo]:
    """Search class index for matching types and return list of matches."""
    matches: List[SymbolInfo] = []
    assert context.symbol_store is not None
    with context.concurrency.index_lock:
        for name, infos in context.symbol_store.iter_class_items():
            for info in infos:
                qualified_name = info.qualified_name if info.qualified_name else info.name
                if matches_qualified_pattern(qualified_name, type_name):
                    matches.append(info)
    return matches


def check_type_ambiguity(type_name: str, matches: List[SymbolInfo]) -> Optional[Dict[str, Any]]:
    """Check for ambiguity among matches and return error dict if ambiguous."""
    if len(matches) > 1:
        unique_qualified_names = set(
            m.qualified_name if m.qualified_name else m.name for m in matches
        )
        if len(unique_qualified_names) > 1:
            return {
                "error": f"Ambiguous type name '{type_name}'",
                "is_ambiguous": True,
                "matches": [
                    {
                        "canonical_type": m.name,
                        "qualified_name": m.qualified_name if m.qualified_name else m.name,
                        "namespace": m.namespace,
                        "file": m.file,
                        "line": m.line,
                    }
                    for m in matches
                ],
                "suggestion": "Use qualified name (e.g., 'ui::Widget')",
            }
    return None


def get_type_alias_info(
    type_name: str,
    context: SearchDependencies,
) -> Dict[str, Any]:
    """Get comprehensive type alias information."""
    input_canonical = context.cache_manager.get_canonical_for_alias(type_name)
    input_was_alias = False

    if input_canonical:
        input_was_alias = True
        info = get_info_for_known_alias(type_name, context.cache_manager)
        if info:
            return info

    matches = find_type_matches(type_name, context)

    ambiguity_error = check_type_ambiguity(type_name, matches)
    if ambiguity_error:
        return ambiguity_error

    if len(matches) == 0:
        return {
            "error": f"Type '{type_name}' not found",
            "canonical_type": None,
            "aliases": [],
        }

    canonical_info = matches[0]
    for m in matches:
        if m.is_definition:
            canonical_info = m
            break

    canonical_type = (
        canonical_info.qualified_name if canonical_info.qualified_name else canonical_info.name
    )

    alias_names = context.cache_manager.get_aliases_for_canonical(canonical_type)
    aliases = get_alias_details_from_db(alias_names, context.cache_manager) if alias_names else []

    return {
        "canonical_type": canonical_type,
        "qualified_name": (
            canonical_info.qualified_name if canonical_info.qualified_name else canonical_info.name
        ),
        "namespace": canonical_info.namespace,
        "file": canonical_info.file,
        "line": canonical_info.line,
        "input_was_alias": input_was_alias,
        "is_ambiguous": False,
        "aliases": aliases,
    }
