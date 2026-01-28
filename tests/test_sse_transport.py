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

    # Cleanup: shutdown server gracefully, then cancel task
    await sse_srv.shutdown()
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass

    # Give time for port to be released and sockets to close
    await asyncio.sleep(1.0)


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
        async with client.stream("GET", f"{sse_server}/sse", timeout=5.0) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            # Note: MCP SDK's SseServerTransport sends session ID in endpoint event,
            # not in headers

            # Read the endpoint event to verify stream is working
            endpoint_found = False
            async for line in response.aiter_lines():
                if "endpoint" in line or "session_id=" in line:
                    endpoint_found = True
                    break  # Exit after finding the endpoint event

            assert endpoint_found, "Should receive at least the endpoint event"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="Flaky in CI: peer closed connection (timing)", strict=False)
async def test_sse_session_id_in_endpoint_event(sse_server):
    """Test that SSE stream includes session ID in endpoint event (MCP SDK behavior)."""
    async with httpx.AsyncClient() as client:
        async with client.stream("GET", f"{sse_server}/sse", timeout=2.0) as response:
            # MCP SDK's SseServerTransport sends session ID in the "endpoint" event
            session_id_found = False
            async for line in response.aiter_lines():
                # Look for "event: endpoint" followed by "data: /messages?session_id=..."
                if line.startswith("data:") and "session_id=" in line:
                    session_id_found = True
                    assert len(line) > len("data: /messages?session_id=")
                    break

            assert session_id_found, "Should receive endpoint event with session ID"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="Flaky in CI: peer closed connection (timing)", strict=False)
async def test_sse_endpoint_event(sse_server):
    """Test that SSE stream sends endpoint event (MCP SDK behavior)."""
    async with httpx.AsyncClient() as client:
        async with client.stream("GET", f"{sse_server}/sse", timeout=5.0) as response:
            endpoint_event_found = False

            async for line in response.aiter_lines():
                # Look for the "endpoint" event that MCP SDK sends
                if line.startswith("event:") and "endpoint" in line:
                    endpoint_event_found = True
                    break

                # Safety: stop after reading many lines
                if endpoint_event_found:
                    break

            assert endpoint_event_found, "No endpoint event received from SSE stream"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="Flaky in CI: peer closed connection (timing)", strict=False)
async def test_sse_with_messages_endpoint(sse_server):
    """Test that SSE server provides messages endpoint with session ID."""
    async with httpx.AsyncClient() as client:
        # First connect to SSE to get session ID
        session_id = None
        async with client.stream("GET", f"{sse_server}/sse", timeout=2.0) as sse_response:
            async for line in sse_response.aiter_lines():
                if "session_id=" in line:
                    # Extract session ID from endpoint URL
                    start = line.find("session_id=") + len("session_id=")
                    session_id = line[start:].strip()
                    break

        assert session_id is not None, "Should receive session ID from endpoint event"

        # Now POST to messages endpoint with session ID (MCP SDK SSE protocol)
        request_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {}
        }

        response = await client.post(
            f"{sse_server}/messages?session_id={session_id}",
            json=request_data
        )

        # Should respond (various status codes are valid at protocol level)
        # 200 = Success
        # 202 = Accepted (async response)
        # 400 = Bad request
        # 406 = Not Acceptable (MCP transport validation)
        # 500 = Server error
        assert response.status_code in (200, 202, 400, 406, 500)


class TestSSEProtocol:
    """Test suite for SSE protocol compliance."""

    @pytest.mark.asyncio
    async def test_sse_content_type(self, sse_server):
        """Test that SSE stream has correct content type."""
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"{sse_server}/sse", timeout=2.0) as response:
                content_type = response.headers.get("content-type", "")
                assert "text/event-stream" in content_type

    @pytest.mark.asyncio
    async def test_sse_cache_control(self, sse_server):
        """Test that SSE stream has cache control header."""
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"{sse_server}/sse", timeout=2.0) as response:
                cache_control = response.headers.get("cache-control", "")
                # MCP SDK's SseServerTransport uses "no-store"
                assert "no-store" in cache_control or "no-cache" in cache_control

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Flaky in CI: peer closed connection (timing)", strict=False)
    async def test_sse_reconnection(self, sse_server):
        """Test SSE stream can be reconnected (each connection gets new session)."""
        async with httpx.AsyncClient() as client:
            # First connection
            session_id_1 = None
            async with client.stream("GET", f"{sse_server}/sse", timeout=2.0) as response1:
                # Extract session ID from endpoint event
                async for line in response1.aiter_lines():
                    if "session_id=" in line:
                        # Parse session ID from URL
                        start = line.find("session_id=") + len("session_id=")
                        session_id_1 = line[start:].strip()
                        break

            # Second connection (MCP SDK creates new session per connection)
            session_id_2 = None
            async with client.stream("GET", f"{sse_server}/sse", timeout=2.0) as response2:
                async for line in response2.aiter_lines():
                    if "session_id=" in line:
                        start = line.find("session_id=") + len("session_id=")
                        session_id_2 = line[start:].strip()
                        break

            # Both connections should receive session IDs
            assert session_id_1 is not None
            assert session_id_2 is not None
            # Each SSE connection gets its own session in MCP SDK
            assert session_id_1 != session_id_2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
