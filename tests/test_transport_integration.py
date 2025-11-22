#!/usr/bin/env python3
"""
Integration tests for all transport types.

Tests that the server can start with different transport configurations.
"""

import asyncio
import subprocess
import time
import pytest
import httpx
import sys
from pathlib import Path


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestTransportSelection:
    """Test suite for transport selection via command-line arguments."""

    def test_help_output(self):
        """Test that help output includes transport options."""
        result = subprocess.run(
            ["python3", "-m", "mcp_server.cpp_mcp_server", "--help"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "--transport" in result.stdout
        assert "stdio" in result.stdout
        assert "http" in result.stdout
        assert "sse" in result.stdout

    def test_invalid_transport(self):
        """Test that invalid transport option is rejected."""
        result = subprocess.run(
            ["python3", "-m", "mcp_server.cpp_mcp_server", "--transport", "invalid"],
            capture_output=True,
            text=True,
            timeout=5
        )

        assert result.returncode != 0
        assert "invalid choice" in result.stderr.lower() or "invalid" in result.stderr.lower()


class TestStdioTransport:
    """Test suite for stdio transport (default behavior)."""

    def test_stdio_default(self):
        """Test that server starts with default stdio transport."""
        # Start server process
        proc = subprocess.Popen(
            ["python3", "-m", "mcp_server.cpp_mcp_server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            # Give it a moment to start
            time.sleep(0.5)

            # Check it's running
            assert proc.poll() is None, "Server should be running"
        finally:
            # Terminate and cleanup
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

            # Close pipes to prevent resource warnings
            if proc.stdin:
                proc.stdin.close()
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()

    def test_stdio_explicit(self):
        """Test that server starts with explicit stdio transport."""
        # Start server process
        proc = subprocess.Popen(
            ["python3", "-m", "mcp_server.cpp_mcp_server", "--transport", "stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            # Give it a moment to start
            time.sleep(0.5)

            # Check it's running
            assert proc.poll() is None, "Server should be running"
        finally:
            # Terminate and cleanup
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

            # Close pipes to prevent resource warnings
            if proc.stdin:
                proc.stdin.close()
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()


@pytest.mark.asyncio
class TestHTTPTransportIntegration:
    """Integration tests for HTTP transport."""

    async def test_http_server_start(self):
        """Test that HTTP server starts and responds."""
        # Start server in subprocess
        proc = subprocess.Popen(
            [
                "python3", "-m", "mcp_server.cpp_mcp_server",
                "--transport", "http",
                "--port", "18100",
                "--host", "127.0.0.1"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for server to start
        await asyncio.sleep(2)

        try:
            # Check server is running
            assert proc.poll() is None, "Server should be running"

            # Try to connect
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.get("http://127.0.0.1:18100/health", timeout=5.0)
                    assert response.status_code == 200
                    data = response.json()
                    assert data["status"] == "healthy"
                except httpx.ConnectError:
                    pytest.fail("Could not connect to HTTP server")

        finally:
            # Cleanup
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

            # Close pipes to prevent resource warnings
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()


@pytest.mark.asyncio
class TestSSETransportIntegration:
    """Integration tests for SSE transport."""

    async def test_sse_server_start(self):
        """Test that SSE server starts and responds."""
        # Start server in subprocess
        proc = subprocess.Popen(
            [
                "python3", "-m", "mcp_server.cpp_mcp_server",
                "--transport", "sse",
                "--port", "18101",
                "--host", "127.0.0.1"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for server to start
        await asyncio.sleep(2)

        try:
            # Check server is running
            assert proc.poll() is None, "Server should be running"

            # Try to connect
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.get("http://127.0.0.1:18101/health", timeout=5.0)
                    assert response.status_code == 200
                    data = response.json()
                    assert data["status"] == "healthy"
                except httpx.ConnectError:
                    pytest.fail("Could not connect to SSE server")

        finally:
            # Cleanup
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

            # Close pipes to prevent resource warnings
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
