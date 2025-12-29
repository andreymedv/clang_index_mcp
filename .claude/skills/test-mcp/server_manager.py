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
from typing import Dict, Optional


class ServerManager:
    """Manages MCP server lifecycle for testing"""

    def __init__(self, protocol: str = "http", port: int = 8000) -> None:
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
        self.session_id = None  # For HTTP/SSE session management
        self.sse_connected = False  # Track SSE connection state
        self.mcp_initialized = False  # Track MCP protocol initialization

    def start_server(self, project_path: Optional[str] = None, timeout: int = 30) -> Dict:
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
        # Use DEVNULL to avoid blocking on full pipes
        self.server_process = subprocess.Popen(
            cmd,
            cwd=self.repo_root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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
        # Use DEVNULL to avoid blocking on full pipes
        self.server_process = subprocess.Popen(
            cmd,
            cwd=self.repo_root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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

    def stop_server(self) -> None:
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

    def _establish_sse_connection(self, endpoint):
        """
        Establish SSE connection for SSE transport

        Args:
            endpoint: Server endpoint

        Note:
            For SSE transport, we don't actually need to maintain a persistent
            connection for simple request/response testing. The MCP SSE transport
            handles the connection internally.
        """
        # For testing purposes with SSE, we can skip the persistent GET /sse connection
        # and just use POST /messages directly. The server's SSE transport handles it.
        self.sse_connected = True

    def _initialize_mcp_session(self, endpoint):
        """
        Perform MCP initialization handshake

        Args:
            endpoint: Server endpoint

        Returns:
            bool: True if initialization successful

        MCP Protocol requires initialization before calling tools:
        1. Client sends "initialize" request
        2. Server responds with capabilities
        3. Client sends "initialized" notification
        """
        try:
            # Step 1: Send initialize request
            url = f"{endpoint}/messages"
            init_request = {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "mcp-test-client",
                        "version": "0.1.0"
                    }
                }
            }

            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json"
            }

            # For HTTP, include session ID if available
            if self.protocol == "http" and self.session_id:
                headers["mcp-session-id"] = self.session_id

            response = requests.post(url, json=init_request, headers=headers, timeout=30)

            # Extract session ID for HTTP
            if self.protocol == "http" and "mcp-session-id" in response.headers:
                self.session_id = response.headers["mcp-session-id"]

            if response.status_code >= 400:
                print(f"ERROR: MCP initialization failed with status {response.status_code}")
                print(f"  Response: {response.text[:500]}")
                return False

            init_result = response.json()

            if "error" in init_result:
                print(f"ERROR: MCP initialization returned error: {init_result['error']}")
                return False

            if "result" not in init_result:
                print(f"ERROR: MCP initialization: No result in response")
                return False

            # Step 2: Send initialized notification (no response expected)
            initialized_notification = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized"
            }

            headers_notify = headers.copy()
            if self.protocol == "http" and self.session_id:
                headers_notify["mcp-session-id"] = self.session_id

            response = requests.post(url, json=initialized_notification, headers=headers_notify, timeout=30)

            # Notification may return empty response or 200 OK
            print(f"✓ MCP session initialized successfully")
            return True

        except Exception as e:
            print(f"ERROR: MCP initialization failed: {e}")
            return False

    def call_tool(self, endpoint: str, tool_name: str, arguments: Dict) -> Dict:
        """
        Call an MCP tool via HTTP/SSE

        Args:
            endpoint: Server endpoint
            tool_name: Name of MCP tool
            arguments: Tool arguments dict

        Returns:
            dict: Tool response (parsed JSON-RPC response)
        """
        if self.protocol not in ["sse", "http"]:
            raise ValueError(f"call_tool not supported for protocol: {self.protocol}")

        # For SSE, establish connection if not already done
        if self.protocol == "sse" and not self.sse_connected:
            self._establish_sse_connection(endpoint)

        # Initialize MCP session if not already done
        if not self.mcp_initialized:
            if not self._initialize_mcp_session(endpoint):
                raise RuntimeError("Failed to initialize MCP session")
            self.mcp_initialized = True

        # Build the MCP JSON-RPC request
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

        # For HTTP protocol, include session ID if we have one
        # Server will create a new session if not provided
        if self.protocol == "http" and self.session_id:
            headers["mcp-session-id"] = self.session_id

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=300)

            # Extract session ID from response for HTTP transport
            if self.protocol == "http" and "mcp-session-id" in response.headers:
                new_session_id = response.headers["mcp-session-id"]
                if self.session_id and self.session_id != new_session_id:
                    print(f"DEBUG: Session ID changed: {self.session_id} -> {new_session_id}")
                self.session_id = new_session_id

            # Check for HTTP errors
            if response.status_code >= 400:
                print(f"ERROR: HTTP request failed with status {response.status_code}")
                print(f"  URL: {url}")
                print(f"  Tool: {tool_name}")
                print(f"  Headers: {dict(response.headers)}")
                print(f"  Response: {response.text[:500]}")
                response.raise_for_status()

            # Parse JSON response
            result = response.json()

            # Check for JSON-RPC error
            if "error" in result:
                print(f"WARNING: MCP tool returned error:")
                print(f"  Tool: {tool_name}")
                print(f"  Error: {result['error']}")
                # Return the error response as-is (caller will handle it)
                return result

            return result

        except requests.exceptions.RequestException as e:
            print(f"ERROR: Request exception: {e}")
            print(f"  URL: {url}")
            print(f"  Tool: {tool_name}")
            raise

    def __del__(self):
        """Cleanup on deletion"""
        self.stop_server()
