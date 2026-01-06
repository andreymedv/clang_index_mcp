# HTTP/SSE Transport Usage Guide

This guide explains how to use the HTTP and Server-Sent Events (SSE) transports with the C++ Code Analysis MCP Server.

## Overview

The server now supports three transport protocols:

1. **stdio** (default) - Standard input/output for CLI integration
2. **http** - HTTP/Streamable HTTP for RESTful API access
3. **sse** - Server-Sent Events for real-time streaming updates

## Starting the Server

### Default (stdio) Transport

```bash
python3 -m mcp_server.cpp_mcp_server
# or
clang-index-mcp
```

### HTTP Transport

```bash
python3 -m mcp_server.cpp_mcp_server --transport http --port 8000
```

This starts an HTTP server on `http://127.0.0.1:8000` with the following endpoints:

- `GET /` - Server information
- `GET /health` - Health check
- `POST /messages` - MCP JSON-RPC messages

### SSE Transport

```bash
python3 -m mcp_server.cpp_mcp_server --transport sse --port 8080
```

This starts an SSE server on `http://127.0.0.1:8080` with the following endpoints:

- `GET /` - Server information
- `GET /health` - Health check
- `GET /sse` - Server-Sent Events stream
- `POST /messages` - MCP JSON-RPC messages (for client requests)

### Custom Host and Port

```bash
# HTTP on custom port
python3 -m mcp_server.cpp_mcp_server --transport http --host 0.0.0.0 --port 9000

# SSE on custom port
python3 -m mcp_server.cpp_mcp_server --transport sse --host 127.0.0.1 --port 8888
```

## Using the HTTP API

### Health Check

```bash
curl http://127.0.0.1:8000/health
```

Response:
```json
{
  "status": "healthy",
  "transport": "http",
  "active_sessions": 0
}
```

### Server Information

```bash
curl http://127.0.0.1:8000/
```

Response:
```json
{
  "name": "C++ Code Analysis MCP Server",
  "version": "0.1.0",
  "transport": "http",
  "protocol": "MCP 1.0",
  "endpoints": {
    "health": "/health",
    "messages": "/messages"
  }
}
```

### Making MCP Requests

Send JSON-RPC messages to `/messages`:

```bash
# Initialize session and set project directory
curl -X POST http://127.0.0.1:8000/messages \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "set_project_directory",
      "arguments": {
        "project_path": "/path/to/cpp/project"
      }
    }
  }'
```

The response will include a session ID header:

```
Mcp-Session-Id: <uuid>
```

Use this session ID in subsequent requests to maintain session state:

```bash
curl -X POST http://127.0.0.1:8000/messages \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: <uuid-from-previous-response>" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "search_classes",
      "arguments": {
        "pattern": ".*",
        "project_only": true
      }
    }
  }'
```

## Using SSE (Server-Sent Events)

### Connecting to SSE Stream

```bash
curl -N http://127.0.0.1:8080/sse
```

This will establish an SSE connection and stream MCP JSON-RPC messages as they occur.

**Note:** The server now properly implements MCP SSE transport using `SseServerTransport`, which means you'll receive actual MCP protocol messages (not just keepalives and pings).

### Sending Requests with SSE

While connected to the SSE stream, you can send requests using the POST endpoint:

```bash
# In terminal 1: Connect to SSE stream
curl -N http://127.0.0.1:8080/sse

# In terminal 2: Send requests
curl -X POST http://127.0.0.1:8080/messages \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "set_project_directory",
      "arguments": {
        "project_path": "/path/to/cpp/project"
      }
    }
  }'
```

## Session Management

### HTTP Sessions

- Each unique `Mcp-Session-Id` creates a separate session
- If no session ID is provided, a new one is automatically generated
- **Session Timeout**: Sessions automatically expire after 1 hour (3600 seconds) of inactivity
- Sessions are cleaned up every minute by a background task
- Multiple concurrent sessions are supported

### SSE Sessions

- SSE connections are now properly implemented using the MCP SDK's `SseServerTransport`
- Each connection runs the MCP server protocol loop and sends actual MCP JSON-RPC messages
- Messages are sent via the SSE stream as MCP protocol events
- Client sends requests via POST to `/messages` endpoint
- Reconnection requires establishing a new SSE connection

### Session Lifecycle

1. **Creation**: Session created on first request without session ID
2. **Activity**: Each request updates the session's last activity timestamp
3. **Timeout**: After 1 hour of inactivity, session is automatically cleaned up
4. **Cleanup**: Background task removes expired sessions every 60 seconds

## Python Client Example

