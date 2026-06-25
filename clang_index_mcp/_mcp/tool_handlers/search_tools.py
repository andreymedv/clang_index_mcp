"""Search-related MCP tool handlers."""

import asyncio
import json
from typing import Any, Dict, List

from mcp.types import TextContent

from ..context import ctx
from ..query_policy import _create_search_result, _parse_search_scope
from ..state_manager import EnhancedQueryResult
from ..response_formatters import suggestions


async def _handle_search_classes(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = ctx.analyzer
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    project_only = _parse_search_scope(arguments)
    pattern = arguments["symbol_name"]
    file_name = arguments.get("file_name", None)
    namespace = arguments.get("namespace", None)
    max_results = arguments.get("max_results", None)
    include_base_classes = arguments.get("include_base_classes", True)

    # Run synchronous method in executor to avoid blocking event loop
    with ctx.state_manager.tool_execution():
        raw_results = await loop.run_in_executor(
            None,
            lambda: analyzer.search_classes(
                pattern,
                project_only,
                file_name,
                namespace,
                max_results,
                include_base_classes,
            ),
        )

    fallback = analyzer.pop_last_fallback()
    # Handle tuple return (results, total_count) when max_results is specified
    if isinstance(raw_results, tuple):
        results, total_count = raw_results
    else:
        results, total_count = raw_results, None

    # Wrap with appropriate metadata based on special conditions
    enhanced_result = _create_search_result(
        results, ctx.state_manager, "search_classes", max_results, total_count, fallback
    )
    if results:
        enhanced_result.next_steps = suggestions.for_search_classes(
            results,
            pattern=pattern,
            file_name=file_name,
            namespace=namespace,
        )
    return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]


async def _handle_search_functions(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = ctx.analyzer
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    project_only = _parse_search_scope(arguments)
    class_name = arguments.get("class_name", None)
    file_name = arguments.get("file_name", None)
    namespace = arguments.get("namespace", None)
    pattern = arguments["symbol_name"]
    max_results = arguments.get("max_results", None)
    signature_pattern = arguments.get("signature_pattern", None)
    include_attributes = arguments.get("include_attributes", False)

    # Run synchronous method in executor to avoid blocking event loop
    with ctx.state_manager.tool_execution():
        raw_results = await loop.run_in_executor(
            None,
            lambda: analyzer.search_functions(
                pattern,
                project_only,
                class_name,
                file_name,
                namespace,
                max_results,
                signature_pattern,
                include_attributes,
            ),
        )

    fallback = analyzer.pop_last_fallback()
    # Handle tuple return (results, total_count) when max_results is specified
    if isinstance(raw_results, tuple):
        results, total_count = raw_results
    else:
        results, total_count = raw_results, None

    # Wrap with appropriate metadata based on special conditions
    enhanced_result = _create_search_result(
        results, ctx.state_manager, "search_functions", max_results, total_count, fallback
    )
    if results:
        enhanced_result.next_steps = suggestions.for_search_functions(results)
    return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]


async def _handle_get_class_info(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = ctx.analyzer
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    class_name = str(arguments["class_name"])
    # Run synchronous method in executor to avoid blocking event loop
    result = await loop.run_in_executor(None, lambda: analyzer.get_class_info(class_name))
    # Wrap with metadata (even if not found)
    enhanced_result = EnhancedQueryResult.create_from_state(
        result, ctx.state_manager, "get_class_info"
    )
    if result and "error" not in (result or {}):
        enhanced_result.next_steps = suggestions.for_get_class_info(result)
    return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]


async def _handle_get_type_alias_info(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = ctx.analyzer
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    type_name = arguments["type_name"]
    # Run synchronous method in executor to avoid blocking event loop
    result = await loop.run_in_executor(None, lambda: analyzer.get_type_alias_info(type_name))
    # Wrap with metadata
    enhanced_result = EnhancedQueryResult.create_from_state(
        result, ctx.state_manager, "get_type_alias_info"
    )
    return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]


async def _handle_search_symbols(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = ctx.analyzer
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    pattern = arguments["symbol_name"]
    project_only = _parse_search_scope(arguments)
    symbol_types = arguments.get("symbol_types", None)
    namespace = arguments.get("namespace", None)
    max_results = arguments.get("max_results", None)
    signature_pattern = arguments.get("signature_pattern", None)
    # Run synchronous method in executor to avoid blocking event loop
    raw_results = await loop.run_in_executor(
        None,
        lambda: analyzer.search_symbols(
            pattern,
            project_only,
            symbol_types,
            namespace,
            max_results,
            signature_pattern,
        ),
    )
    fallback = analyzer.pop_last_fallback()
    # Handle tuple return (results, total_count) when max_results is specified
    if isinstance(raw_results, tuple):
        results, total_count = raw_results
    else:
        results, total_count = raw_results, None
    # Wrap with appropriate metadata based on special conditions
    enhanced_result = _create_search_result(
        results, ctx.state_manager, "search_symbols", max_results, total_count, fallback
    )
    return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]


async def _handle_find_in_file(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = ctx.analyzer
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    file_path = arguments["file_path"]
    pattern = arguments["pattern"]
    # Run synchronous method in executor to avoid blocking event loop
    with ctx.state_manager.tool_execution():
        results = await loop.run_in_executor(
            None, lambda: analyzer.find_in_file(file_path, pattern)
        )
    # find_in_file returns {"results": [...], "matched_files": [...], ...}
    # Count the actual symbol results for metadata logic
    result_list = results.get("results", []) if isinstance(results, dict) else []
    # Wrap with appropriate metadata based on special conditions
    # Use _create_search_result with the result list for counting
    enhanced_result = _create_search_result(
        result_list, ctx.state_manager, "find_in_file", None, None
    )
    # But return the full results dict (with matched_files, suggestions, etc.)
    # Merge the metadata into the results dict
    output = results.copy() if isinstance(results, dict) else {"results": results}
    enhanced_dict = enhanced_result.to_dict()
    if "metadata" in enhanced_dict:
        output["metadata"] = enhanced_dict["metadata"]
    return [TextContent(type="text", text=json.dumps(output, indent=2))]
