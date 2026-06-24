"""Class hierarchy traversal helpers for the query engine.

Encapsulates resolving base-class keys, looking up class infos, and BFS traversal
for ``get_class_hierarchy`` so that the QueryEngine class does not need to own all
of this logic.
"""

from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

from .._symbols.model import SymbolInfo
from .._search.pattern_matcher import matches_qualified_pattern
from .._search.search_engine import SearchEngine
from .._search.template_analyzer import get_derived_classes


def resolve_base_key(raw: str, symbol_store, index_lock) -> str:
    """Resolve a raw base-class name to a canonical key (qualified name)."""
    is_dependent = raw.startswith("typename ") or (
        "<" in raw and ">" in raw and not raw.endswith(">")
    )
    if is_dependent:
        return raw
    has_targs = "<" in raw
    lookup = SearchEngine._strip_template_args(raw) if has_targs else raw
    is_qual = "::" in lookup
    simple = SearchEngine._extract_simple_name(lookup)
    with index_lock:
        infos = symbol_store.get_classes_by_name(simple)
        for info in infos:
            if is_qual:
                info_qn = info.qualified_name if info.qualified_name else info.name
                if not matches_qualified_pattern(info_qn, lookup):
                    continue
            qn = info.qualified_name if info.qualified_name else info.name
            return str(qn)  # type: ignore[no-any-return]
    return raw


def lookup_class_infos(key: str, symbol_store, index_lock) -> List[SymbolInfo]:
    """Look up SymbolInfo objects for a class name/key."""
    has_targs = "<" in key
    lookup = SearchEngine._strip_template_args(key) if has_targs else key
    is_qual = "::" in lookup
    simple = SearchEngine._extract_simple_name(lookup)
    with index_lock:
        infos = list(symbol_store.get_classes_by_name(simple))
    if is_qual:
        infos = [
            i
            for i in infos
            if matches_qualified_pattern(i.qualified_name if i.qualified_name else i.name, lookup)
        ]
    if has_targs and not is_qual:
        specs = [i for i in infos if i.is_template_specialization]
        if specs:
            infos = specs
    return infos


def collect_hierarchy_node_data(
    key: str,
    symbol_store,
    index_lock,
) -> Optional[Dict[str, Any]]:
    """Collect class node data for hierarchy building. Returns None if not found."""
    infos = lookup_class_infos(key, symbol_store, index_lock)
    if not infos:
        # Unresolved: external lib or template-dependent name
        is_dep = key.startswith("typename ") or (
            "<" in key and ">" in key and not key.endswith(">")
        )
        node: Dict[str, Any] = {
            "qualified_name": key,
            "kind": "unknown",
            "is_project": False,
            "base_classes": [],
            "derived_classes": [],
        }
        if is_dep:
            node["is_dependent_type"] = True
        else:
            node["is_unresolved"] = True
        return node

    info = infos[0]
    info_key = info.qualified_name if info.qualified_name else info.name

    # Resolve raw base class names to canonical keys (dedup, preserve order)
    base_keys: List[str] = []
    seen_base: Set[str] = set()
    for raw_base in info.base_classes:
        bk = resolve_base_key(raw_base, symbol_store, index_lock)
        if bk not in seen_base:
            seen_base.add(bk)
            base_keys.append(bk)

    # Get derived classes for this node
    derived = get_derived_classes(
        info_key, project_only=False, symbol_store=symbol_store, index_lock=index_lock
    )
    derived_keys: List[str] = []
    seen_derived: Set[str] = set()
    for d in derived:
        dk = d["qualified_name"]
        if dk not in seen_derived:
            seen_derived.add(dk)
            derived_keys.append(dk)

    return {
        "qualified_name": info_key,
        "kind": info.kind,
        "is_project": info.is_project,
        "base_classes": base_keys,
        "derived_classes": derived_keys,
    }


def should_skip_hierarchy_node(
    current: str, visited: Set[str], initial_visited: Optional[Set[str]], start_key: str
) -> bool:
    """Decide if a node should be skipped during BFS."""
    if current in visited:
        if initial_visited is None:
            return True
        if current != start_key:
            return True
    return False


def bfs_traverse_hierarchy(
    start_key: str,
    direction: str,
    max_depth: Optional[int],
    max_nodes: Optional[int],
    classes: Dict[str, Any],
    symbol_store,
    index_lock,
    initial_visited: Optional[Set[str]] = None,
) -> Tuple[Set[str], bool]:
    """Perform BFS traversal in specified direction for class hierarchy.
    Returns (set of visited keys, truncated flag).
    """
    visited: Set[str] = initial_visited if initial_visited is not None else set()
    queue: deque = deque([(start_key, 0)])
    local_truncated = False
    neighbor_attr = "base_classes" if direction == "up" else "derived_classes"

    while queue:
        current, depth = queue.popleft()
        if should_skip_hierarchy_node(current, visited, initial_visited, start_key):
            continue
        visited.add(current)

        node_data = collect_hierarchy_node_data(current, symbol_store, index_lock)
        if node_data is None:
            continue

        # Add to classes if not already there (for final collection)
        if current not in classes:
            classes[current] = node_data

        # Check node cap AFTER adding current node
        if max_nodes is not None and len(classes) >= max_nodes:
            local_truncated = True
            break

        next_depth = depth + 1
        if max_depth is not None and next_depth > max_depth:
            if any(n not in visited for n in node_data[neighbor_attr]):
                local_truncated = True
        else:
            for neighbor in node_data[neighbor_attr]:
                if neighbor not in visited:
                    queue.append((neighbor, next_depth))

    return visited, local_truncated


def get_class_hierarchy(
    class_name: str,
    max_nodes: Optional[int],
    max_depth: Optional[int],
    direction: str,
    symbol_store,
    index_lock,
) -> Dict[str, Any]:
    """Get the inheritance graph for a class as a flat adjacency list."""
    if direction not in ("up", "down", "both"):
        return {"error": f"Invalid direction '{direction}'. Must be one of: up, down, both"}

    start_infos = lookup_class_infos(class_name, symbol_store, index_lock)
    if not start_infos:
        return {"error": f"Class '{class_name}' not found"}

    start_info = start_infos[0]
    start_key = start_info.qualified_name or start_info.name
    classes: Dict[str, Any] = {}
    truncated = False

    if direction == "up":
        _, truncated = bfs_traverse_hierarchy(
            start_key, "up", max_depth, max_nodes, classes, symbol_store, index_lock
        )
    elif direction == "down":
        _, truncated = bfs_traverse_hierarchy(
            start_key, "down", max_depth, max_nodes, classes, symbol_store, index_lock
        )
    else:  # both
        v_up, trunc_up = bfs_traverse_hierarchy(
            start_key, "up", max_depth, max_nodes, classes, symbol_store, index_lock
        )
        trunc_down = False
        if max_nodes is None or len(classes) < max_nodes:
            _, trunc_down = bfs_traverse_hierarchy(
                start_key,
                "down",
                max_depth,
                max_nodes,
                classes,
                symbol_store,
                index_lock,
                initial_visited=v_up,
            )
        truncated = trunc_up or trunc_down

    result: Dict[str, Any] = {
        "queried_class": start_key,
        "direction": direction,
        "classes": classes,
    }
    if truncated:
        result.update(
            {"truncated": True, "nodes_returned": len(classes), "completeness": "partial"}
        )
        result["completeness_note"] = "Hierarchy was truncated due to max_nodes or max_depth limit."
    else:
        result.update({"completeness": "complete"})
        result["completeness_note"] = (
            "Full inheritance hierarchy including all ancestors and descendants."
        )
    return result
