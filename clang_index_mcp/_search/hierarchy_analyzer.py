"""Class hierarchy traversal helpers for the query engine.

Encapsulates building the inheritance adjacency graph and BFS traversal for
``get_class_hierarchy`` so that the QueryEngine class does not need to own all
of this logic.

Template specializations are first-class nodes (issue cplusplus_mcp-jqqq):
``T<A1>`` and ``T<A2>`` are distinct keys with their own base/derived edges.
The primary template ``T`` acts as an aggregation hub connected to its
instantiations through a separate ``instantiates`` / ``specialization_of``
relationship which does not participate in inheritance reachability — walking
``T<A1>`` never pulls in ``T<A2>`` or its descendants.
"""

from collections import deque
from typing import Any

from .._search.pattern_matcher import matches_qualified_pattern
from .._search.symbol_name_utils import (
    extract_simple_name,
    is_dependent_type_name,
    is_specialization_key,
)
from .._search.template_analyzer import (
    find_matching_specialization,
    format_specialization_key,
    parse_specialization_key,
    recover_specialization_args,
    resolve_class_key,
    substitute_template_params,
)
from .._symbols.model import SymbolInfo


def resolve_base_key(raw: str, symbol_store, index_lock) -> str:
    """Resolve a raw base-class name to a canonical node key.

    Template arguments are preserved: ``T<A1>`` resolves to ``T<A1>``
    (template-name portion qualified when namespaced), never collapsing to
    ``T``.
    """
    return resolve_class_key(raw, symbol_store, index_lock)


def _info_rank(info: SymbolInfo) -> int:
    """Preference rank when several symbols share one node key."""
    if info.kind == "class_template":
        return 2
    if info.base_classes:
        return 1
    return 0


def lookup_class_infos(key: str, symbol_store, index_lock) -> list[SymbolInfo]:
    """Look up class symbols for a plain class key (best match first)."""
    is_qual = "::" in key
    simple = extract_simple_name(key)
    with index_lock:
        infos = list(symbol_store.get_classes_by_name(simple))
    if is_qual:
        infos = [
            i
            for i in infos
            if matches_qualified_pattern(i.qualified_name if i.qualified_name else i.name, key)
        ]
    infos.sort(key=_info_rank, reverse=True)
    return infos


def _node_key(info: SymbolInfo) -> str:
    return str(info.qualified_name if info.qualified_name else info.name)


