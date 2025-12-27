"""
Server Manager - Manages MCP server lifecycle

Responsibilities:
- Start/stop MCP server processes
- Monitor server health
- Handle cleanup
"""

import subprocess
import time
import requests
import signal
import os
from pathlib import Path


class ServerManager:
    """Manages MCP server lifecycle for testing"""

    def __init__(self, protocol="http", port=8000):
        """
        Initialize ServerManager

        Args:
            protocol: Protocol to use (sse, stdio, http)
            port: Port for SSE/HTTP protocols
        """
        self.protocol = protocol
        self.port = port
        self.server_process = None
        self.repo_root = Path(__file__).parent.parent.parent.parent
        self.session_id = None  # For HTTP session management

    def start_server(self, project_path=None, timeout=30):
        """
        Start MCP server in background

        Args:
            project_path: Optional project path to set immediately
            timeout: Timeout in seconds to wait for server ready

        Returns:
            dict: Server info (pid, endpoint, status)
        """
        if self.protocol == "sse":
            return self._start_sse_server(timeout)
        elif self.protocol == "stdio":
            return self._start_stdio_server()
        elif self.protocol == "http":
            return self._start_http_server(timeout)
        else:
            raise ValueError(f"Unsupported protocol: {self.protocol}")

    def _start_sse_server(self, timeout):
        """Start SSE server"""
        cmd = [
            "python", "-m", "mcp_server.cpp_mcp_server",
            "--transport", "sse",
            "--port", str(self.port)
        ]

        env = os.environ.copy()
        env["MCP_DEBUG"] = "1"
        env["PYTHONUNBUFFERED"] = "1"

        # Start server process
        self.server_process = subprocess.Popen(
            cmd,
            cwd=self.repo_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Wait for server to be ready
        endpoint = f"http://localhost:{self.port}"
        if not self._wait_for_ready(endpoint, timeout):
            self.stop_server()
            raise RuntimeError(f"Server failed to start within {timeout}s")

        return {
            "pid": self.server_process.pid,
            "endpoint": endpoint,
            "protocol": "sse",
            "status": "running"
        }

    def _start_stdio_server(self):
        """Start stdio server"""
        # stdio mode is more complex - need bidirectional communication
        # For Phase 1, focus on SSE mode
        raise NotImplementedError("stdio protocol not implemented yet (Phase 3)")

    def _start_http_server(self, timeout):
        """Start HTTP server"""
        cmd = [
            "python", "-m", "mcp_server.cpp_mcp_server",
            "--transport", "http",
            "--port", str(self.port)
        ]

        env = os.environ.copy()
        env["MCP_DEBUG"] = "1"
        env["PYTHONUNBUFFERED"] = "1"

        # Start server process
        self.server_process = subprocess.Popen(
            cmd,
            cwd=self.repo_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Wait for server to be ready
        endpoint = f"http://localhost:{self.port}"
        if not self._wait_for_ready(endpoint, timeout):
            self.stop_server()
            raise RuntimeError(f"Server failed to start within {timeout}s")

        return {
            "pid": self.server_process.pid,
            "endpoint": endpoint,
            "protocol": "http",
            "status": "running"
        }

    def _wait_for_ready(self, endpoint, timeout):
        """
        Wait for server to become ready

        Args:
            endpoint: Server endpoint URL
            timeout: Timeout in seconds

        Returns:
            bool: True if server is ready, False otherwise
        """
        start_time = time.time()
        health_url = f"{endpoint}/health"

        while time.time() - start_time < timeout:
            try:
                response = requests.get(health_url, timeout=2)
                if response.status_code == 200:
                    return True
            except (requests.ConnectionError, requests.Timeout):
                pass

            time.sleep(0.5)

        return False

    def stop_server(self):
        """Stop the server process"""
        if self.server_process is None:
            return

        try:
            # Try graceful shutdown first
            self.server_process.send_signal(signal.SIGTERM)
            self.server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Force kill if graceful shutdown fails
            self.server_process.kill()
            self.server_process.wait()
        except Exception:
            pass

        self.server_process = None

    def call_tool(self, endpoint, tool_name, arguments):
        """
        Call an MCP tool via HTTP/SSE

        Args:
            endpoint: Server endpoint
            tool_name: Name of MCP tool
            arguments: Tool arguments dict

        Returns:
            dict: Tool response
        """
        if self.protocol not in ["sse", "http"]:
            raise ValueError(f"call_tool not supported for protocol: {self.protocol}")

        # For both SSE and HTTP, use POST /messages endpoint
        url = f"{endpoint}/messages"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # For HTTP protocol, manage session ID
        if self.protocol == "http":
            if self.session_id is None:
                # Generate new session ID
                import uuid
                self.session_id = str(uuid.uuid4())
            headers["Mcp-Session-Id"] = self.session_id

        response = requests.post(url, json=payload, headers=headers, timeout=300)

        # Update session ID from response if provided
        if "Mcp-Session-Id" in response.headers:
            self.session_id = response.headers["Mcp-Session-Id"]

        # Debug: print response details on error
        if response.status_code >= 400:
            print(f"DEBUG: Request failed with {response.status_code}")
            print(f"DEBUG: Request URL: {url}")
            print(f"DEBUG: Request payload: {payload}")
            print(f"DEBUG: Response: {response.text}")

        response.raise_for_status()
        return response.json()

    def __del__(self):
        """Cleanup on deletion"""
        self.stop_server()
