#!/usr/bin/env python3
"""Standalone mock MCP server returning canned responses.

Uses the real tool schemas from consolidated_tools.py but returns
predefined responses from YAML fixtures. No libclang, no SQLite,
no indexing — sub-second response time for rapid iteration.

Usage:
    python tools/mock_server/server.py --port 9000
    python tools/mock_server/server.py --port 9000 --fixtures custom.yaml
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to path so we can import mcp_server.consolidated_tools
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from mcp.server import Server  # noqa: E402
from mcp.types import TextContent, Tool  # noqa: E402

from mcp_server.consolidated_tools import list_tools_b  # noqa: E402
from tools.mock_server.fixtures import FixtureStore  # noqa: E402

logger = logging.getLogger("mock_mcp_server")

DEFAULT_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixtures(fixtures_path: str | Path | None = None) -> FixtureStore:
    """Load fixtures from a file or directory (all *.yaml)."""
    path = Path(fixtures_path) if fixtures_path else DEFAULT_FIXTURES_DIR
    store = FixtureStore()
    if path.is_dir():
        for ff in sorted(path.glob("*.yaml")):
            store.load(ff)
    else:
        store.load(path)
    return store


def _convert_hierarchy_response(response: dict, output_format: str) -> str:
    """Convert mock hierarchy response to requested output format.

    The mock uses a simplified 'nodes' format, so we convert it to the
    standard 'classes' format that the real server uses, then format.
    """
    # Convert nodes format to classes format
    classes = {}
    nodes = response.get("nodes", [])

    for node in nodes:
        name = node["name"]
        children = node.get("children", [])
        # In the mock format, children are derived classes
        classes[name] = {
            "qualified_name": name,
            "name": name.split("::")[-1] if "::" in name else name,
            "kind": "class",
            "is_project": True,
            "base_classes": [],  # Will be filled in below
            "derived_classes": children,
        }

    # Build base_classes relationships from derived_classes
    for name, info in classes.items():
        for derived in info["derived_classes"]:
            if derived in classes:
                classes[derived]["base_classes"].append(name)

    # Build standard hierarchy structure
    hierarchy = {
        "queried_class": response.get("root", ""),
        "direction": "both",
        "classes": classes,
    }
    if response.get("truncated"):
        hierarchy["truncated"] = True

    # Use the same converter as the real server
    try:
        # Try importing from mcp_server first
        from mcp_server.hierarchy_format import convert_hierarchy_format
    except ImportError:
        # Fallback to local implementation
        return _mock_convert_hierarchy(hierarchy, output_format)

    return convert_hierarchy_format(hierarchy, output_format)


def _mock_convert_hierarchy(hierarchy: dict, output_format: str) -> str:
    """Fallback converter when mcp_server module is not available."""
    classes = hierarchy.get("classes", {})
    queried_class = hierarchy.get("queried_class", "Unknown")

    if output_format == "compact":
        # Abbreviated JSON
        key_map = {
            "queried_class": "q",
            "classes": "c",
            "qualified_name": "qn",
            "base_classes": "bases",
            "derived_classes": "derived",
        }

        def abbreviate(obj):
            if isinstance(obj, dict):
                return {key_map.get(k, k): abbreviate(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [abbreviate(item) for item in obj]
            return obj

        return json.dumps(abbreviate(hierarchy), indent=None, separators=(',', ':'))

    if output_format in ("cpp", "cpp_with_meta"):
        # C++ pseudocode format
        lines = []
        lines.append(f"// Class hierarchy for: {queried_class}")
        lines.append("")

        # Simple topological sort: classes with no bases first
        sorted_names = sorted(classes.keys())

        for name in sorted_names:
            info = classes[name]
            bases = info.get("base_classes", [])
            if bases:
                base_list = ", ".join(f"public {b}" for b in bases)
                lines.append(f"class {name}: {base_list} {{}};")
            else:
                lines.append(f"class {name} {{}};")

            if output_format == "cpp_with_meta":
                derived = info.get("derived_classes", [])
                if derived:
                    lines.append(f"  // derived: {', '.join(derived)}")

        return "\n".join(lines)

    # Default: JSON
    return json.dumps(hierarchy, indent=2)


def create_server(fixtures_path: str | Path | None = None) -> Server:
    """Create a mock MCP server with canned responses."""
    store = _load_fixtures(fixtures_path)
    tools = list_tools_b()

    app = Server("cpp-analyzer-mock")

    @app.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return tools

    @app.call_tool()
    async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
        logger.debug("call_tool: %s(%s)", name, json.dumps(arguments, indent=2))
        response = store.match(name, arguments or {})

        # Handle output_format for get_class_hierarchy
        if name == "get_class_hierarchy":
            output_format = arguments.get("output_format", "json")
            if output_format != "json" and "error" not in response:
                # Convert fixture response to proper format
                formatted = _convert_hierarchy_response(response, output_format)
                return [TextContent(type="text", text=formatted)]

        return [TextContent(type="text", text=json.dumps(response, indent=2))]

    return app


async def run_sse(port: int, fixtures_path: str | Path | None = None) -> None:
    """Run the mock server with SSE transport."""
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route

    try:
        import uvicorn
    except ImportError:
        print("uvicorn required for SSE transport: pip install uvicorn")
        sys.exit(1)

    app_server = create_server(fixtures_path)
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):  # type: ignore[no-untyped-def]
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await app_server.run(streams[0], streams[1], app_server.create_initialization_options())

    starlette_app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )

    config = uvicorn.Config(starlette_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def run_stdio(fixtures_path: str | Path | None = None) -> None:
    """Run the mock server with stdio transport."""
    from mcp.server.stdio import stdio_server

    app_server = create_server(fixtures_path)
    async with stdio_server() as (read_stream, write_stream):
        await app_server.run(read_stream, write_stream, app_server.create_initialization_options())


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock MCP server with canned responses")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="SSE port (omit for stdio transport)",
    )
    parser.add_argument(
        "--fixtures",
        type=str,
        default=None,
        help="Path to fixtures YAML file or directory (default: fixtures/)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    import asyncio

    if args.port:
        print(f"Starting mock MCP server on SSE port {args.port}")
        asyncio.run(run_sse(args.port, args.fixtures))
    else:
        asyncio.run(run_stdio(args.fixtures))


if __name__ == "__main__":
    main()
