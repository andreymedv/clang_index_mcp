"""Hierarchy format converters for get_class_hierarchy tool.

Provides alternative output formats for class hierarchy data:
- json: Full verbose JSON (default, current behavior)
- compact: Abbreviated JSON keys
- cpp: C++ pseudocode format
- cpp_with_meta: C++ pseudocode with comment metadata
"""

from typing import Any, Dict, List, Set


def convert_hierarchy_format(
    hierarchy: Dict[str, Any],
    output_format: str,
) -> str:
    """Convert hierarchy data to specified output format.

    Args:
        hierarchy: The raw hierarchy data from get_class_hierarchy()
        output_format: One of 'json', 'compact', 'cpp', 'cpp_with_meta'

    Returns:
        Formatted string in the requested format
    """
    if output_format == "json":
        import json

        return json.dumps(hierarchy, indent=2)

    if output_format == "compact":
        return _format_compact_json(hierarchy)

    if output_format == "cpp":
        return _format_cpp_pseudocode(hierarchy, include_meta=False)

    if output_format == "cpp_with_meta":
        return _format_cpp_pseudocode(hierarchy, include_meta=True)

    # Fallback to JSON for unknown format
    import json

    return json.dumps(hierarchy, indent=2)


def _format_compact_json(hierarchy: Dict[str, Any]) -> str:
    """Format hierarchy as compact JSON with abbreviated keys."""
    import json

    # Key abbreviations
    key_map = {
        "queried_class": "q",
        "classes": "c",
        "qualified_name": "qn",
        "name": "n",
        "kind": "k",
        "is_project": "proj",
        "base_classes": "bases",
        "derived_classes": "derived",
        "is_unresolved": "unres",
        "is_dependent_type": "dep",
        "direction": "dir",
        "truncated": "trunc",
        "nodes_returned": "nodes",
        "completeness": "complete",
        "completeness_note": "note",
    }

    def abbreviate(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {key_map.get(k, k): abbreviate(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [abbreviate(item) for item in obj]
        return obj

    compact = abbreviate(hierarchy)
    return json.dumps(compact, indent=None, separators=(",", ":"))


def _format_cpp_pseudocode(hierarchy: Dict[str, Any], include_meta: bool = False) -> str:
    """Format hierarchy as C++ pseudocode.

    Outputs classes in topological order (bases before derived) with
    inheritance relationships shown via C++ syntax.
    """
    classes = hierarchy.get("classes", {})
    queried_class = hierarchy.get("queried_class", "Unknown")
    truncated = hierarchy.get("truncated", False)

    if not classes:
        result = f"// No hierarchy data for: {queried_class}"
        if truncated:
            result += "\n// Note: Hierarchy was truncated (max_nodes/max_depth limit)"
        return result

    # Build dependency graph for topological sort
    # We want: bases appear before derived classes
    in_degree: Dict[str, int] = dict.fromkeys(classes, 0)
    dependents: Dict[str, List[str]] = {name: [] for name in classes}

    for name, info in classes.items():
        bases = info.get("base_classes", [])
        for base in bases:
            if base in classes:
                dependents[base].append(name)
                in_degree[name] += 1

    # Topological sort using Kahn's algorithm
    queue = [name for name, deg in in_degree.items() if deg == 0]
    sorted_names: List[str] = []
    unresolved_bases: Set[str] = set()

    while queue:
        # Sort for deterministic output
        queue.sort()
        current = queue.pop(0)
        sorted_names.append(current)

        for dependent in dependents[current]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    # Collect any remaining (circular dependencies)
    remaining = [name for name in classes if name not in sorted_names]
    remaining.sort()
    sorted_names.extend(remaining)

    # Find bases that are not in the classes dict (external/unresolved)
    for _name, info in classes.items():
        for base in info.get("base_classes", []):
            if base not in classes:
                unresolved_bases.add(base)

    # Generate C++ code lines
    lines: List[str] = []
    lines.append(f"// Class hierarchy for: {queried_class}")
    if truncated:
        lines.append("// Note: Hierarchy was truncated (max_nodes/max_depth limit)")
    lines.append("")

    # Forward declarations for unresolved bases
    if unresolved_bases:
        for base in sorted(unresolved_bases):
            lines.append(f"class {base};")
        lines.append("")

    # Class definitions in topological order
    for name in sorted_names:
        info = classes[name]
        class_line = _build_class_declaration(name, info)
        lines.append(class_line)

        if include_meta:
            # Add metadata as comments
            kind = info.get("kind", "class")
            is_project = info.get("is_project", False)
            meta_parts = [f"kind: {kind}", f"project: {is_project}"]

            if info.get("is_unresolved"):
                meta_parts.append("unresolved: true")
            if info.get("is_dependent_type"):
                meta_parts.append("dependent: true")

            lines.append(f"  // {', '.join(meta_parts)}")

    if truncated:
        lines.append("")
        lines.append("// [Truncated - increase max_nodes/max_depth for full hierarchy]")

    return "\n".join(lines)


def _build_class_declaration(name: str, info: Dict[str, Any]) -> str:
    """Build a C++ class declaration line.

    Examples:
        class Foo;
        class Bar: public Base {};
        template <typename A> class Impl: public Base<A> {};
    """
    kind = info.get("kind", "class")
    bases = info.get("base_classes", [])

    # Determine if this is a template
    is_template = kind in ("class_template", "struct_template") or "<" in name

    # Simple name (without template args for the declaration)
    simple_name = name
    if "<" in name and not name.endswith(">"):
        # Handle dependent types
        simple_name = name

    # Build class declaration
    if is_template and "<" in name:
        # Extract template parameters if present in name
        decl = f"class {simple_name}"
    else:
        decl = f"class {simple_name}"

    # Add inheritance
    if bases:
        base_list = ", ".join(f"public {base}" for base in bases)
        decl += f": {base_list}"

    # Close declaration
    decl += " {};"

    return decl


def format_hierarchy_error(error_msg: str, output_format: str) -> str:
    """Format an error message in the requested format."""
    if output_format in ("cpp", "cpp_with_meta"):
        return f"// Error: {error_msg}"

    if output_format == "compact":
        import json

        return json.dumps({"err": error_msg})

    import json

    return json.dumps({"error": error_msg})
