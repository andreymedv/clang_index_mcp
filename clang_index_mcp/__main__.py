"""Package entry point for the C++ Code Analysis MCP Server.

Run with:
    python -m clang_index_mcp
"""

import asyncio

from clang_index_mcp._mcp.cpp_mcp_server import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
