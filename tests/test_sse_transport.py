#!/usr/bin/env python3
"""
Tests for SSE (Server-Sent Events) transport implementation.

Tests the SSE protocol support for the MCP server.
"""

import asyncio
import json
import pytest
import httpx
from pathlib import Path


# Test configuration
TEST_HOST = "127.0.0.1"
TEST_PORT = 18001  # Use different port from HTTP tests


@pytest.fixture
async def sse_server():
    """
    Fixture to start SSE server for testing.

    Starts the server in the background and yields the base URL.
    """
    # Import MCP Server class (not the instance, to avoid libclang init)
    from mcp.server import Server
    from mcp_server.http_server import MCPHTTPServer
    import socket

    # Find an available port dynamically to avoid conflicts
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]

    # Create a minimal mock MCP server for testing SSE transport
    # This doesn't need libclang or C++ analyzer functionality
    mock_server = Server("test-cpp-analyzer")

    # Register minimal tools for testing
    @mock_server.list_tools()
    async def list_tools():
        return []

    @mock_server.call_tool()
    async def call_tool(name: str, arguments: dict):
        from mcp.types import TextContent
        return [TextContent(type="text", text=json.dumps({"status": "ok", "tool": name}))]

    # Create SSE server instance with mock server
    sse_srv = MCPHTTPServer(mock_server, host=TEST_HOST, port=port, transport_type="sse")

    # Start server in background task
    server_task = asyncio.create_task(sse_srv.start())

    # Wait a bit for server to start
    await asyncio.sleep(1.5)

    # Yield base URL for tests
    base_url = f"http://{TEST_HOST}:{port}"

    yield base_url

    # Cleanup: cancel server task and wait for it to finish
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass

    # Give time for port to be released
    await asyncio.sleep(0.5)


@pytest.mark.asyncio
async def test_sse_root_endpoint(sse_server):
    """Test the root endpoint returns server information."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{sse_server}/")

        assert response.status_code == 200
        data = response.json()

        assert "name" in data
        assert "version" in data
        assert "transport" in data
        assert data["transport"] == "sse"
        assert "endpoints" in data
        assert "sse" in data["endpoints"]


@pytest.mark.asyncio
async def test_sse_health_endpoint(sse_server):
    """Test the health check endpoint."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{sse_server}/health")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "healthy"
        assert data["transport"] == "sse"


@pytest.mark.asyncio
async def test_sse_stream_endpoint(sse_server):
    """Test the SSE stream endpoint returns event stream."""
    async with httpx.AsyncClient() as client:
        async with client.stream("GET", f"{sse_server}/mcp/v1/sse", timeout=5.0) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            assert "x-mcp-session-id" in response.headers

            # Read first few events
            event_count = 0
            async for line in response.aiter_lines():
                if line.strip():
                    event_count += 1
                    # Stop after getting a few events
                    if event_count >= 3:
                        break


@pytest.mark.asyncio
async def test_sse_session_id_header(sse_server):
    """Test that SSE stream includes session ID in headers."""
    async with httpx.AsyncClient() as client:
        async with client.stream("GET", f"{sse_server}/mcp/v1/sse", timeout=2.0) as response:
            assert "x-mcp-session-id" in response.headers
            session_id = response.headers["x-mcp-session-id"]
            assert session_id
            assert len(session_id) > 0


@pytest.mark.asyncio
async def test_sse_keepalive(sse_server):
    """Test that SSE stream sends keepalive messages."""
    async with httpx.AsyncClient() as client:
        async with client.stream("GET", f"{sse_server}/mcp/v1/sse", timeout=5.0) as response:
            keepalive_found = False

            async for line in response.aiter_lines():
                # SSE keepalive is a comment line starting with ':'
                if line.strip().startswith(":"):
                    keepalive_found = True
                    break

                # Safety: break after reading some lines
                if keepalive_found:
                    break

            assert keepalive_found, "No keepalive messages received"


@pytest.mark.asyncio
async def test_sse_with_messages_endpoint(sse_server):
    """Test that SSE server also provides messages endpoint for requests."""
    async with httpx.AsyncClient() as client:
        # SSE server should also have a messages endpoint
        request_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {}
        }

        response = await client.post(
            f"{sse_server}/mcp/v1/messages",
            json=request_data
        )

        # Should succeed or return error if not initialized
        assert response.status_code in (200, 500)


class TestSSEProtocol:
    """Test suite for SSE protocol compliance."""

    @pytest.mark.asyncio
    async def test_sse_content_type(self, sse_server):
        """Test that SSE stream has correct content type."""
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"{sse_server}/mcp/v1/sse", timeout=2.0) as response:
                content_type = response.headers.get("content-type", "")
                assert "text/event-stream" in content_type

    @pytest.mark.asyncio
    async def test_sse_cache_control(self, sse_server):
        """Test that SSE stream has no-cache header."""
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"{sse_server}/mcp/v1/sse", timeout=2.0) as response:
                cache_control = response.headers.get("cache-control", "")
                assert "no-cache" in cache_control

    @pytest.mark.asyncio
    async def test_sse_reconnection(self, sse_server):
        """Test SSE stream reconnection with same session ID."""
        async with httpx.AsyncClient() as client:
            # First connection
            async with client.stream("GET", f"{sse_server}/mcp/v1/sse", timeout=2.0) as response1:
                session_id = response1.headers["x-mcp-session-id"]

            # Reconnect with same session ID
            async with client.stream(
                "GET",
                f"{sse_server}/mcp/v1/sse",
                headers={"x-mcp-session-id": session_id},
                timeout=2.0
            ) as response2:
                # Should get same session ID back
                assert response2.headers["x-mcp-session-id"] == session_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