class HierarchyGraph:
    """Inheritance adjacency with first-class template specialization nodes."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}

    def ensure_node(self, key: str) -> dict[str, Any]:
        if key not in self.nodes:
            self.nodes[key] = {
                "qualified_name": key,
                "kind": "unknown",
                "is_project": False,
                "base_classes": [],
                "derived_classes": [],
            }
        return self.nodes[key]

    def add_edge(self, derived_key: str, base_key: str) -> None:
        derived = self.ensure_node(derived_key)
        base = self.ensure_node(base_key)
        if base_key not in derived["base_classes"]:
            derived["base_classes"].append(base_key)
        if derived_key not in base["derived_classes"]:
            base["derived_classes"].append(derived_key)


def build_hierarchy_graph(symbol_store, index_lock) -> HierarchyGraph:
    """Build the full inheritance adjacency (one index pass per query)."""
    graph = HierarchyGraph()
    infos = _snapshot_class_infos(symbol_store, index_lock)
    for key, info in _pick_primary_infos(infos).items():
        _register_plain_node(graph, key, info, symbol_store, index_lock)
    for info in infos:
        if info.is_template_specialization:
            _register_spec_from_info(graph, info, symbol_store, index_lock)
    _mark_stub_nodes(graph)
    _aggregate_instantiations(graph)
    return graph


def _snapshot_class_infos(symbol_store, index_lock) -> list[SymbolInfo]:
    with index_lock:
        return [info for _, infos in symbol_store.iter_class_items() for info in infos]


def _pick_primary_infos(infos: list[SymbolInfo]) -> dict[str, SymbolInfo]:
    """Pick one representative per plain node key (full specs get own keys)."""
    chosen: dict[str, SymbolInfo] = {}
    for info in infos:
        if info.is_template_specialization:
            continue
        key = _node_key(info)
        current = chosen.get(key)
        if current is None or _info_rank(info) > _info_rank(current):
            chosen[key] = info
    return chosen


def _register_plain_node(
    graph: HierarchyGraph, key: str, info: SymbolInfo, symbol_store, index_lock
) -> None:
    node = graph.ensure_node(key)
    node["kind"] = info.kind
    node["is_project"] = info.is_project
    for raw in info.base_classes:
        base_key = resolve_class_key(raw, symbol_store, index_lock)
        if is_specialization_key(base_key):
            _ensure_spec_node(graph, base_key, symbol_store, index_lock)
        graph.add_edge(key, base_key)


def _register_spec_from_info(
    graph: HierarchyGraph, spec: SymbolInfo, symbol_store, index_lock
) -> None:
    primary = _lookup_primary_template(_node_key(spec), symbol_store, index_lock)
    args = recover_specialization_args(spec, primary, symbol_store, index_lock)
    if args is None or primary is None:
        return
    spec_key = format_specialization_key(_node_key(primary), args)
    _fill_spec_node(graph, spec_key, primary, args, spec, symbol_store, index_lock)


def _ensure_spec_node(graph: HierarchyGraph, spec_key: str, symbol_store, index_lock) -> None:
    existing = graph.nodes.get(spec_key)
    if existing is not None and existing["kind"] != "unknown":
        return
    parts = parse_specialization_key(spec_key)
    if parts is None:
        return
    name_part, args = parts
    primary = _lookup_primary_template(name_part, symbol_store, index_lock)
    if primary is None:
        graph.ensure_node(spec_key)["is_unresolved"] = True
        return
    spec = find_matching_specialization(primary, args, symbol_store, index_lock)
    _fill_spec_node(graph, spec_key, primary, args, spec, symbol_store, index_lock)


def _fill_spec_node(
    graph: HierarchyGraph,
    spec_key: str,
    primary: SymbolInfo | None,
    args: list[str],
    spec: SymbolInfo | None,
    symbol_store,
    index_lock,
) -> None:
    node = graph.ensure_node(spec_key)
    if node["kind"] != "unknown":
        return
    parts = parse_specialization_key(spec_key) or (spec_key, [])
    raw_bases = (
        list(spec.base_classes)
        if spec and spec.base_classes
        else (list(primary.base_classes) if primary else [])
    )
    params = primary.template_parameters if primary else None
    node.update(
        {
            "kind": "full_specialization",
            "is_project": spec.is_project if spec else bool(primary and primary.is_project),
            "specialization_of": parts[0],
            "template_arguments": list(args),
        }
    )
    for raw in substitute_template_params(raw_bases, params, args):
        graph.add_edge(spec_key, resolve_class_key(raw, symbol_store, index_lock))


def _lookup_primary_template(name_key: str, symbol_store, index_lock) -> SymbolInfo | None:
    for info in lookup_class_infos(name_key, symbol_store, index_lock):
        if info.kind == "class_template":
            return info
    return None


def _mark_stub_nodes(graph: HierarchyGraph) -> None:
    for key, node in graph.nodes.items():
        if node["kind"] != "unknown":
            continue
        if is_dependent_type_name(key):
            node["is_dependent_type"] = True
        else:
            node["is_unresolved"] = True


def _aggregate_instantiations(graph: HierarchyGraph) -> None:
    for key, node in graph.nodes.items():
        template_key = node.get("specialization_of")
        if not template_key:
            continue
        hub = graph.ensure_node(template_key)
        if "instantiates" not in hub:
            hub["instantiates"] = []
        if key not in hub["instantiates"]:
            hub["instantiates"].append(key)
    for node in graph.nodes.values():
        if "instantiates" in node:
            node["instantiates"].sort()


def should_skip_hierarchy_node(
    current: str, visited: set[str], initial_visited: set[str] | None, start_key: str
) -> bool:
    """Decide if a node should be skipped during BFS."""
    if current in visited:
        if initial_visited is None:
            return True
        if current != start_key:
            return True
    return False


def _neighbors(node_data: dict[str, Any], direction: str) -> list[str]:
    """Neighbor keys for BFS: inheritance edges, plus hub aggregation on the way down."""
    if direction == "up":
        return list(node_data.get("base_classes", []))
    neighbors = list(node_data.get("derived_classes", []))
    # Aggregation hub: expand into instantiations (T -> T<A1>, T<A2>) only
    # downward from the template, never upward from a specialization.
    neighbors.extend(node_data.get("instantiates", []))
    return neighbors


def bfs_traverse_hierarchy(
    start_key: str,
    direction: str,
    max_depth: int | None,
    max_nodes: int | None,
    classes: dict[str, Any],
    graph: HierarchyGraph,
    initial_visited: set[str] | None = None,
) -> tuple[set[str], bool]:
    """Perform BFS traversal in specified direction for class hierarchy.
    Returns (set of visited keys, truncated flag).
    """
    visited: set[str] = initial_visited if initial_visited is not None else set()
    queue: deque = deque([(start_key, 0)])
    local_truncated = False

    while queue:
        current, depth = queue.popleft()
        if should_skip_hierarchy_node(current, visited, initial_visited, start_key):
            continue
        visited.add(current)

        node_data = graph.nodes.get(current)
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
        neighbors = _neighbors(node_data, direction)
        if max_depth is not None and next_depth > max_depth:
            if any(n not in visited for n in neighbors):
                local_truncated = True
        else:
            for neighbor in neighbors:
                if neighbor not in visited:
                    queue.append((neighbor, next_depth))

    return visited, local_truncated


def _scope_edges_to_graph(classes: dict[str, Any]) -> None:
    """Restrict node edge lists to nodes present in the result graph.

    Keeps the response a sound reachability graph: every base/derived (and
    hub-instantiation) reference resolves to a node in ``classes``, so foreign
    entities (e.g. a sibling co-base or a sibling specialization) never appear
    as quasi-edges. Full lists remain available via ``edge_scope='full'`` or a
    follow-up get_class_info query. ``specialization_of`` and
    ``template_arguments`` are annotations, not edges, and always stay.
    """
    for node in classes.values():
        node["base_classes"] = [b for b in node["base_classes"] if b in classes]
        node["derived_classes"] = [d for d in node["derived_classes"] if d in classes]
        if "instantiates" in node:
            node["instantiates"] = [s for s in node["instantiates"] if s in classes]


def _resolve_start_key(
    class_name: str, graph: HierarchyGraph, symbol_store, index_lock
) -> str | None:
    """Resolve the query name to its canonical start node key."""
    if is_specialization_key(class_name):
        key = resolve_class_key(class_name, symbol_store, index_lock)
        parts = parse_specialization_key(key)
        if parts and _lookup_primary_template(parts[0], symbol_store, index_lock):
            _ensure_spec_node(graph, key, symbol_store, index_lock)
            return key
        if graph.nodes.get(key, {}).get("kind") not in (None, "unknown"):
            return key
        return None
    infos = lookup_class_infos(class_name, symbol_store, index_lock)
    if not infos:
        return None
    return _node_key(infos[0])


def get_class_hierarchy(
    class_name: str,
    max_nodes: int | None,
    max_depth: int | None,
    direction: str,
    symbol_store,
    index_lock,
    edge_scope: str = "path",
) -> dict[str, Any]:
    """Get the inheritance graph for a class as a flat adjacency list."""
    if direction not in ("up", "down", "both"):
        return {"error": f"Invalid direction '{direction}'. Must be one of: up, down, both"}
    if edge_scope not in ("path", "full"):
        return {"error": f"Invalid edge_scope '{edge_scope}'. Must be one of: path, full"}

    graph = build_hierarchy_graph(symbol_store, index_lock)
    start_key = _resolve_start_key(class_name, graph, symbol_store, index_lock)
    if start_key is None:
        return {"error": f"Class '{class_name}' not found"}

    classes: dict[str, Any] = {}
    truncated = False

    if direction == "up":
        _, truncated = bfs_traverse_hierarchy(start_key, "up", max_depth, max_nodes, classes, graph)
    elif direction == "down":
        _, truncated = bfs_traverse_hierarchy(
            start_key, "down", max_depth, max_nodes, classes, graph
        )
    else:  # both
        v_up, trunc_up = bfs_traverse_hierarchy(
            start_key, "up", max_depth, max_nodes, classes, graph
        )
        trunc_down = False
        if max_nodes is None or len(classes) < max_nodes:
            _, trunc_down = bfs_traverse_hierarchy(
                start_key,
                "down",
                max_depth,
                max_nodes,
                classes,
                graph,
                initial_visited=v_up,
            )
        truncated = trunc_up or trunc_down

    if edge_scope == "path":
        _scope_edges_to_graph(classes)

    result: dict[str, Any] = {
        "queried_class": start_key,
        "direction": direction,
        "edge_scope": edge_scope,
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
