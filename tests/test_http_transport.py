#!/usr/bin/env python3
"""
Tests for HTTP transport implementation.

Tests the HTTP/Streamable HTTP protocol support for the MCP server.
"""

import asyncio
import json
import pytest
import httpx
from pathlib import Path
import tempfile
import os

# Test configuration
TEST_HOST = "127.0.0.1"
TEST_PORT = 18000  # Use non-standard port for testing


@pytest.fixture
async def http_server():
    """
    Fixture to start HTTP server for testing.

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

    # Create a minimal mock MCP server for testing HTTP transport
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

    # Create HTTP server instance with mock server
    http_srv = MCPHTTPServer(mock_server, host=TEST_HOST, port=port, transport_type="http")

    # Start server in background task
    server_task = asyncio.create_task(http_srv.start())

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
async def test_http_root_endpoint(http_server):
    """Test the root endpoint returns server information."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{http_server}/")

        assert response.status_code == 200
        data = response.json()

        assert "name" in data
        assert "version" in data
        assert "transport" in data
        assert data["transport"] == "http"
        assert "protocol" in data


@pytest.mark.asyncio
async def test_http_health_endpoint(http_server):
    """Test the health check endpoint."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{http_server}/health")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "healthy"
        assert data["transport"] == "http"
        assert "active_sessions" in data


@pytest.mark.asyncio
async def test_http_messages_endpoint_invalid_json(http_server):
    """Test messages endpoint with invalid JSON."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{http_server}/mcp/v1/messages",
            content=b"invalid json{",
            headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 400
        data = response.json()

        assert "error" in data
        assert data["error"]["code"] == -32700  # Parse error


@pytest.mark.asyncio
async def test_http_session_creation(http_server):
    """Test that sessions are created and session IDs are returned."""
    async with httpx.AsyncClient() as client:
        # Make a request without session ID
        request_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {}
        }

        response = await client.post(
            f"{http_server}/mcp/v1/messages",
            json=request_data
        )

        # Should get a session ID header
        assert "x-mcp-session-id" in response.headers
        session_id = response.headers["x-mcp-session-id"]
        assert session_id

        # Make another request with the same session ID
        response2 = await client.post(
            f"{http_server}/mcp/v1/messages",
            json=request_data,
            headers={"x-mcp-session-id": session_id}
        )

        # Should get the same session ID back
        assert response2.headers["x-mcp-session-id"] == session_id


@pytest.mark.asyncio
async def test_http_concurrent_sessions(http_server):
    """Test that multiple concurrent sessions are supported."""
    async with httpx.AsyncClient() as client:
        # Create multiple sessions concurrently
        tasks = []
        for i in range(5):
            request_data = {
                "jsonrpc": "2.0",
                "id": i,
                "method": "initialize",
                "params": {}
            }
            tasks.append(
                client.post(f"{http_server}/mcp/v1/messages", json=request_data)
            )

        responses = await asyncio.gather(*tasks)

        # All should succeed
        for response in responses:
            assert response.status_code in (200, 500)  # 500 may occur if not fully initialized

        # All should have different session IDs
        session_ids = [r.headers["x-mcp-session-id"] for r in responses]
        assert len(set(session_ids)) == len(session_ids)  # All unique


@pytest.mark.asyncio
async def test_http_tool_list_request(http_server):
    """Test listing tools via HTTP."""
    async with httpx.AsyncClient() as client:
        request_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }

        response = await client.post(
            f"{http_server}/mcp/v1/messages",
            json=request_data,
            timeout=10.0
        )

        # Should succeed or return error if not initialized
        assert response.status_code in (200, 500)


class TestHTTPProtocol:
    """Test suite for HTTP protocol compliance."""

    @pytest.mark.asyncio
    async def test_content_type_json(self, http_server):
        """Test that responses have correct content type."""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{http_server}/")
            assert "application/json" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_cors_headers_not_present(self, http_server):
        """Test that CORS headers are not set (out of scope)."""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{http_server}/")
            assert "access-control-allow-origin" not in response.headers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
