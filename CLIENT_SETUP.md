# Client Setup Guide

This guide provides detailed instructions for configuring the C++ Analyzer MCP Server with various AI coding assistants and IDEs.

## Table of Contents

- [Claude Desktop](#claude-desktop)
- [Claude Code (VS Code Extension)](#claude-code-vs-code-extension)
- [Cursor IDE](#cursor-ide)
- [Cline (VS Code Extension)](#cline-vs-code-extension)
- [Windsurf IDE](#windsurf-ide)
- [Continue (VS Code Extension)](#continue-vs-code-extension)
- [Generic MCP Client](#generic-mcp-client)

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
2. Review [COMPILE_COMMANDS_INTEGRATION.md](COMPILE_COMMANDS_INTEGRATION.md) for build system integration
3. Open an issue on [GitHub](https://github.com/andreymedv/clang_index_mcp/issues)
4. See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines
