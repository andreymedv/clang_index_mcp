# C++ MCP Server

An MCP (Model Context Protocol) server for analyzing C++ codebases using libclang.

## About This Fork

This project is a fork of [kandrwmrtn/cplusplus_mcp](https://github.com/kandrwmrtn/cplusplus_mcp). The main intention of this fork was to add support for projects described by `compile_commands.json`.

**⚠️ Development Status**: This MCP server is currently in active development and is **not suitable for production use**. Use at your own risk.

**Platform Support**: This server has been primarily developed and tested to run on **Linux and macOS**. While Windows support may work, it is not the primary focus of development.

## Why Use This?

Instead of having an AI Agent grep through your C++ codebase trying to understand the structure, this server provides semantic understanding of your code. Agents can instantly find classes, functions, and their relationships without getting lost in thousands of files. It understands C++ syntax, inheritance hierarchies, and call graphs - giving the AI Agent the ability to navigate your codebase like an IDE would.

**Note**: These tools are primarily intended for use with weaker LLM models running locally (e.g., via LM Studio or Ollama) to help them understand complex codebases, but they work equally well with frontier models like Claude 3.5 Sonnet or GPT-4o.

## Features

Consolidated C++ code analysis tools (unified from multiple individual tools):
- **set_project** - REQUIRED FIRST STEP: Set project directory or config file and wait for indexing completion.
- **sync_project** - Check system status or trigger an incremental/full project refresh.
- **find_symbols_by_pattern** - Discover classes and functions by name pattern with namespace and file filters.
- **find_in_file** - List all symbols defined in a specific file.
- **get_class_info** - Get detailed class information (methods, members, inheritance).
- **get_class_hierarchy** - Get complete inheritance hierarchy for a class (ancestors, descendants, or both).
- **get_type_alias_info** - Resolve type aliases (`using`, `typedef`) and template aliases.
- **find_outgoing_calls** - Find functions called by a specific function (callees).
- **find_incoming_calls** - Find functions that call a specific function (callers).
- **trace_execution_path** - Find execution paths (call chains) between two functions.

**Qualified Names Support**:
- **Namespace-Aware Search**: Search by qualified patterns like `"ui::View"`, `"app::Database::save"`.
- **Template Specialization Detection**: Distinguish `template<> void foo<int>()` from generic `template<typename T> void foo(T)`.
- **Disambiguation**: All results include `qualified_name` and `namespace` fields.

**Additional Capabilities:**
- **Automatic Header Analysis**: Project headers are automatically analyzed when included by source files.
- **Smart Deduplication**: Headers are processed only once for optimal performance.
- **Incremental Analysis**: Detects changes and re-analyzes only affected files (30-300x faster).
- **Error Recovery**: Extracts symbols even from files with non-fatal parsing errors.

## Transport Protocols

The server supports multiple transport protocols:

### stdio (Default)
Standard input/output transport for MCP client integration (Claude Desktop, etc.):
```bash
python -m mcp_server.cpp_mcp_server
```

### HTTP (Streamable HTTP)
RESTful HTTP transport for API access:
```bash
python -m mcp_server.cpp_mcp_server --transport http --host 127.0.0.1 --port 8000
```

### SSE (Server-Sent Events)
Real-time streaming transport for event-driven applications:
```bash
python -m mcp_server.cpp_mcp_server --transport sse --host 127.0.0.1 --port 8000
```

For detailed HTTP/SSE usage, see **[HTTP_USAGE.md](docs/HTTP_USAGE.md)**

## Prerequisites

- Python 3.10 or higher
- pip (Python package manager)
- Git (for cloning the repository)
- LLVM's libclang (the setup scripts will attempt to download a portable build)

## Setup

1. Clone the repository:
```bash
git clone https://github.com/andreymedv/clang_index_mcp.git
cd clang_index_mcp
```

2. Run the setup script:
   - **Linux/macOS**:
     ```bash
     ./server_setup.sh
     ```
   - **Windows**:
     ```bash
     server_setup.bat
     ```

3. Test the installation:
```bash
source mcp_env/bin/activate  # Linux/macOS
python scripts/test_installation.py
```

## Performance Optimization

The analyzer is optimized for performance on multi-core systems.

### Optional Dependencies
For large projects, install `orjson` for 3-5x faster JSON parsing:
```bash
pip install .[performance]
```

### Automatic Optimizations
1. **GIL Bypass**: Uses `ProcessPoolExecutor` for true parallel parsing.
2. **Binary Caching**: Parsed `compile_commands.json` and symbols are cached for fast subsequent startups.
3. **Intelligent Incremental Analysis**: Re-analyzes only affected files when changes are detected.

## Client Configuration

This MCP server can be used with various AI coding assistants and IDEs. See **[CLIENT_SETUP.md](CLIENT_SETUP.md)** for detailed instructions for:
- Claude Desktop / Claude Code
- Cursor / Windsurf
- Cline / Continue

### Generic CLI Agent Configuration

To use this with an MCP-compatible CLI Agent, add the server to your configuration:

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

## Usage with AI Agent

Once configured, you can use the C++ analyzer in your conversations:

1. First, set your project directory:
   ```
   "Set the project directory to /path/to/your/cpp/project"
   ```

2. Then you can ask questions like:
   - "Find all classes containing 'Actor'"
   - "Show me the Component class details"
   - "Find all functions that call Update()"
   - "What functions does Render() call?"
   - "Show me the inheritance hierarchy for GameObject"

## Configuration Options

The server behavior can be configured via a `.cpp-analyzer-config.json` file. The server looks for this file in:
1. The path specified by the `CPP_ANALYZER_CONFIG` environment variable.
2. The project root directory.
3. A path explicitly passed to the `set_project` tool.

### Example Configuration

```json
{
  "project_root": ".",
  "exclude_directories": [".git", "build", "node_modules"],
  "include_dependencies": true,
  "max_workers": null,
  "query_behavior": "allow_partial",
  "compile_commands": {
    "enabled": true,
    "path": "compile_commands.json"
  }
}
```

### Key Options

- **project_root**: (Optional) Specify the source root relative to the config file. This allows placing the config file outside the source tree.
- **exclude_directories**: Directories to skip during project scanning.
- **include_dependencies**: Whether to analyze files in dependency directories (e.g., `third_party`).
- **max_workers**: Number of worker processes (default: `null` = use all CPU cores).
- **query_behavior**: `allow_partial` (return results during indexing), `block` (wait for indexing), or `reject`.
- **compile_commands**: Configure the path and behavior for `compile_commands.json` integration.

**For detailed information about compile_commands.json integration, see [COMPILE_COMMANDS_INTEGRATION.md](docs/COMPILE_COMMANDS_INTEGRATION.md)**

## Troubleshooting

### Common Issues

1. **"libclang not found" error**
   - Run the setup script to download libclang automatically, or set `LIBCLANG_PATH` environment variable to the path of your `libclang.so`/`.dylib`/`.dll`.

2. **Server fails to start**
   - Ensure Python 3.10+ is installed and all dependencies from `requirements.txt` are available.

3. **Parse warnings vs. fatal errors**
   - The analyzer extracts what it can from files with syntax errors. If a file fails fatally, check its entry in `compile_commands.json` or run `python scripts/diagnose_parse_errors.py`.
