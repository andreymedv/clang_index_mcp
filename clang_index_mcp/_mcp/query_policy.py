"""Application-layer query policies: search scope parsing, result metadata, and tool readiness."""

from typing import Any, Dict, List, Optional

from mcp.types import TextContent

from .context import ctx
from .state_manager import AnalyzerStateManager, EnhancedQueryResult
from .tool_handlers.policy_tools import check_query_policy

_VALID_SEARCH_SCOPES = ("project_code_only", "include_external_libraries")


def _parse_search_scope(arguments: Dict[str, Any]) -> bool:
    """Convert search_scope string enum to project_only bool.

    Returns True (project_only) for 'project_code_only' (default),
    False for 'include_external_libraries'.
    Raises ValueError for invalid values.
    """
    scope: str = arguments.get("search_scope", "project_code_only")
    if scope not in _VALID_SEARCH_SCOPES:
        raise ValueError(
            f"Invalid search_scope '{scope}'. " f"Must be one of: {', '.join(_VALID_SEARCH_SCOPES)}"
        )
    return bool(scope == "project_code_only")


def _create_search_result(
    data: Any,
    state_manager: AnalyzerStateManager,
    tool_name: str,
    max_results: Optional[int] = None,
    total_count: Optional[int] = None,
    fallback: Any = None,
    empty_suggestions: Optional[List[str]] = None,
) -> EnhancedQueryResult:
    """
    Create an EnhancedQueryResult with appropriate metadata based on special conditions.

    Design principle: Silence = Success. Metadata only appears for special conditions
    that require LLM guidance (empty, truncated, large, partial).

    Args:
        data: Query result data (list or dict with lists)
        state_manager: State manager for checking indexing status
        tool_name: Name of the tool (for customized messages)
        max_results: If specified, max_results limit was applied
        total_count: Total count before truncation (when max_results is specified)
        fallback: Optional FallbackResult from smart_fallback module
        empty_suggestions: Custom suggestions for the empty-result case.  When None,
        create_empty() uses its own default "search" suggestions.  Pass an explicit
        list (including []) to override those defaults.

    Returns:
        EnhancedQueryResult with appropriate metadata
    """
    # Priority 1: Check for partial indexing (always takes precedence)
    if not state_manager.is_fully_indexed():
        return EnhancedQueryResult.create_from_state(data, state_manager, tool_name)

    # Calculate result count for both list and dict data
    if isinstance(data, list):
        result_count = len(data)
    elif isinstance(data, dict):
        # For search_symbols which returns {"classes": [...], "functions": [...]}
        result_count = sum(len(v) for v in data.values() if isinstance(v, list))
    else:
        result_count = 0

    # Priority 2: Check for empty results (with smart fallback if available)
    if result_count == 0:
        return EnhancedQueryResult.create_empty(
            data, suggestions=empty_suggestions, fallback=fallback
        )

    # Priority 3: Check for truncation (max_results was specified and applied)
    if max_results is not None and total_count is not None and total_count > max_results:
        return EnhancedQueryResult.create_truncated(data, result_count, total_count)

    # Priority 4: Check for large result set (>20 results without max_results)
    if max_results is None and result_count > EnhancedQueryResult.LARGE_RESULT_THRESHOLD:
        return EnhancedQueryResult.create_large(data, result_count)

    # Default: Normal result (no metadata - silence = success)
    return EnhancedQueryResult.create_normal(data)


def _check_tool_readiness(name: str) -> Optional[List[TextContent]]:
    """
    Check if a tool is ready to be executed based on current analyzer state.
    Returns None if ready, or a List[TextContent] with an error message if not.
    """
    # Policy check and readiness for query tools
    query_tools = {
        "search_classes",
        "search_functions",
        "get_class_info",
        "get_type_alias_info",
        "search_symbols",
        "find_in_file",
        "get_class_hierarchy",
        "find_incoming_calls",
        "get_outgoing_calls",
        "get_call_path",
        "get_call_sites",
    }

    if name in query_tools:
        if ctx.analyzer is None:
            return [
                TextContent(
                    type="text",
                    text="Error: Project directory not set. Please use 'set_project_directory' first with the path to your C++ project.",
                )
            ]
        if not ctx.state_manager.is_ready_for_queries():
            return [
                TextContent(
                    type="text",
                    text="Error: Project is not ready for queries yet. Use 'sync_project' to start indexing or check status.",
                )
            ]

        allowed, policy_message = check_query_policy(name)
        if not allowed:
            return [TextContent(type="text", text=policy_message)]

    # Check for other tools (refresh_project, wait_for_indexing)
    if name in ("refresh_project", "wait_for_indexing") and ctx.analyzer is None:
        # For refresh_project, we'll try to resume inside the handler
        if name == "wait_for_indexing":
            return [
                TextContent(
                    type="text",
                    text="Error: Project directory not set. Please use 'set_project_directory' first.",
                )
            ]

    return None
