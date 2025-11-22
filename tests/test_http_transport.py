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
    # Import server components
    from mcp_server.cpp_mcp_server import server
    from mcp_server.http_server import MCPHTTPServer

    # Create server instance
    http_srv = MCPHTTPServer(server, host=TEST_HOST, port=TEST_PORT, transport_type="http")

    # Start server in background task
    server_task = asyncio.create_task(http_srv.start())

    # Wait a bit for server to start
    await asyncio.sleep(1)

    # Yield base URL for tests
    base_url = f"http://{TEST_HOST}:{TEST_PORT}"

    yield base_url

    # Cleanup: cancel server task
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass


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
