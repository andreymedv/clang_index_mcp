"""
Conditional next-step suggestions for MCP tool responses.

Design principle: hints only appear when returned data warrants them.
Each function returns list[str] — empty list means no suggestions (no metadata added).
"""

from typing import Any, Dict, List


def _strip_template_args(name: str) -> str:
    """Strip template arguments from a type name: 'Foo<T>' -> 'Foo'."""
    idx = name.find("<")
    if idx != -1:
        return name[:idx].strip()
    return name


def for_get_class_info(result_data: Dict[str, Any]) -> List[str]:
    """Generate next-step suggestions for get_class_info results.

    Args:
        result_data: The dict returned by get_class_info (must be truthy / non-error)

    Returns:
        List of suggestion strings, empty if none warranted.
    """
    if not result_data or "error" in result_data:
        return []

    hints: List[str] = []

    # Suggest exploring base classes (up to 3)
    base_classes: List[str] = result_data.get("base_classes") or []
    for base in base_classes[:3]:
        clean = _strip_template_args(base)
        if clean:
            hints.append(f"get_class_info('{clean}') — explore base class")

    # Suggest finding implementations of pure virtual methods
    methods: List[Dict[str, Any]] = result_data.get("methods") or []
    has_pure_virtual = any("pure_virtual" in (m.get("attributes") or []) for m in methods)
    if has_pure_virtual:
        class_name = result_data.get("qualified_name") or ""
        hints.append(
            f"search_functions(is_definition=True, parent_class='DerivedClass') "
            f"— find concrete implementations of {class_name}'s pure virtual methods"
        )

    # Suggest filtering when there are many methods
    if len(methods) > 10:
        class_name = result_data.get("qualified_name") or ""
        hints.append(
            f"search_functions(pattern='...', parent_class='{class_name}') "
            f"— filter methods by name pattern"
        )

    return hints


def for_search_classes(results: List[Dict[str, Any]]) -> List[str]:
    """Generate next-step suggestions for search_classes results.

    Args:
        results: The list returned by search_classes (non-empty)

    Returns:
        List of suggestion strings, empty if none warranted.
    """
    if not results:
        return []

    hints: List[str] = []

    if len(results) <= 3:
        # Few results — suggest get_class_info for each
        for item in results:
            qname = item.get("qualified_name") or item.get("name") or ""
            if qname:
                hints.append(f"get_class_info('{qname}') — get full class details")
    else:
        # Many results — suggest get_class_info for top match only
        top = results[0]
        qname = top.get("qualified_name") or top.get("name") or ""
        if qname:
            hints.append(f"get_class_info('{qname}') — get full details for top match")

    return hints


def for_search_functions(results: List[Dict[str, Any]]) -> List[str]:
    """Generate next-step suggestions for search_functions results.

    Args:
        results: The list returned by search_functions (non-empty)

    Returns:
        List of suggestion strings, empty if none warranted.
    """
    if not results:
        return []

    hints: List[str] = []

    # Collect unique parent classes (up to 2)
    seen: List[str] = []
    for item in results:
        parent = item.get("parent_class") or ""
        if parent and parent not in seen:
            seen.append(parent)
        if len(seen) >= 2:
            break

    for parent in seen:
        hints.append(f"get_class_info('{parent}') — explore owning class")

    return hints


def for_find_callers(function_name: str, result_data: Dict[str, Any]) -> List[str]:
    """Generate next-step suggestions for find_callers results.

    Args:
        function_name: The function name that was queried
        result_data: The full dict returned by find_callers (with 'callers' list)

    Returns:
        List of suggestion strings, empty if none warranted.
    """
    callers: List[Any] = result_data.get("callers") or [] if isinstance(result_data, dict) else []
    if not callers:
        return []

    return [f"get_call_sites('{function_name}') — get exact file:line:column call locations"]


def for_find_callees(function_name: str, result_data: Dict[str, Any]) -> List[str]:
    """Generate next-step suggestions for find_callees results.

    Args:
        function_name: The function name that was queried
        result_data: The full dict returned by find_callees (with 'callees' list)

    Returns:
        List of suggestion strings, empty if none warranted.
    """
    callees: List[Any] = result_data.get("callees") or [] if isinstance(result_data, dict) else []
    if not callees:
        return []

    return [
        f"get_call_sites('{function_name}') — get exact call locations within the function body"
    ]
