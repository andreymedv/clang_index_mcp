#!/usr/bin/env python3
"""
HTTP/SSE Server Implementation for C++ Code Analysis MCP Server

Provides HTTP and Server-Sent Events transport support for the MCP server.
"""

import asyncio
import json
import logging
from uuid import uuid4

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
import uvicorn

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http import StreamableHTTPServerTransport

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MCPHTTPServer:
    """
    HTTP/SSE server wrapper for MCP Server.

    Supports both HTTP (Streamable HTTP) and SSE transports.
    """

    def __init__(
        self,
        mcp_server: Server,
        host: str = "127.0.0.1",
        port: int = 8000,
        transport_type: str = "http"
    ):
        """
        Initialize the HTTP/SSE server.

        Args:
            mcp_server: The MCP Server instance to wrap
            host: Host address to bind to
            port: Port number to listen on
            transport_type: Type of transport ("http" or "sse")
        """
        self.mcp_server = mcp_server
        self.host = host
        self.port = port
        self.transport_type = transport_type

        # Session management (for multi-client support)
        self.sessions = {}  # session_id -> (transport, task)

    def _create_app(self) -> Starlette:
        """Create and configure the Starlette application."""

        routes = [
            Route("/", self.handle_root, methods=["GET"]),
            Route("/health", self.handle_health, methods=["GET"]),
        ]

        if self.transport_type == "http":
            routes.append(Route("/mcp/v1/messages", self.handle_http_message, methods=["POST"]))

        elif self.transport_type == "sse":
            routes.append(Route("/mcp/v1/sse", self.handle_sse_stream, methods=["GET"]))
            # SSE also needs a message endpoint for POST requests
            routes.append(Route("/mcp/v1/messages", self.handle_http_message, methods=["POST"]))

        return Starlette(debug=True, routes=routes)

    async def handle_root(self, request: Request) -> Response:
        """Handle root endpoint - return server information."""
        info = {
            "name": "C++ Code Analysis MCP Server",
            "version": "0.1.0",
            "transport": self.transport_type,
            "protocol": "MCP 1.0",
            "endpoints": {
                "health": "/health",
            }
        }

        if self.transport_type == "http":
            info["endpoints"]["messages"] = "/mcp/v1/messages"
        elif self.transport_type == "sse":
            info["endpoints"]["sse"] = "/mcp/v1/sse"
            info["endpoints"]["messages"] = "/mcp/v1/messages"

        return JSONResponse(info)

    async def handle_health(self, request: Request) -> Response:
        """Handle health check endpoint."""
        return JSONResponse({
            "status": "healthy",
            "transport": self.transport_type,
            "active_sessions": len(self.sessions)
        })

    async def handle_http_message(self, request: Request) -> Response:
        """
        Handle HTTP POST messages for Streamable HTTP transport.

        This is an ASGI endpoint that delegates to StreamableHTTPServerTransport.
        """
        # Get or create session ID
        session_id = request.headers.get("x-mcp-session-id")
        if not session_id:
            session_id = str(uuid4())
            logger.info(f"Created new HTTP session: {session_id}")

        # Get or create transport for this session
        if session_id not in self.sessions:
            transport = StreamableHTTPServerTransport(
                mcp_session_id=session_id,
                is_json_response_enabled=True
            )

            # Start MCP server with this transport in background
            async def run_session():
                async with transport.connect() as (read_stream, write_stream):
                    try:
                        await self.mcp_server.run(
                            read_stream,
                            write_stream,
                            self.mcp_server.create_initialization_options(),
                            raise_exceptions=False
                        )
                    except Exception as e:
                        logger.exception(f"Error in session {session_id}: {e}")
                    finally:
                        # Clean up session
                        if session_id in self.sessions:
                            del self.sessions[session_id]

            task = asyncio.create_task(run_session())
            self.sessions[session_id] = (transport, task)
            logger.info(f"Started MCP server session {session_id}")

        else:
            transport, _ = self.sessions[session_id]

        # Handle the request through the transport
        # Create a custom send that captures the response
        response_status = 200
        response_headers = []
        response_body = b""

        async def send(message):
            nonlocal response_status, response_headers, response_body
            if message["type"] == "http.response.start":
                response_status = message.get("status", 200)
                response_headers = message.get("headers", [])
            elif message["type"] == "http.response.body":
                response_body += message.get("body", b"")

        # Use transport's handle_request method
        await transport.handle_request(request.scope, request.receive, send)

        # Build response
        headers_dict = {
            k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
            for k, v in response_headers
        }
        headers_dict["x-mcp-session-id"] = session_id

        return Response(
            content=response_body,
            status_code=response_status,
            headers=headers_dict
        )

    async def handle_sse_stream(self, request: Request) -> Response:
        """
        Handle SSE stream endpoint.

        This delegates to SseServerTransport for event streaming.
        """
        # Get or create session ID
        session_id = request.headers.get("x-mcp-session-id")
        if not session_id:
            session_id = str(uuid4())
            logger.info(f"Created new SSE session: {session_id}")

        # Create SSE transport
        sse_transport = SseServerTransport("/mcp/v1/sse")

        # Create custom send that captures response
        response_started = False
        response_headers = []

        original_send = None

        async def send_wrapper(message):
            nonlocal response_started, response_headers, original_send
            if message["type"] == "http.response.start":
                response_started = True
                response_headers = list(message.get("headers", []))
                # Add session ID header
                response_headers.append((b"x-mcp-session-id", session_id.encode()))
                message["headers"] = response_headers
            # Forward to original send
            if original_send:
                await original_send(message)

        # Start MCP server with SSE transport
        async def run_sse_session(scope, receive, send):
            nonlocal original_send
            original_send = send

            async with sse_transport.connect_sse(scope, receive, send_wrapper) as streams:
                try:
                    await self.mcp_server.run(
                        streams[0],
                        streams[1],
                        self.mcp_server.create_initialization_options(),
                        raise_exceptions=False
                    )
                except Exception as e:
                    logger.exception(f"Error in SSE session {session_id}: {e}")

        # Delegate to SSE transport by calling it as ASGI app
        # We need to create a wrapper that handles the response
        from starlette.responses import StreamingResponse

        # For SSE, we need to properly stream events
        # The SSE transport will handle the ASGI protocol

        async def event_generator():
            """Generator that yields SSE events."""
            # Create channels for communication
            from anyio import create_memory_object_stream

            send_stream, receive_stream = create_memory_object_stream(100)

            async def fake_send(message):
                """Capture SSE events from the transport."""
                if message["type"] == "http.response.body":
                    body = message.get("body", b"")
                    if body:
                        await send_stream.send(body)

            async def run_in_background():
                """Run the SSE transport in background."""
                try:
                    await sse_transport.connect_sse(
                        request.scope,
                        request.receive,
                        fake_send
                    ).__aenter__()
                except Exception as e:
                    logger.exception(f"SSE error: {e}")
                finally:
                    await send_stream.aclose()

            # Start background task
            task = asyncio.create_task(run_in_background())

            try:
                async for chunk in receive_stream:
                    yield chunk
            except Exception as e:
                logger.exception(f"Event generator error: {e}")
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "x-mcp-session-id": session_id,
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            }
        )

    async def start(self):
        """Start the HTTP/SSE server."""
        app = self._create_app()

        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="info",
            access_log=True,
        )
        server = uvicorn.Server(config)

        logger.info(f"Starting MCP HTTP server on {self.host}:{self.port}")
        logger.info(f"Transport type: {self.transport_type}")

        await server.serve()

    def run(self):
        """Run the server (blocking)."""
        asyncio.run(self.start())


async def run_http_server(
    mcp_server: Server,
    host: str = "127.0.0.1",
    port: int = 8000,
    transport_type: str = "http"
):
    """
    Run the HTTP/SSE server with the given MCP server instance.

    Args:
        mcp_server: The MCP Server instance
        host: Host address to bind to
        port: Port number to listen on
        transport_type: Type of transport ("http" or "sse")
    """
    server = MCPHTTPServer(mcp_server, host, port, transport_type)
    await server.start()
