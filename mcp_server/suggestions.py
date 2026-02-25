"""
Conditional next-step suggestions for MCP tool responses.

Design principle: hints only appear when returned data warrants them.
Each function returns list[str] — empty list means no suggestions (no metadata added).
"""

from typing import Any, Dict, List, Optional


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
            f"search_functions(is_definition=True, parent_class='<DerivedClassName>') "
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


def for_find_callers(
    function_name: str,
    result_data: Dict[str, Any],
    qualified_name: Optional[str] = None,
) -> List[str]:
    """Generate next-step suggestions for find_callers results.

    Args:
        function_name: The function name that was queried
        result_data: The full dict returned by find_callers (with 'callers' list)
        qualified_name: Fully qualified name of the resolved function (preferred for hint)

    Returns:
        List of suggestion strings, empty if none warranted.
    """
    callers: List[Any] = result_data.get("callers") or [] if isinstance(result_data, dict) else []
    if not callers:
        return []

    name_to_use = qualified_name or function_name
    return [f"find_callees('{name_to_use}') — see what this function calls (complements callers view)"]


def for_find_callees(
    function_name: str,
    result_data: Dict[str, Any],
    qualified_name: Optional[str] = None,
) -> List[str]:
    """Generate next-step suggestions for find_callees results.

    Args:
        function_name: The function name that was queried
        result_data: The full dict returned by find_callees (with 'callees' list)
        qualified_name: Fully qualified name of the resolved function (preferred for hint)

    Returns:
        List of suggestion strings, empty if none warranted.
    """
    callees: List[Any] = result_data.get("callees") or [] if isinstance(result_data, dict) else []
    if not callees:
        return []

    name_to_use = qualified_name or function_name
    return [f"get_call_sites('{name_to_use}') — get exact call locations within the function body"]


def for_find_callers_external(
    function_name: str,
    qualified_name: Optional[str] = None,
) -> List[str]:
    """Suggestion when find_callers finds the function but all callers are external code.

    Args:
        function_name: The function name that was queried
        qualified_name: Fully qualified name (preferred for hint)

    Returns:
        List with one actionable suggestion string.
    """
    name = qualified_name or function_name
    return [
        f"Function found but all callers are in external code; "
        f"call find_callers('{name}', project_only=false) to list them"
    ]


def for_find_callees_external(
    function_name: str,
    qualified_name: Optional[str] = None,
) -> List[str]:
    """Suggestion when find_callees finds the function but all callees are external libraries.

    Args:
        function_name: The function name that was queried
        qualified_name: Fully qualified name (preferred for hint)

    Returns:
        List with one actionable suggestion string.
    """
    name = qualified_name or function_name
    return [
        f"Function found but all callees are in external libraries (stdlib, third-party); "
        f"call find_callees('{name}', project_only=false) to list them"
    ]


def for_get_call_sites_empty(
    function_name: str,
    class_name: str = "",
) -> List[str]:
    """Suggestion when get_call_sites returns no call sites.

    Guides the caller to use find_callees to distinguish between 'no body',
    'leaf function', and 'all callees are external'.

    Args:
        function_name: The function name that was queried
        class_name: Optional class name used to build a more specific hint name

    Returns:
        List with one actionable suggestion string.
    """
    name = f"{class_name}::{function_name}" if class_name else function_name
    return [
        f"No call sites found within '{name}'. "
        f"Call find_callees('{name}') to check why — "
        "if it reports 'all callees outside project', "
        "the function calls only external libraries; "
        "use project_only=false to list them."
    ]


def for_get_call_path_empty(
    from_function: str,
    to_function: str,
    max_depth: int,
) -> List[str]:
    """Suggestion when get_call_path returns no paths.

    Args:
        from_function: The source function name
        to_function: The target function name
        max_depth: The max depth that was used

    Returns:
        List with one actionable suggestion string.
    """
    return [
        f"No call path found from '{from_function}' to '{to_function}' "
        f"within max_depth={max_depth}. "
        "Try increasing max_depth or verify both functions exist "
        "with search_functions."
    ]
