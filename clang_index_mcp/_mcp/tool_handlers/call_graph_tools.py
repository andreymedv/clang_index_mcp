"""Call-graph MCP tool handlers."""

import asyncio
import json
from typing import Any, Callable, Dict, List, Optional

from mcp.types import TextContent

from ..context import ctx
from ..query_policy import _create_search_result, _parse_search_scope
from ..response_formatters import suggestions


async def _handle_call_graph_query(
    arguments: Dict[str, Any],
    analyzer_method: Callable,
    result_key: str,
    tool_name: str,
    entity_name: str,
    suggestion_func: Callable,
) -> List[TextContent]:
    """Generic handler for call graph queries (incoming/outgoing calls).

    Args:
        arguments: MCP tool arguments
        analyzer_method: Analyzer method to call (e.g., find_incoming_calls)
        result_key: Key for result list in response (e.g., "callers", "callees")
        tool_name: Tool name for metadata (e.g., "find_incoming_calls")
        entity_name: Entity name for messages (e.g., "caller", "callee")
        suggestion_func: Suggestion function to call
    """
    analyzer = ctx.analyzer
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    function_name = str(arguments["function_name"])
    class_name = str(arguments.get("class_name", ""))
    max_results = arguments.get("max_results", None)
    project_only = _parse_search_scope(arguments)

    # Run synchronous method in executor to avoid blocking event loop
    results = await loop.run_in_executor(
        None,
        lambda: analyzer_method(function_name, class_name, project_only=project_only),
    )

    # Extract result list and internal flags
    result_list = results.get(result_key, []) if isinstance(results, dict) else []
    function_found = results.pop("_function_found", False) if isinstance(results, dict) else False
    has_any_in_graph = (
        results.pop("_has_any_in_graph", False) if isinstance(results, dict) else False
    )
    target_qualified_name = (
        results.pop("_target_qualified_name", None) if isinstance(results, dict) else None
    )

    # Auto-expand: when project_only=True yields 0 results but external results exist
    search_note = None
    if project_only and not result_list and function_found and has_any_in_graph:
        expanded = await loop.run_in_executor(
            None,
            lambda: analyzer_method(function_name, class_name, project_only=False),
        )
        # Strip internal flags from expanded results
        expanded.pop("_function_found", None)
        expanded.pop("_has_any_in_graph", None)
        expanded.pop("_target_qualified_name", None)
        results = expanded
        result_list = results.get(result_key, [])
        ext_count = len(result_list)
        search_note = (
            f"Project-only search yielded 0 results. "
            f"Auto-expanded to include external libraries "
            f"({ext_count} external {entity_name}{'s' if ext_count != 1 else ''} found)."
        )

    total_count = len(result_list)

    # Apply truncation if max_results specified
    if max_results is not None and len(result_list) > max_results:
        results[result_key] = result_list[:max_results]

    # Determine empty suggestions
    empty_suggestions: Optional[List[str]] = None
    if not function_found:
        pass  # None -> default "check spelling / broaden pattern"
    elif has_any_in_graph:
        empty_suggestions = []  # auto-expanded above; no hint needed
    else:
        empty_suggestions = []  # genuinely no results -> no hints

    # Wrap with appropriate metadata
    enhanced_result = _create_search_result(
        results.get(result_key, []),
        ctx.state_manager,
        tool_name,
        max_results,
        total_count,
        empty_suggestions=empty_suggestions,
    )
    enhanced_result.next_steps = suggestion_func(
        function_name, results, qualified_name=target_qualified_name
    )

    # Merge metadata into results dict
    output = results.copy() if isinstance(results, dict) else {result_key: results}
    enhanced_dict = enhanced_result.to_dict()
    if "metadata" in enhanced_dict:
        output["metadata"] = enhanced_dict["metadata"]
    if search_note:
        output["search_note"] = search_note
    return [TextContent(type="text", text=json.dumps(output, indent=2))]


async def _handle_find_incoming_calls(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = ctx.analyzer
    assert analyzer is not None
    return await _handle_call_graph_query(
        arguments=arguments,
        analyzer_method=analyzer.find_incoming_calls,
        result_key="callers",
        tool_name="find_incoming_calls",
        entity_name="caller",
        suggestion_func=suggestions.for_find_incoming_calls,
    )


async def _handle_get_outgoing_calls(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = ctx.analyzer
    assert analyzer is not None
    return await _handle_call_graph_query(
        arguments=arguments,
        analyzer_method=analyzer.find_callees,
        result_key="callees",
        tool_name="get_outgoing_calls",
        entity_name="callee",
        suggestion_func=suggestions.for_get_outgoing_calls,
    )


async def _handle_get_call_sites(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = ctx.analyzer
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    function_name = arguments["function_name"]
    class_name = arguments.get("class_name", "")
    # Run synchronous method in executor to avoid blocking event loop
    call_sites = await loop.run_in_executor(
        None, lambda: analyzer.get_call_sites(function_name, class_name)
    )
    output_sites: Dict[str, Any] = {"call_sites": call_sites}
    if not call_sites:
        output_sites["metadata"] = {
            "suggestions": suggestions.for_get_call_sites_empty(function_name, class_name),
        }
    return [TextContent(type="text", text=json.dumps(output_sites, indent=2))]


async def _handle_get_call_path(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = ctx.analyzer
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    from_function = arguments["from_function"]
    to_function = arguments["to_function"]
    max_depth = arguments.get("max_depth", 10)
    # Run synchronous method in executor to avoid blocking event loop
    with ctx.state_manager.tool_execution():
        paths = await loop.run_in_executor(
            None, lambda: analyzer.get_call_path(from_function, to_function, max_depth)
        )
    output_paths: Dict[str, Any] = {"paths": paths}
    if not paths:
        output_paths["metadata"] = {
            "suggestions": suggestions.for_get_call_path_empty(
                from_function, to_function, max_depth
            ),
        }
    return [TextContent(type="text", text=json.dumps(output_paths, indent=2))]
