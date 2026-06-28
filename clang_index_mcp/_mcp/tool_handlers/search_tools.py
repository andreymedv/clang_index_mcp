"""Search-related MCP tool handlers."""

import asyncio
import json
from typing import Any, Dict, List

from mcp.types import TextContent

from ..context import ctx
from ..query_policy import _create_search_result
from ..response_formatters import suggestions
from .execution_utils import execute_analyzer_search, execute_analyzer_query


async def _handle_search_classes(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = ctx.analyzer
    assert analyzer is not None
    return await execute_analyzer_search(
        arguments=arguments,
        analyzer_method=lambda project_only: analyzer.search_classes(
            arguments["symbol_name"],
            project_only,
            arguments.get("file_name"),
            arguments.get("namespace"),
            arguments.get("max_results"),
            arguments.get("include_base_classes", True),
        ),
        tool_name="search_classes",
        max_results=arguments.get("max_results"),
        next_steps_func=lambda results, **kw: suggestions.for_search_classes(
            results,
            pattern=kw.get("arguments", {}).get("symbol_name"),
            file_name=kw.get("arguments", {}).get("file_name"),
            namespace=kw.get("arguments", {}).get("namespace"),
        ),
    )


async def _handle_search_functions(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = ctx.analyzer
    assert analyzer is not None
    return await execute_analyzer_search(
        arguments=arguments,
        analyzer_method=lambda project_only: analyzer.search_functions(
            arguments["symbol_name"],
            project_only,
            arguments.get("class_name"),
            arguments.get("file_name"),
            arguments.get("namespace"),
            arguments.get("max_results"),
            arguments.get("signature_pattern"),
            arguments.get("include_attributes", False),
        ),
        tool_name="search_functions",
        max_results=arguments.get("max_results"),
        next_steps_func=lambda results, **kw: suggestions.for_search_functions(results),
    )


async def _handle_get_class_info(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = ctx.analyzer
    assert analyzer is not None
    return await execute_analyzer_query(
        arguments=arguments,
        analyzer_method=lambda: analyzer.get_class_info(str(arguments["class_name"])),
        tool_name="get_class_info",
        next_steps_func=lambda result, args: suggestions.for_get_class_info(result),
    )


async def _handle_get_type_alias_info(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = ctx.analyzer
    assert analyzer is not None
    return await execute_analyzer_query(
        arguments=arguments,
        analyzer_method=lambda: analyzer.get_type_alias_info(arguments["type_name"]),
        tool_name="get_type_alias_info",
    )


async def _handle_search_symbols(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = ctx.analyzer
    assert analyzer is not None
    return await execute_analyzer_search(
        arguments=arguments,
        analyzer_method=lambda project_only: analyzer.search_symbols(
            arguments["symbol_name"],
            project_only,
            arguments.get("symbol_types"),
            arguments.get("namespace"),
            arguments.get("max_results"),
            arguments.get("signature_pattern"),
        ),
        tool_name="search_symbols",
        max_results=arguments.get("max_results"),
        use_tool_execution_context=False,
    )


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
