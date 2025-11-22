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
- `POST /mcp/v1/messages` - MCP JSON-RPC messages

### SSE Transport

```bash
python3 -m mcp_server.cpp_mcp_server --transport sse --port 8080
```

This starts an SSE server on `http://127.0.0.1:8080` with the following endpoints:

- `GET /` - Server information
- `GET /health` - Health check
- `GET /mcp/v1/sse` - Server-Sent Events stream
- `POST /mcp/v1/messages` - MCP JSON-RPC messages (for client requests)

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
    "messages": "/mcp/v1/messages"
  }
}
```

### Making MCP Requests

Send JSON-RPC messages to `/mcp/v1/messages`:

```bash
# Initialize session and set project directory
curl -X POST http://127.0.0.1:8000/mcp/v1/messages \
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
x-mcp-session-id: <uuid>
```

Use this session ID in subsequent requests to maintain session state:

```bash
curl -X POST http://127.0.0.1:8000/mcp/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-mcp-session-id: <uuid-from-previous-response>" \
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
curl -N http://127.0.0.1:8080/mcp/v1/sse
```

This will establish an SSE connection and stream events as they occur.

Example events:
```
event: connected
data: {"session_id": "<uuid>"}

: keepalive

event: progress
data: {"indexed": 10, "total": 100, "percentage": 10.0}

: keepalive
```

### Sending Requests with SSE

While connected to the SSE stream, you can send requests using the POST endpoint with the same session ID:

```bash
# In terminal 1: Connect to SSE stream
curl -N http://127.0.0.1:8080/mcp/v1/sse

# In terminal 2: Send requests (note: extract session_id from SSE stream first)
curl -X POST http://127.0.0.1:8080/mcp/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-mcp-session-id: <session-id-from-sse>" \
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

- Each unique `x-mcp-session-id` creates a separate session
- If no session ID is provided, a new one is automatically generated
- **Session Timeout**: Sessions automatically expire after 1 hour (3600 seconds) of inactivity
- Sessions are cleaned up every minute by a background task
- Multiple concurrent sessions are supported

### SSE Sessions

- SSE connections automatically create a session
- The session ID is provided in the initial connection event
- Reconnection with the same session ID resumes the session
- Long-running operations stream keepalive events (`: keepalive`)
- **Note**: Full indexing progress updates are planned for a future release

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
            f"{base_url}/mcp/v1/messages",
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
        session_id = response.headers.get("x-mcp-session-id")
        print(f"Session ID: {session_id}")
        print(f"Response: {response.json()}")

        # Search classes (using same session)
        response = await client.post(
            f"{base_url}/mcp/v1/messages",
            headers={"x-mcp-session-id": session_id},
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
const response1 = await fetch(`${baseUrl}/mcp/v1/messages`, {
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

sessionId = response1.headers.get('x-mcp-session-id');
const data1 = await response1.json();
console.log('Session ID:', sessionId);
console.log('Response:', data1);

// Search classes (using same session)
const response2 = await fetch(`${baseUrl}/mcp/v1/messages`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'x-mcp-session-id': sessionId!
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

```javascript
const baseUrl = 'http://127.0.0.1:8080';
let sessionId = null;

// Connect to SSE stream
const eventSource = new EventSource(`${baseUrl}/mcp/v1/sse`);

eventSource.addEventListener('connected', (event) => {
  const data = JSON.parse(event.data);
  sessionId = data.session_id;
  console.log('Connected with session:', sessionId);

  // Now you can send requests using the session ID
  sendRequest();
});

eventSource.addEventListener('progress', (event) => {
  const data = JSON.parse(event.data);
  console.log('Progress:', data);
});

eventSource.onerror = (error) => {
  console.error('SSE error:', error);
};

async function sendRequest() {
  const response = await fetch(`${baseUrl}/mcp/v1/messages`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-mcp-session-id': sessionId
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

Ensure you're using the same `x-mcp-session-id` header in all requests for a session.

### SSE connection drops

SSE connections may timeout due to network or proxy settings. Implement reconnection logic in your client.

## Next Steps

- See [REQUIREMENTS_HTTP_SUPPORT.md](REQUIREMENTS_HTTP_SUPPORT.md) for technical details
- Run tests: `pytest tests/test_http_transport.py tests/test_sse_transport.py`
- Check the main README for C++ analyzer functionality
