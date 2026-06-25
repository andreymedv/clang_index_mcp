"""Class hierarchy MCP tool handlers."""

import asyncio
from typing import Any, Dict, List

from mcp.types import TextContent

from ..context import ctx
from ..._search.hierarchy_format import convert_hierarchy_format, format_hierarchy_error


async def _handle_get_class_hierarchy(arguments: Dict[str, Any]) -> List[TextContent]:
    analyzer = ctx.analyzer
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    class_name = str(arguments["class_name"])
    max_nodes = arguments.get("max_nodes", 200)
    max_depth = arguments.get("max_depth", None)
    direction = arguments.get("direction", "both")
    output_format = arguments.get("output_format", "json")
    # Run synchronous method in executor to avoid blocking event loop
    hierarchy = await loop.run_in_executor(
        None,
        lambda: analyzer.get_class_hierarchy(
            class_name, max_nodes=max_nodes, max_depth=max_depth, direction=direction
        ),
    )
    if hierarchy:
        # Check for error in hierarchy result
        if "error" in hierarchy:
            error_text = format_hierarchy_error(hierarchy["error"], output_format)
            return [TextContent(type="text", text=error_text)]
        # Convert to requested output format
        formatted = convert_hierarchy_format(hierarchy, output_format)
        return [TextContent(type="text", text=formatted)]
    else:
        error_text = format_hierarchy_error(f"Class '{class_name}' not found", output_format)
        return [TextContent(type="text", text=error_text)]
