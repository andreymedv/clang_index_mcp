"""Package entry point for the C++ Code Analysis MCP Server.

Run with:
    python -m mcp_server
"""

import asyncio

from mcp_server._mcp.cpp_mcp_server import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
