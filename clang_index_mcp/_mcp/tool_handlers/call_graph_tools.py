"""Call-graph MCP tool handlers."""

import asyncio
import json
from typing import Any, Dict, List, Optional

from mcp.types import TextContent

from .. import cpp_mcp_server as _server
from ..response_formatters import suggestions


async def _handle_find_incoming_calls(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = _server.analyzer
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    function_name = str(arguments["function_name"])
    class_name = str(arguments.get("class_name", ""))
    max_results = arguments.get("max_results", None)
    project_only = _server._parse_search_scope(arguments)
    # Run synchronous method in executor to avoid blocking event loop
    results = await loop.run_in_executor(
        None,
        lambda: analyzer.find_incoming_calls(function_name, class_name, project_only=project_only),
    )
    # Results is dict with "callers" list - use that for metadata logic
    callers_list = results.get("callers", []) if isinstance(results, dict) else []
    # 3-case empty-result logic (internal flags stripped before sending to LLM):
    #   not found            -> default "check spelling" suggestions  (None)
    #   found, no callers    -> no hints at all                        ([])
    #   found, ext. callers  -> auto-expand to include external results
    function_found = results.pop("_function_found", False) if isinstance(results, dict) else False
    has_any_in_graph = (
        results.pop("_has_any_in_graph", False) if isinstance(results, dict) else False
    )
    target_qualified_name = (
        results.pop("_target_qualified_name", None) if isinstance(results, dict) else None
    )
    # Auto-expand: when project_only=True yields 0 results but external callers
    # exist, re-fetch with project_only=False so the LLM gets useful data without
    # needing to interpret a suggestion and issue a second tool call.
    search_note = None
    if project_only and not callers_list and function_found and has_any_in_graph:
        expanded = await loop.run_in_executor(
            None,
            lambda: analyzer.find_incoming_calls(function_name, class_name, project_only=False),
        )
        # Strip internal flags from expanded results
        expanded.pop("_function_found", None)
        expanded.pop("_has_any_in_graph", None)
        expanded.pop("_target_qualified_name", None)
        results = expanded
        callers_list = results.get("callers", [])
        ext_count = len(callers_list)
        search_note = (
            f"Project-only search yielded 0 results. "
            f"Auto-expanded to include external libraries "
            f"({ext_count} external caller{'s' if ext_count != 1 else ''} found)."
        )
    total_count = len(callers_list)
    # Apply truncation if max_results specified
    if max_results is not None and len(callers_list) > max_results:
        results["callers"] = callers_list[:max_results]
    empty_suggestions: Optional[List[str]] = None
    if not function_found:
        pass  # None -> default "check spelling / broaden pattern"
    elif has_any_in_graph:
        empty_suggestions = []  # auto-expanded above; no hint needed
    else:
        empty_suggestions = []  # genuinely no callers -> no hints
    # Wrap with appropriate metadata
    enhanced_result = _server._create_search_result(
        results.get("callers", []),
        _server.state_manager,
        "find_incoming_calls",
        max_results,
        total_count,
        empty_suggestions=empty_suggestions,
    )
    enhanced_result.next_steps = suggestions.for_find_incoming_calls(
        function_name, results, qualified_name=target_qualified_name
    )
    # Merge metadata into results dict
    output = results.copy() if isinstance(results, dict) else {"callers": results}
    enhanced_dict = enhanced_result.to_dict()
    if "metadata" in enhanced_dict:
        output["metadata"] = enhanced_dict["metadata"]
    if search_note:
        output["search_note"] = search_note
    return [TextContent(type="text", text=json.dumps(output, indent=2))]


async def _handle_get_outgoing_calls(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = _server.analyzer
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    function_name = str(arguments["function_name"])
    class_name = str(arguments.get("class_name", ""))
    max_results = arguments.get("max_results", None)
    project_only = _server._parse_search_scope(arguments)
    # Run synchronous method in executor to avoid blocking event loop
    results = await loop.run_in_executor(
        None,
        lambda: analyzer.find_callees(function_name, class_name, project_only=project_only),
    )
    # Results is dict with "callees" list - use that for metadata logic
    callees_list = results.get("callees", []) if isinstance(results, dict) else []
    # 3-case empty-result logic (internal flags stripped before sending to LLM):
    #   not found               -> default "check spelling" suggestions  (None)
    #   found, no callees       -> no hints at all                        ([])
    #   found, ext. callees     -> auto-expand to include external results
    function_found = results.pop("_function_found", False) if isinstance(results, dict) else False
    has_any_in_graph = (
        results.pop("_has_any_in_graph", False) if isinstance(results, dict) else False
    )
    target_qualified_name = (
        results.pop("_target_qualified_name", None) if isinstance(results, dict) else None
    )
    # Auto-expand: when project_only=True yields 0 results but external callees
    # exist, re-fetch with project_only=False so the LLM gets useful data without
    # needing to interpret a suggestion and issue a second tool call.
    search_note = None
    if project_only and not callees_list and function_found and has_any_in_graph:
        expanded = await loop.run_in_executor(
            None,
            lambda: analyzer.find_callees(function_name, class_name, project_only=False),
        )
        # Strip internal flags from expanded results
        expanded.pop("_function_found", None)
        expanded.pop("_has_any_in_graph", None)
        expanded.pop("_target_qualified_name", None)
        results = expanded
        callees_list = results.get("callees", [])
        ext_count = len(callees_list)
        search_note = (
            f"Project-only search yielded 0 results. "
            f"Auto-expanded to include external libraries "
            f"({ext_count} external callee{'s' if ext_count != 1 else ''} found)."
        )
    total_count = len(callees_list)
    # Apply truncation if max_results specified
    if max_results is not None and len(callees_list) > max_results:
        results["callees"] = callees_list[:max_results]
    empty_suggestions: Optional[List[str]] = None
    if not function_found:
        pass  # None -> default "check spelling / broaden pattern"
    elif has_any_in_graph:
        empty_suggestions = []  # auto-expanded above; no hint needed
    else:
        empty_suggestions = []  # genuinely calls nothing -> no hints
    # Wrap with appropriate metadata
    enhanced_result = _server._create_search_result(
        results.get("callees", []),
        _server.state_manager,
        "get_outgoing_calls",
        max_results,
        total_count,
        empty_suggestions=empty_suggestions,
    )
    enhanced_result.next_steps = suggestions.for_get_outgoing_calls(
        function_name, results, qualified_name=target_qualified_name
    )
    # Merge metadata into results dict
    output = results.copy() if isinstance(results, dict) else {"callees": results}
    enhanced_dict = enhanced_result.to_dict()
    if "metadata" in enhanced_dict:
        output["metadata"] = enhanced_dict["metadata"]
    if search_note:
        output["search_note"] = search_note
    return [TextContent(type="text", text=json.dumps(output, indent=2))]


async def _handle_get_call_sites(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = _server.analyzer
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
    analyzer = _server.analyzer
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    from_function = arguments["from_function"]
    to_function = arguments["to_function"]
    max_depth = arguments.get("max_depth", 10)
    # Run synchronous method in executor to avoid blocking event loop
    with _server.state_manager.tool_execution():
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
