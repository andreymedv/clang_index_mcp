# HTTP/Streamable HTTP Protocol Support Requirements

## Overview
Add HTTP and Server-Sent Events (SSE) transport protocols to the clang_index_mcp server, in addition to the existing stdio transport.

## Objectives
1. Enable the MCP server to run over HTTP/HTTPS
2. Support Server-Sent Events (SSE) for real-time streaming updates
3. Maintain backward compatibility with existing stdio transport
4. Provide flexible deployment options (stdio, HTTP, or SSE)

## Technical Requirements

### 1. Protocol Support

#### 1.1 HTTP Transport (Streamable HTTP)
- **Description**: RESTful HTTP endpoint for synchronous request/response communication
- **Protocol**: HTTP/1.1 or HTTP/2
- **Format**: JSON-RPC 2.0 over HTTP
- **Methods**: POST for tool calls and requests
- **Headers**:
  - `Content-Type: application/json`
  - `x-mcp-session-id`: Session identifier
  - `x-mcp-protocol-version`: MCP protocol version
- **Response Format**: JSON with results or errors

#### 1.2 Server-Sent Events (SSE) Transport
- **Description**: Unidirectional streaming from server to client for real-time updates
- **Protocol**: SSE (Server-Sent Events) over HTTP
- **Format**: JSON-RPC 2.0 messages as SSE events
- **Headers**:
  - `Content-Type: text/event-stream`
  - `x-mcp-session-id`: Session identifier
  - `Last-Event-ID`: For resuming connections
- **Features**:
  - Automatic reconnection support
  - Event streaming for long-running operations
  - Progress updates during indexing

#### 1.3 Standard I/O (stdio) - Existing
- **Description**: Communication via standard input/output
- **Format**: JSON-RPC messages over stdin/stdout
- **Use Case**: CLI integration, process spawning

### 2. Server Implementation

#### 2.1 Transport Selection
- Command-line argument `--transport` with options:
  - `stdio` (default): Standard I/O transport
  - `http`: HTTP/Streamable HTTP transport
  - `sse`: Server-Sent Events transport

#### 2.2 Configuration
- **Port Configuration**: `--port <number>` (default: 8000)
- **Host Configuration**: `--host <address>` (default: 127.0.0.1)
- **Security**: Optional TLS/SSL support for HTTPS

#### 2.3 Endpoints

For HTTP/SSE transports:
- `POST /mcp/v1/messages`: Main endpoint for requests (HTTP)
- `GET /mcp/v1/sse`: SSE stream endpoint (SSE)
- `GET /health`: Health check endpoint
- `GET /`: Root endpoint with server information

### 3. Session Management

#### 3.1 Session Lifecycle
- Each client connection gets a unique session ID
- Session state includes:
  - Project directory configuration
  - Analyzer state
  - Indexing progress
- Sessions timeout after inactivity (configurable)

#### 3.2 Session Isolation
- Multiple concurrent clients supported
- Each session maintains independent analyzer state
- Thread-safe or async implementation

### 4. Error Handling

#### 4.1 HTTP Status Codes
- `200 OK`: Successful request
- `400 Bad Request`: Invalid JSON-RPC request
- `500 Internal Server Error`: Server-side errors
- `503 Service Unavailable`: Server not ready

#### 4.2 JSON-RPC Error Codes
- `-32700`: Parse error
- `-32600`: Invalid request
- `-32601`: Method not found
- `-32602`: Invalid params
- `-32603`: Internal error

### 5. Performance Requirements

#### 5.1 Concurrency
- Support at least 10 concurrent sessions
- Non-blocking I/O for HTTP/SSE
- Async implementation using asyncio

#### 5.2 Resource Management
- Proper cleanup of disconnected sessions
- Memory limits per session
- Connection timeout handling

### 6. Testing Requirements

#### 6.1 Unit Tests
- Transport initialization and configuration
- Request/response handling
- Session management
- Error handling

#### 6.2 Integration Tests
- End-to-end HTTP request/response flow
- SSE streaming and reconnection
- Multi-session scenarios
- Tool execution over HTTP/SSE

#### 6.3 Regression Tests
- Existing stdio functionality remains working
- All existing tests pass
- No performance degradation for stdio transport

### 7. Documentation Requirements

#### 7.1 Usage Documentation
- How to start server in HTTP/SSE mode
- Client connection examples
- Configuration options

#### 7.2 API Documentation
- HTTP endpoint specifications
- SSE event format
- Authentication (if implemented)

## Implementation Plan

### Phase 1: HTTP Transport
1. Create HTTP server module using MCP's `StreamableHTTPServerTransport`
2. Implement basic request/response handling
3. Add session management
4. Write unit tests

### Phase 2: SSE Transport
1. Create SSE server module using MCP's `SseServerTransport`
2. Implement event streaming for progress updates
3. Handle reconnection scenarios
4. Write unit tests

### Phase 3: Integration
1. Add transport selection to main server
2. Update command-line interface
3. Write integration tests
4. Update documentation

### Phase 4: Testing & Validation
1. Run regression tests
2. Fix any issues found
3. Performance testing
4. Security review

## Success Criteria

1. ✅ Server can start with `--transport http` or `--transport sse`
2. ✅ All existing tools work over HTTP/SSE transports
3. ⚠️ SSE provides real-time updates (keepalives implemented, progress updates future work)
4. ✅ Multiple concurrent clients supported
5. ✅ All existing tests pass
6. ✅ New tests have >80% code coverage
7. ✅ Documentation is complete and accurate

## Implementation Status

### ✅ Completed (v1.0)
- HTTP and SSE transport protocols
- Session management with timeouts (1 hour default)
- Command-line transport selection
- Health check and info endpoints
- Error handling with proper HTTP status codes
- JSON-RPC 2.0 compliance
- Multi-session support
- Comprehensive test suite
- Usage documentation
- macOS compatibility

### 🔄 Partially Implemented
- **SSE Progress Updates**: Currently sends keepalives only. Full indexing progress updates planned for future release
- **503 Service Unavailable**: Not used; server returns 500 for errors

### 📋 Future Work (Out of Scope for v1.0)
- Authentication/authorization
- Rate limiting
- CORS configuration
- TLS/SSL support
- Resource limits per session
- WebSocket transport
- gRPC transport
- Distributed deployment
- Advanced connection timeout handling
- Real-time SSE progress updates during indexing