```python
import httpx
import asyncio
import json

async def main():
    base_url = "http://127.0.0.1:8000"
    session_id = None

    async with httpx.AsyncClient() as client:
        # Set project directory
        response = await client.post(
            f"{base_url}/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "set_project_directory",
                    "arguments": {
                        "project_path": "/path/to/project"
                    }
                }
            }
        )

        # Extract session ID
        session_id = response.headers.get("Mcp-Session-Id")
        print(f"Session ID: {session_id}")
        print(f"Response: {response.json()}")

        # Search classes (using same session)
        response = await client.post(
            f"{base_url}/messages",
            headers={"Mcp-Session-Id": session_id},
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "search_classes",
                    "arguments": {
                        "pattern": ".*"
                    }
                }
            }
        )

        print(f"Classes: {response.json()}")

if __name__ == "__main__":
    asyncio.run(main())
```

## JavaScript/TypeScript Client Example

```typescript
// Using fetch API
const baseUrl = 'http://127.0.0.1:8000';
let sessionId: string | null = null;

// Set project directory
const response1 = await fetch(`${baseUrl}/messages`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    jsonrpc: '2.0',
    id: 1,
    method: 'tools/call',
    params: {
      name: 'set_project_directory',
      arguments: {
        project_path: '/path/to/project'
      }
    }
  })
});

sessionId = response1.headers.get('Mcp-Session-Id');
const data1 = await response1.json();
console.log('Session ID:', sessionId);
console.log('Response:', data1);

// Search classes (using same session)
const response2 = await fetch(`${baseUrl}/messages`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Mcp-Session-Id': sessionId!
  },
  body: JSON.stringify({
    jsonrpc: '2.0',
    id: 2,
    method: 'tools/call',
    params: {
      name: 'search_classes',
      arguments: {
        pattern: '.*'
      }
    }
  })
});

const data2 = await response2.json();
console.log('Classes:', data2);
```

## SSE Client Example (JavaScript)

**Note:** The SSE transport now properly implements MCP protocol using `SseServerTransport` from the MCP SDK. The SSE stream sends MCP JSON-RPC messages as SSE events.

```javascript
const baseUrl = 'http://127.0.0.1:8080';

// Connect to SSE stream
// The server will send MCP JSON-RPC messages through the SSE connection
const eventSource = new EventSource(`${baseUrl}/sse`);

eventSource.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log('MCP message:', message);
  // Handle MCP JSON-RPC messages (requests, responses, notifications)
};

eventSource.onerror = (error) => {
  console.error('SSE error:', error);
};

// Send requests via POST endpoint
async function sendRequest() {
  const response = await fetch(`${baseUrl}/messages`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method: 'tools/call',
      params: {
        name: 'set_project_directory',
        arguments: {
          project_path: '/path/to/project'
        }
      }
    })
  });

  const data = await response.json();
  console.log('Response:', data);
}
```

## Error Handling

### HTTP Status Codes

- `200 OK` - Request successful
- `400 Bad Request` - Invalid JSON-RPC request
- `500 Internal Server Error` - Server error

### JSON-RPC Error Codes

- `-32700` - Parse error (invalid JSON)
- `-32600` - Invalid request
- `-32601` - Method not found
- `-32602` - Invalid params
- `-32603` - Internal error

Example error response:
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32600,
    "message": "Invalid request"
  },
  "id": null
}
```

## Performance Considerations

- HTTP transport is suitable for request/response patterns
- SSE transport is ideal for long-running operations with progress updates
- Multiple concurrent sessions are supported
- Each session maintains independent state
- Sessions consume server resources - close unused sessions

## Security Notes

- The default configuration binds to `127.0.0.1` (localhost only)
- For production use, consider:
  - Using `--host 0.0.0.0` to allow external connections
  - Implementing authentication/authorization
  - Using HTTPS/TLS encryption
  - Implementing rate limiting
  - Setting up CORS if needed

## Troubleshooting

### Server won't start

Check if the port is already in use:
```bash
lsof -i :8000
```

Try a different port:
```bash
python3 -m mcp_server.cpp_mcp_server --transport http --port 9000
```

### Session not found

Ensure you're using the same `Mcp-Session-Id` header in all requests for a session (HTTP transport only).

### SSE connection drops

SSE connections may timeout due to network or proxy settings. Implement reconnection logic in your client.

## Next Steps

- See [REQUIREMENTS_HTTP_SUPPORT.md](archived/REQUIREMENTS_HTTP_SUPPORT.md) for technical details
- Run tests: `pytest tests/test_http_transport.py tests/test_sse_transport.py`
- Check the main README for C++ analyzer functionality
