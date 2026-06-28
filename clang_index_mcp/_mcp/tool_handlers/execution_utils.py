"""Utility functions for MCP tool handler execution.

Provides helpers to eliminate boilerplate in tool handlers:
- Async executor wrapping
- Result enhancement with metadata
- Common patterns for search and query operations
"""

import asyncio
import json
from typing import Any, Callable, Dict, List, Optional

from mcp.types import TextContent

from ..context import ctx
from ..query_policy import _create_search_result, _parse_search_scope
from ..state_manager import EnhancedQueryResult


async def execute_analyzer_search(
    arguments: Dict[str, Any],
    analyzer_method: Callable,
    tool_name: str,
    max_results: Optional[int] = None,
    use_tool_execution_context: bool = True,
    next_steps_func: Optional[Callable] = None,
) -> List[TextContent]:
    """Execute a search-style analyzer method and return enhanced results.

    This eliminates the common boilerplate pattern in search tool handlers:
    1. Get analyzer and event loop
    2. Parse search scope
    3. Execute in executor with optional tool_execution context
    4. Handle tuple returns (results, total_count)
    5. Wrap with metadata and suggestions

    Args:
        arguments: MCP tool arguments dict.
        analyzer_method: The analyzer method to call (must accept project_only as first arg).
        tool_name: Tool name for metadata (e.g., "search_classes").
        max_results: Optional max results limit.
        use_tool_execution_context: If True, wrap execution in state_manager.tool_execution().
        next_steps_func: Optional function to generate next_steps suggestions.
                        Receives (results, **arguments) and returns list of suggestions.

    Returns:
        List containing a single TextContent with JSON-formatted enhanced result.

    Example:
        async def _handle_search_classes(arguments):
            return await execute_analyzer_search(
                arguments=arguments,
                analyzer_method=lambda project_only, **kw: analyzer.search_classes(
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
                ),
            )
    """
    analyzer = ctx.analyzer
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    project_only = _parse_search_scope(arguments)

    # Execute analyzer method
    if use_tool_execution_context:
        with ctx.state_manager.tool_execution():
            raw_results = await loop.run_in_executor(
                None,
                lambda: analyzer_method(project_only=project_only),
            )
    else:
        raw_results = await loop.run_in_executor(
            None,
            lambda: analyzer_method(project_only=project_only),
        )

    # Handle fallback
    fallback = analyzer.pop_last_fallback()

    # Handle tuple return (results, total_count) when max_results is specified
    if isinstance(raw_results, tuple):
        results, total_count = raw_results
    else:
        results, total_count = raw_results, None

    # Wrap with metadata
    enhanced_result = _create_search_result(
        results, ctx.state_manager, tool_name, max_results, total_count, fallback
    )

    # Add next steps if provided and results exist
    if results and next_steps_func:
        enhanced_result.next_steps = next_steps_func(results, arguments=arguments)

    return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]


async def execute_analyzer_query(
    arguments: Dict[str, Any],
    analyzer_method: Callable,
    tool_name: str,
    next_steps_func: Optional[Callable] = None,
    result_transform_func: Optional[Callable] = None,
) -> List[TextContent]:
    """Execute a simple query-style analyzer method and return enhanced result.

    This eliminates the common boilerplate pattern in query tool handlers:
    1. Get analyzer and event loop
    2. Execute in executor
    3. Wrap with EnhancedQueryResult metadata
    4. Optionally add next steps

    Args:
        arguments: MCP tool arguments dict.
        analyzer_method: The analyzer method to call (no arguments, use lambda).
        tool_name: Tool name for metadata (e.g., "get_class_info").
        next_steps_func: Optional function to generate next_steps.
                        Receives (result, arguments) and returns suggestions.
        result_transform_func: Optional function to transform result before wrapping.
                              Receives result and returns transformed result.

    Returns:
        List containing a single TextContent with JSON-formatted enhanced result.

    Example:
        async def _handle_get_class_info(arguments):
            return await execute_analyzer_query(
                arguments=arguments,
                analyzer_method=lambda: analyzer.get_class_info(
                    str(arguments["class_name"])
                ),
                tool_name="get_class_info",
                next_steps_func=lambda result, args: suggestions.for_get_class_info(result),
            )
    """
    analyzer = ctx.analyzer
    assert analyzer is not None
    loop = asyncio.get_event_loop()

    # Execute analyzer method
    result = await loop.run_in_executor(None, analyzer_method)

    # Apply optional transformation
    if result_transform_func:
        result = result_transform_func(result, arguments)

    # Wrap with metadata
    enhanced_result = EnhancedQueryResult.create_from_state(result, ctx.state_manager, tool_name)

    # Add next steps if provided
    if next_steps_func and result and "error" not in (result or {}):
        enhanced_result.next_steps = next_steps_func(result, arguments)

    return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]
