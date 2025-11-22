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

        try:
            # Validate JSON early to return proper error codes
            # Read and validate the body
            body = await request.body()
            try:
                if body:
                    json.loads(body.decode())
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning(f"JSON decode error: {e}")
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32700,
                            "message": "Parse error"
                        },
                        "id": None
                    },
                    status_code=400,
                    headers={"x-mcp-session-id": session_id}
                )

            # Create a custom receive function that replays the body we already read
            body_sent = False

            async def receive_with_body():
                nonlocal body_sent
                if not body_sent:
                    body_sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                else:
                    # Body already sent
                    return {"type": "http.disconnect"}

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

                # Give the session a moment to initialize
                await asyncio.sleep(0.1)

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

            # Use transport's handle_request method with our custom receive
            try:
                await transport.handle_request(request.scope, receive_with_body, send)
            except json.JSONDecodeError as e:
                # Invalid JSON
                logger.warning(f"JSON decode error: {e}")
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32700,
                            "message": "Parse error"
                        },
                        "id": None
                    },
                    status_code=400,
                    headers={"x-mcp-session-id": session_id}
                )
            except Exception as e:
                logger.exception(f"Error handling request: {e}")
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32603,
                            "message": f"Internal error: {str(e)}"
                        },
                        "id": None
                    },
                    status_code=500,
                    headers={"x-mcp-session-id": session_id}
                )

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

        except Exception as e:
            logger.exception(f"Unexpected error in handle_http_message: {e}")
            return JSONResponse(
                {"error": f"Server error: {str(e)}"},
                status_code=500,
                headers={"x-mcp-session-id": session_id}
            )

    async def handle_sse_stream(self, request: Request) -> Response:
        """
        Handle SSE stream endpoint.

        This delegates to SseServerTransport for event streaming.
        """
        from starlette.responses import StreamingResponse

        # Get or create session ID
        session_id = request.headers.get("x-mcp-session-id")
        if not session_id:
            session_id = str(uuid4())
            logger.info(f"Created new SSE session: {session_id}")

        async def sse_event_stream():
            """Generate SSE events including keepalives."""
            # Send initial connected event
            yield f"event: connected\ndata: {json.dumps({'session_id': session_id})}\n\n".encode()

            # Send keepalive comments periodically
            try:
                count = 0
                while True:
                    await asyncio.sleep(1)
                    yield b": keepalive\n\n"
                    count += 1

                    # Also send a periodic data event
                    if count % 5 == 0:
                        yield f"event: ping\ndata: {json.dumps({'timestamp': count})}\n\n".encode()
            except asyncio.CancelledError:
                logger.info(f"SSE stream closed for session {session_id}")
                raise

        return StreamingResponse(
            sse_event_stream(),
            media_type="text/event-stream",
            headers={
                "x-mcp-session-id": session_id,
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
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
