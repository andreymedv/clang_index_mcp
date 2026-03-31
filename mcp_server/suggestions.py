"""Conditional next-step suggestions for MCP tool responses."""

import re
from typing import Any, Dict, List, Optional


def for_get_class_info(result_data: Dict[str, Any]) -> List[str]:
    """Generate next-step suggestions for get_class_info results (public: get_class_info).

    Args:
        result_data: The dict returned by get_class_info (must be truthy / non-error)

    Returns:
        List of suggestion strings, empty if none warranted.
    """
    if not result_data or "error" in result_data:
        return []

    hints: List[str] = []

    # Suggest finding implementations of pure virtual methods
    methods: List[Dict[str, Any]] = result_data.get("methods") or []
    has_pure_virtual = any("pure_virtual" in (m.get("attributes") or []) for m in methods)
    if has_pure_virtual:
        class_name = result_data.get("qualified_name") or ""
        hints.append(
            f"get_class_hierarchy('{class_name}') — inspect the full implementation tree "
            f"and concrete subclasses"
        )

    notes = result_data.get("notes")
    if isinstance(notes, str):
        match = re.search(r"Private implementation class is ([A-Za-z_][\w:]*)", notes)
        if match:
            impl_class = match.group(1)
            hints.append(
                f"get_class_info('{impl_class}') — inspect the private implementation "
                f"class behind this PIMPL interface"
            )

    # Suggest filtering when there are many methods
    if len(methods) > 10:
        class_name = result_data.get("qualified_name") or ""
        hints.append(
            f"find_symbols_by_pattern(pattern='...', target_type='functions_and_methods_only') "
            f"— filter methods by name pattern"
        )

    return hints


def for_search_classes(
    results: List[Dict[str, Any]],
    pattern: str = "",
    file_name: Optional[str] = None,
    namespace: Optional[str] = None,
) -> List[str]:
    """Generate next-step suggestions for search_classes results (public: find_symbols_by_pattern).

    Args:
        results: The list returned by search_classes (non-empty)

    Returns:
        List of suggestion strings, empty if none warranted.
    """
    if not results:
        return []

    if pattern == "" or file_name or namespace:
        return []

    hints: List[str] = []
    if len(results) > 3:
        # Many results — suggest get_class_info for top match only.
        # For small result sets, avoid nudging the model into extra follow-up
        # calls when the search already answered the user's discovery task.
        top = results[0]
        qname = top.get("qualified_name") or top.get("name") or ""
        if qname:
            hints.append(f"get_class_info('{qname}') — get full details for top match")

    return hints


def for_search_functions(results: List[Dict[str, Any]]) -> List[str]:
    """Generate next-step suggestions for search_functions results (public: find_symbols_by_pattern).

    Args:
        results: The list returned by search_functions (non-empty)

    Returns:
        List of suggestion strings, empty if none warranted.
    """
    if not results:
        return []

    # Function searches often precede call-graph queries. Avoid steering models
    # toward class-info detours unless the user explicitly asked about the class.
    return []


def for_get_incoming_calls(
    function_name: str,
    result_data: Dict[str, Any],
    qualified_name: Optional[str] = None,
) -> List[str]:
    """Generate next-step suggestions for get_incoming_calls results (public: find_callers).

    Args:
        function_name: The function name that was queried
        result_data: The full dict returned by get_incoming_calls (with 'callers' list)
        qualified_name: Fully qualified name of the resolved function (preferred for hint)

    Returns:
        List of suggestion strings, empty if none warranted.
    """
    callers: List[Any] = result_data.get("callers") or [] if isinstance(result_data, dict) else []
    if not callers:
        return []

    name_to_use = qualified_name or function_name
    return [
        f"get_functions_called_by('{name_to_use}') — see what this function calls "
        f"(complements incoming calls view)"
    ]


def for_get_outgoing_calls(
    function_name: str,
    result_data: Dict[str, Any],
    qualified_name: Optional[str] = None,
) -> List[str]:
    """Generate next-step suggestions for get_outgoing_calls results (public: get_functions_called_by).

    Args:
        function_name: The function name that was queried
        result_data: The full dict returned by get_outgoing_calls (with 'callees' list)
        qualified_name: Fully qualified name of the resolved function (preferred for hint)

    Returns:
        List of suggestion strings, empty if none warranted.
    """
    callees: List[Any] = result_data.get("callees") or [] if isinstance(result_data, dict) else []
    if not callees:
        return []

    name_to_use = qualified_name or function_name
    return [f"get_functions_called_by('{name_to_use}', return_format='exact_call_line_locations') — get exact call locations within the function body"]


def for_get_call_sites_empty(
    function_name: str,
    class_name: str = "",
) -> List[str]:
    """Suggestion when get_call_sites returns no call sites (via get_functions_called_by).

    Guides the caller to use get_functions_called_by to distinguish between 'no body',
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
        f"Call get_functions_called_by('{name}') to check why — "
        "if it reports 'all callees outside project', "
        "the function calls only external libraries; "
        "use search_scope='include_external_libraries' to list them."
    ]


def for_get_call_path_empty(
    from_function: str,
    to_function: str,
    max_depth: int,
) -> List[str]:
    """Suggestion when get_call_path returns no paths (public: trace_execution_path).

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
        "with find_symbols_by_pattern."
    ]
