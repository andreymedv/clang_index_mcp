# Client Setup Guide

This guide provides detailed instructions for configuring the C++ Analyzer MCP Server with various AI coding assistants and IDEs.

## Table of Contents

- [Claude Desktop](#claude-desktop)
- [Claude Code (VS Code Extension)](#claude-code-vs-code-extension)
- [Cursor IDE](#cursor-ide)
- [Cline (VS Code Extension)](#cline-vs-code-extension)
- [Windsurf IDE](#windsurf-ide)
- [Continue (VS Code Extension)](#continue-vs-code-extension)
- [LM Studio](#lm-studio)
- [Generic MCP Client](#generic-mcp-client)
- [HTTP/SSE Transport Configuration](#httpsse-transport-configuration)

## Prerequisites

Before configuring any client, ensure you have:

1. Completed the [Setup](README.md#setup) steps
2. The MCP server is working (test with `python -m mcp_server.cpp_mcp_server`)
3. Note the absolute path to your clang_index_mcp installation directory

## Claude Desktop

Claude Desktop is Anthropic's desktop application for conversational AI.

### Configuration

1. **Locate the configuration file:**
   - **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
   - **Linux:** `~/.config/Claude/claude_desktop_config.json`

2. **Add the MCP server configuration:**

```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "python",
      "args": [
        "-m",
        "mcp_server.cpp_mcp_server"
      ],
      "cwd": "/absolute/path/to/clang_index_mcp",
      "env": {
        "PYTHONPATH": "/absolute/path/to/clang_index_mcp"
      }
    }
  }
}
```

**For Windows:** Use backslashes and adjust Python path:
```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "C:\\path\\to\\clang_index_mcp\\mcp_env\\Scripts\\python.exe",
      "args": ["-m", "mcp_server.cpp_mcp_server"],
      "cwd": "C:\\path\\to\\clang_index_mcp",
      "env": {
        "PYTHONPATH": "C:\\path\\to\\clang_index_mcp"
      }
    }
  }
}
```

3. **Restart Claude Desktop** for changes to take effect

4. **Verify:** Start a conversation and the cpp-analyzer tools should be available

## Claude Code (VS Code Extension)

Claude Code is the official VS Code extension by Anthropic.

### Configuration

1. **Open VS Code Settings:**
   - Press `Ctrl+,` (Windows/Linux) or `Cmd+,` (macOS)
   - Search for "MCP"
   - Or edit `settings.json` directly

2. **Add to your VS Code `settings.json`:**

```json
{
  "claude.mcpServers": {
    "cpp-analyzer": {
      "command": "python",
      "args": [
        "-m",
        "mcp_server.cpp_mcp_server"
      ],
      "cwd": "/absolute/path/to/clang_index_mcp",
      "env": {
        "PYTHONPATH": "/absolute/path/to/clang_index_mcp"
      }
    }
  }
}
```

3. **Reload VS Code window:** Press `Ctrl+Shift+P` → "Developer: Reload Window"

4. **Usage:** When working on C++ projects, ask Claude to use the cpp-analyzer tools

### Using Virtual Environment

If you want to use the project's virtual environment:

```json
{
  "claude.mcpServers": {
    "cpp-analyzer": {
      "command": "/absolute/path/to/clang_index_mcp/mcp_env/bin/python",
      "args": ["-m", "mcp_server.cpp_mcp_server"],
      "cwd": "/absolute/path/to/clang_index_mcp"
    }
  }
}
```

**Windows:** Use `mcp_env\\Scripts\\python.exe`

## Cursor IDE

Cursor is an AI-first IDE built on VS Code.

### Configuration

1. **Create or edit the Cursor MCP config file:**
   - **macOS/Linux:** `~/.cursor/mcp.json`
   - **Windows:** `%USERPROFILE%\.cursor\mcp.json`

2. **Add the server configuration:**

```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "python",
      "args": [
        "-m",
        "mcp_server.cpp_mcp_server"
      ],
      "cwd": "/absolute/path/to/clang_index_mcp",
      "env": {
        "PYTHONPATH": "/absolute/path/to/clang_index_mcp"
      }
    }
  }
}
```

3. **Restart Cursor** to load the new configuration

4. **Usage:**
   - Open your C++ project in Cursor
   - In the AI chat, ask: "Use the cpp-analyzer to set the project directory to [your-project-path]"
   - Then query about your codebase

### Alternative: Project-Specific Configuration

Create a `.cursorrules` or `mcp.json` file in your C++ project root:

```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "/absolute/path/to/clang_index_mcp/mcp_env/bin/python",
      "args": ["-m", "mcp_server.cpp_mcp_server"],
      "cwd": "/absolute/path/to/clang_index_mcp"
    }
  }
}
```

## Cline (VS Code Extension)

Cline (formerly Claude Dev) is a VS Code extension for AI-assisted coding.

### Configuration

1. **Open Cline Settings in VS Code:**
   - Click the Cline icon in the sidebar
   - Open settings (gear icon)
   - Or edit `settings.json` directly

2. **Add to VS Code `settings.json`:**

```json
{
  "cline.mcpServers": {
    "cpp-analyzer": {
      "command": "python",
      "args": [
        "-m",
        "mcp_server.cpp_mcp_server"
      ],
      "cwd": "/absolute/path/to/clang_index_mcp",
      "env": {
        "PYTHONPATH": "/absolute/path/to/clang_index_mcp"
      }
    }
  }
}
```

3. **Reload the extension:**
   - Press `Ctrl+Shift+P` → "Developer: Reload Window"
   - Or restart VS Code

4. **Usage:**
   - Open Cline panel
   - Ask it to use the cpp-analyzer tool
   - Example: "Use cpp-analyzer to find all classes in the project"

## Windsurf IDE

Windsurf is an AI-native IDE for developers.

### Configuration

1. **Open Windsurf Settings:**
   - Navigate to Settings → Extensions → MCP Servers
   - Or edit the configuration file directly

2. **Locate the Windsurf config file:**
   - **macOS:** `~/Library/Application Support/Windsurf/mcp_config.json`
   - **Windows:** `%APPDATA%\Windsurf\mcp_config.json`
   - **Linux:** `~/.config/Windsurf/mcp_config.json`

3. **Add the server configuration:**

```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "python",
      "args": [
        "-m",
        "mcp_server.cpp_mcp_server"
      ],
      "cwd": "/absolute/path/to/clang_index_mcp",
      "env": {
        "PYTHONPATH": "/absolute/path/to/clang_index_mcp"
      }
    }
  }
}
```

4. **Restart Windsurf** to apply changes

5. **Usage:** The cpp-analyzer tools will be available in the AI assistant panel

## Continue (VS Code Extension)

Continue is an open-source VS Code extension for AI coding assistance.

### Configuration

1. **Open Continue configuration:**
   - Click Continue icon in sidebar
   - Click gear icon for settings
   - This opens `~/.continue/config.json`

2. **Add MCP server to the configuration:**

```json
{
  "models": [
    // ... your existing models ...
  ],
  "mcpServers": [
    {
      "name": "cpp-analyzer",
      "command": "python",
      "args": [
        "-m",
        "mcp_server.cpp_mcp_server"
      ],
      "cwd": "/absolute/path/to/clang_index_mcp",
      "env": {
        "PYTHONPATH": "/absolute/path/to/clang_index_mcp"
      }
    }
  ]
}
```

3. **Reload Continue extension** or restart VS Code

4. **Usage:** Tools will be available in Continue chat sessions

## LM Studio

LM Studio is a desktop application for running local LLMs with MCP support.

### ⚠️ Known Compatibility Issues

Testing with **LM Studio version 0.3.35 build 1** revealed significant compatibility issues with this MCP server:

#### stdio Transport Issues
- **Problem**: LM Studio disconnects from the MCP server after a short period of inactivity
- **Impact**: Makes background analysis impossible - server loses connection mid-indexing
- **Not recommended** for projects requiring long-running operations

#### HTTP/SSE Transport Issues
- **Problem**: LM Studio's MCP bridge does not properly support HTTP or SSE transports
- **Symptoms**:
  - Returns "405 Method Not Allowed" errors
  - Continues treating HTTP endpoints as SSE regardless of configuration
  - Connection closes immediately after establishment
- **Testing details**: Attempted both HTTP and SSE transports with proper server configuration, but LM Studio's MCP bridge consistently failed to recognize the transport type

**Example error from LM Studio logs:**
```
Error in LM Studio MCP bridge process: SSE error: Non-200 status code (405)
```

Even when server was running with HTTP transport, LM Studio still attempted SSE-style requests.

### Configuration Attempted (Did Not Work)

**stdio transport (disconnects on inactivity):**
```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "python",
      "args": ["-m", "mcp_server.cpp_mcp_server"],
      "cwd": "/absolute/path/to/clang_index_mcp",
      "env": {
        "PYTHONPATH": "/absolute/path/to/clang_index_mcp"
      }
    }
  }
}
```

**HTTP transport (405 errors):**
```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "url": "http://127.0.0.1:8080/mcp/v1/messages"
    }
  }
}
```

### Recommendation

**LM Studio is not recommended for use with this MCP server** due to the issues above. Consider using:
- **Claude Desktop** - Excellent MCP support with persistent connections
- **Claude Code** (VS Code) - Reliable stdio transport
- **Cursor IDE** - Good MCP integration
- **Cline** (VS Code) - Stable MCP support
- **Continue** (VS Code) - Open-source alternative

These clients properly handle long-running indexing operations and maintain stable connections.

### If You Must Use LM Studio

If LM Studio is your only option:
1. Keep projects small (< 1000 files) to avoid timeout issues
2. Be prepared to manually restart the MCP connection frequently
3. Monitor the LM Studio developer logs for disconnection events
4. Avoid background indexing - index only when actively using the tools

**Note:** These issues may be resolved in future LM Studio releases. This information is accurate as of LM Studio 0.3.35 build 1.

## Generic MCP Client

For any MCP-compatible client not listed above:

### Standard Configuration Format

Most MCP clients use a similar configuration format:

```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "python",
      "args": ["-m", "mcp_server.cpp_mcp_server"],
      "cwd": "/absolute/path/to/clang_index_mcp",
      "env": {
        "PYTHONPATH": "/absolute/path/to/clang_index_mcp"
      }
    }
  }
}
```

### Configuration Elements

- **command**: Path to Python interpreter
  - Use system Python: `"python"` or `"python3"`
  - Use virtual environment: `"/path/to/mcp_env/bin/python"`

- **args**: Arguments to pass to Python
  - `["-m", "mcp_server.cpp_mcp_server"]` - runs the module

- **cwd**: Working directory for the server
  - Must be the root of the clang_index_mcp repository

- **env**: Environment variables
  - `PYTHONPATH`: Ensures Python can find the mcp_server module

## HTTP/SSE Transport Configuration

The examples above use **stdio** transport (standard input/output), which is the default for most MCP clients. However, the server also supports **HTTP** and **SSE** (Server-Sent Events) transports for:

- Web-based integrations
- Remote server deployments
- Custom client implementations
- Multi-client scenarios
- Testing and debugging

### When to Use HTTP/SSE

**Use stdio (default)** when:
- Integrating with desktop applications (Claude Desktop, VS Code extensions)
- The client and server run on the same machine
- The MCP client spawns the server process

**Use HTTP/SSE** when:
- Building web-based integrations
- Deploying the server remotely
- Multiple clients need to connect to the same server
- You need RESTful API access
- You want real-time progress updates (SSE)

### Starting the Server with HTTP/SSE

#### HTTP Transport

```bash
# Start HTTP server on default port 8000
python -m mcp_server.cpp_mcp_server --transport http --port 8000

# Start on custom port
python -m mcp_server.cpp_mcp_server --transport http --host 127.0.0.1 --port 9000

# Allow external connections (use with caution)
python -m mcp_server.cpp_mcp_server --transport http --host 0.0.0.0 --port 8000
```

#### SSE Transport

```bash
# Start SSE server on default port 8080
python -m mcp_server.cpp_mcp_server --transport sse --port 8080

# Start on custom port
python -m mcp_server.cpp_mcp_server --transport sse --host 127.0.0.1 --port 9000
```

### MCP Client Configuration for HTTP/SSE

Some MCP clients support HTTP/SSE transport. Check your client's documentation for specific configuration details.

#### Example: Generic HTTP Client Configuration

If your MCP client supports HTTP transport:

```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "transport": "http",
      "url": "http://127.0.0.1:8000/mcp/v1/messages",
      "headers": {
        "Content-Type": "application/json"
      }
    }
  }
}
```

#### Example: Generic SSE Client Configuration

If your MCP client supports SSE transport:

```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "transport": "sse",
      "url": "http://127.0.0.1:8080/mcp/v1/sse",
      "messagesUrl": "http://127.0.0.1:8080/mcp/v1/messages"
    }
  }
}
```

### Running as a Background Service

For remote or persistent deployments, run the server as a background service:

#### Using systemd (Linux)

Create `/etc/systemd/system/cpp-analyzer.service`:

```ini
[Unit]
Description=C++ Analyzer MCP Server
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/clang_index_mcp
Environment="PYTHONPATH=/path/to/clang_index_mcp"
ExecStart=/path/to/clang_index_mcp/mcp_env/bin/python -m mcp_server.cpp_mcp_server --transport http --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable cpp-analyzer
sudo systemctl start cpp-analyzer
sudo systemctl status cpp-analyzer
```

#### Using Docker

Create a `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Copy server files
COPY . .

# Install dependencies
RUN pip install -r requirements.txt

# Download libclang
RUN python scripts/download_libclang.py

# Expose HTTP port
EXPOSE 8000

# Run server
CMD ["python", "-m", "mcp_server.cpp_mcp_server", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:
```bash
docker build -t cpp-analyzer-mcp .
docker run -d -p 8000:8000 --name cpp-analyzer cpp-analyzer-mcp
```

#### Using screen/tmux (Quick Solution)

```bash
# Using screen
screen -S cpp-analyzer
cd /path/to/clang_index_mcp
source mcp_env/bin/activate
python -m mcp_server.cpp_mcp_server --transport http --port 8000
# Press Ctrl+A then D to detach

# Reattach later
screen -r cpp-analyzer

# Using tmux
tmux new -s cpp-analyzer
cd /path/to/clang_index_mcp
source mcp_env/bin/activate
python -m mcp_server.cpp_mcp_server --transport http --port 8000
# Press Ctrl+B then D to detach

# Reattach later
tmux attach -t cpp-analyzer
```

### Custom Client Implementation

For building custom clients that connect to HTTP/SSE, see the comprehensive examples in [HTTP_USAGE.md](docs/HTTP_USAGE.md):

- **Python client** using httpx
- **JavaScript/TypeScript client** using fetch API
- **SSE client** using EventSource
- Complete API reference
- Session management
- Error handling

### Security Considerations for HTTP/SSE

When running the server with HTTP/SSE transport:

1. **Default binding** is `127.0.0.1` (localhost only)
2. **For production deployments:**
   - Use HTTPS/TLS encryption (place behind reverse proxy like nginx)
   - Implement authentication/authorization
   - Configure CORS if needed
   - Set up rate limiting
   - Use firewall rules to restrict access
   - Monitor logs for suspicious activity

3. **Example nginx reverse proxy with TLS:**

```nginx
server {
    listen 443 ssl http2;
    server_name cpp-analyzer.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Health Check Endpoints

When using HTTP/SSE, the server provides health check endpoints:

```bash
# Check server health
curl http://127.0.0.1:8000/health

# Get server information
curl http://127.0.0.1:8000/
```

Example health check response:
```json
{
  "status": "healthy",
  "transport": "http",
  "active_sessions": 2
}
```

### Session Management

HTTP/SSE transports support multiple concurrent sessions:

- Each client gets a unique session ID (`x-mcp-session-id` header)
- Sessions timeout after 1 hour of inactivity
- Multiple clients can connect to the same server instance
- Each session maintains independent project state

See [HTTP_USAGE.md](docs/HTTP_USAGE.md) for detailed session management examples.

## Common Configuration Issues

### Issue: "Module not found" error

**Solution:** Check that:
1. The `cwd` points to the repository root
2. The `PYTHONPATH` is set correctly
3. Dependencies are installed: `pip install -r requirements.txt`

### Issue: "libclang not found" error

**Solution:** Run the setup script to download libclang:
```bash
./server_setup.sh  # Linux/macOS
server_setup.bat   # Windows
```

Or manually run:
```bash
python scripts/download_libclang.py
```

### Issue: Server starts but tools don't work

**Solution:** Verify the server works standalone:
```bash
cd /path/to/clang_index_mcp
python -m mcp_server.cpp_mcp_server
```

If it prints initialization messages and waits for input, it's working correctly.

### Issue: Wrong Python version

**Solution:** Ensure Python 3.9+ is used:
```bash
python --version  # Should be 3.9 or higher
```

If needed, explicitly specify the Python path:
```json
{
  "command": "/usr/bin/python3.11"  // or your Python 3.9+ path
}
```

## Using the Server

Once configured, you can use these commands in your AI assistant:

### Initial Setup
```
Use the cpp-analyzer tool to set the project directory to /path/to/your/cpp/project
```

### Example Queries
- "Find all classes containing 'Network'"
- "Show me the methods in the Player class"
- "What functions call the Initialize method?"
- "Show the inheritance hierarchy for GameObject"
- "Find all functions that handle user input"

### Tips
1. **Initial indexing** may take several minutes for large projects
2. **Results are cached** for faster subsequent queries
3. **Use specific patterns** for better results (e.g., "Player.*" for classes starting with Player)
4. **Project-only searches** exclude third-party dependencies by default

## Advanced Configuration

### Using a Custom Config File

You can specify a custom configuration file location:

```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "python",
      "args": ["-m", "mcp_server.cpp_mcp_server"],
      "cwd": "/path/to/clang_index_mcp",
      "env": {
        "CPP_ANALYZER_CONFIG": "/path/to/custom/cpp-analyzer-config.json"
      }
    }
  }
}
```

### Debug Mode

To enable debug output for troubleshooting:

```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "python",
      "args": ["-m", "mcp_server.cpp_mcp_server"],
      "cwd": "/path/to/clang_index_mcp",
      "env": {
        "MCP_DEBUG": "1",
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

## Getting Help

If you encounter issues:

1. Check the [Troubleshooting](README.md#troubleshooting) section in README.md
2. Review [COMPILE_COMMANDS_INTEGRATION.md](docs/COMPILE_COMMANDS_INTEGRATION.md) for build system integration
3. Open an issue on [GitHub](https://github.com/andreymedv/clang_index_mcp/issues)
4. See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines
