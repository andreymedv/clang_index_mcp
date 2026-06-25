"""Transport and signal helpers for the C++ MCP server."""

import asyncio
import os
import signal
import threading

from ..._core import diagnostics


async def _run_stdio_transport(server):
    """Run the server using stdio transport."""
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def _run_http_transport(server, host, port, transport):
    """Run the server using HTTP or SSE transport."""
    try:
        from ..transport.http_server import run_http_server
    except ImportError:
        from http_server import run_http_server  # type: ignore[no-redef]

    await run_http_server(server, host, port, transport)


def _install_signal_handlers():
    """Install SIGINT/SIGTERM handlers that trigger graceful asyncio shutdown."""
    loop = asyncio.get_event_loop()
    _hard_shutdown_armed = False

    def _signal_handler():
        nonlocal _hard_shutdown_armed
        if _hard_shutdown_armed:
            diagnostics.warning("Forced shutdown")
            os._exit(1)
        _hard_shutdown_armed = True

        diagnostics.info("Shutdown signal received, stopping server...")
        for task in asyncio.all_tasks(loop):
            task.cancel()

        # Hard shutdown fallback: force-exit if cleanup blocks for >3s.
        # Uses a daemon thread since the event loop itself may be stuck.
        def _hard_shutdown():
            import time

            time.sleep(3.0)
            os._exit(0)

        threading.Thread(target=_hard_shutdown, daemon=True).start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)
