# C++ MCP Server

An MCP (Model Context Protocol) server for analyzing C++ codebases using libclang.

## About This Fork

This project is a fork of [kandrwmrtn/cplusplus_mcp](https://github.com/kandrwmrtn/cplusplus_mcp). The main intention of this fork was to add support for projects described by `compile_commands.json`.

**⚠️ Development Status**: This MCP server is currently in active development and is **not suitable for production use**. Use at your own risk.

**Platform Support**: This server has been primarily developed and tested to run on **Linux and macOS**. While Windows support may work, it is not the primary focus of development.

## Why Use This?

Instead of having Claude grep through your C++ codebase trying to understand the structure, this server provides semantic understanding of your code. Claude can instantly find classes, functions, and their relationships without getting lost in thousands of files. It understands C++ syntax, inheritance hierarchies, and call graphs - giving Claude the ability to navigate your codebase like an IDE would.

## Features

Context-efficient C++ code analysis:
- **search_classes** - Find classes by name pattern
- **search_functions** - Find functions by name pattern  
- **get_class_info** - Get detailed class information (methods, members, inheritance)
- **get_function_signature** - Get function signatures and parameters
- **find_in_file** - Search symbols within specific files
- **get_class_hierarchy** - Get complete inheritance hierarchy for a class
- **get_derived_classes** - Find all classes that inherit from a base class
- **find_callers** - Find all functions that call a specific function
- **find_callees** - Find all functions called by a specific function
- **get_call_path** - Find call paths from one function to another

**Additional Capabilities:**
- **Automatic Header Analysis**: When using `compile_commands.json`, project headers are automatically analyzed when included by source files
- **Smart Deduplication**: Headers included by multiple source files are processed only once for optimal performance
- **Incremental Analysis**: Detects changes and re-analyzes only affected files for fast refreshes (30-300x faster than full re-analysis)
- **Error Recovery**: Leverages libclang's error recovery to extract symbols from files with non-fatal parsing errors, providing partial results instead of complete failure

## Transport Protocols

The server supports multiple transport protocols for different use cases:

### stdio (Default)
Standard input/output transport for MCP client integration (Claude Desktop, Claude Code, etc.):
```bash
python -m mcp_server.cpp_mcp_server
```

### HTTP (Streamable HTTP) ✨ New
RESTful HTTP transport for API access and web integrations:
```bash
python -m mcp_server.cpp_mcp_server --transport http --host 127.0.0.1 --port 8000
```

### SSE (Server-Sent Events)
Real-time streaming transport for event-driven applications:
```bash
python -m mcp_server.cpp_mcp_server --transport sse --host 127.0.0.1 --port 8000
```

**Features:**
- Multi-session support with automatic session management
- 1-hour session timeout with automatic cleanup
- Health check endpoints for monitoring
- JSON-RPC 2.0 protocol compliance
- Graceful shutdown with resource cleanup

For detailed HTTP/SSE usage instructions, examples, and API reference, see **[HTTP_USAGE.md](docs/HTTP_USAGE.md)**

## Prerequisites

- Python 3.9 or higher
- pip (Python package manager)
- Git (for cloning the repository)
- LLVM's libclang (the setup scripts will attempt to download a portable build)

## Setup

1. Clone the repository:
```bash
git clone https://github.com/andreymedv/clang_index_mcp.git
cd clang_index_mcp
```

2. Run the setup script (this creates a virtual environment, installs dependencies, and fetches libclang if possible):
   - **Linux/macOS** (recommended):
     ```bash
     ./server_setup.sh
     ```
   - **Windows** (not primary platform):
     ```bash
     server_setup.bat
     ```

3. Test the installation (recommended):
```bash
# Activate the virtual environment first
source mcp_env/bin/activate  # Linux/macOS
# OR: mcp_env\Scripts\activate  # Windows

# Run the installation test
python scripts/test_installation.py
```

This will verify that all components are properly installed and working. The test script lives at `scripts/test_installation.py`.

## Performance Optimization

The analyzer is optimized for performance on multi-core systems, but you can further improve performance with these optional enhancements:

### Optional Dependencies

**For Large Projects (recommended):**

Install the performance extras package:
```bash
pip install .[performance]
```

Or install orjson directly:
```bash
pip install orjson>=3.0.0
```

Benefits:
- **3-5x faster** JSON parsing for large `compile_commands.json` files (40MB+)
- Automatically used if installed, no configuration needed
- Particularly beneficial for projects with 1000+ compilation units
- Falls back gracefully to stdlib json if not available

### Performance Features

The analyzer includes several automatic optimizations:

1. **GIL Bypass (enabled by default)**
   - Uses `ProcessPoolExecutor` for true parallel parsing
   - Bypasses Python's Global Interpreter Lock
   - 6-7x speedup on 4+ core systems
   - Can be disabled via `CPP_ANALYZER_USE_THREADS=true` environment variable

2. **Binary Caching**
   - Parsed `compile_commands.json` cached in `.mcp_cache/<project>/compile_commands/<hash>.cache`
   - 10-100x faster subsequent startups for large projects
   - Automatically invalidated when `compile_commands.json` changes

3. **Bulk Symbol Writes**
   - Dramatically reduced lock contention during parallel parsing
   - Symbols collected in thread-local buffers, written in bulk
   - Reduces lock acquisitions from O(symbols) to O(1) per file

### Performance Diagnostics

If you experience slow analysis, use the diagnostic tools:

```bash
# Profile analysis performance (identify bottlenecks)
python scripts/profile_analysis.py /path/to/project

# Check if GIL is limiting parallelism
python scripts/diagnose_gil.py /path/to/project
```

The profiling tool shows time spent in:
- libclang parsing
- AST traversal
- Lock contention
- Cache operations

### Worker Configuration

By default, the analyzer uses `os.cpu_count()` workers. For slow hosts or limited resources:
- This is automatically optimized for CPU-bound parsing workload
- ProcessPool mode provides best performance on multi-core systems
- ThreadPool mode available via `CPP_ANALYZER_USE_THREADS=true` (not recommended)

## SQLite Cache

The analyzer uses a high-performance SQLite cache for symbol storage:

### Key Features

- **FTS5 Full-Text Search**: Lightning-fast symbol searches with prefix matching (2-5ms for 100K symbols)
- **Concurrent Access**: WAL mode enables safe multi-process access
- **Efficient Storage**: Compact database format with automatic maintenance
- **Health Monitoring**: Built-in diagnostics and integrity checks
- **Database Maintenance**: Automatic VACUUM, OPTIMIZE, and ANALYZE

### Diagnostic Tools

Two command-line tools are included for cache management:

```bash
# View comprehensive cache statistics
python scripts/cache_stats.py

# Diagnose cache health and get recommendations
python scripts/diagnose_cache.py
```

### More Information

- **Configuration**: See [CONFIGURATION.md](CONFIGURATION.md) for cache settings
- **Architecture**: See [ANALYSIS_STORAGE_ARCHITECTURE.md](docs/development/ANALYSIS_STORAGE_ARCHITECTURE.md) for technical details
- **Troubleshooting**: See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for cache-specific issues

## Intelligent Incremental Analysis (New in v3.1.0)

The analyzer now features intelligent incremental analysis that dramatically reduces re-analysis time when files change. Instead of re-analyzing your entire project, only affected files are re-parsed.

### How It Works

The incremental analysis system automatically:
- **Tracks file changes** via MD5 hashing
- **Builds dependency graphs** to understand which files include which headers
- **Detects compilation changes** by diffing `compile_commands.json` entries
- **Cascades header changes** to all dependent files

When you refresh the project, the analyzer intelligently determines the minimal set of files that need re-analysis.

### Performance Impact

| Scenario | Before (Full Re-analysis) | After (Incremental) | Speedup |
|----------|--------------------------|---------------------|---------|
| Single source file changed | 30-60s | <1s | **30-60x faster** |
| Header file changed (10 dependents) | 30-60s | 3-5s | **6-10x faster** |
| No changes detected | 30-60s | <0.1s | **300-600x faster** |
| `compile_commands.json` changed (1 entry) | 30-60s | 1-2s | **15-30x faster** |

*Times based on a medium-sized project (~1000 files)*

### Multi-Configuration Support

Projects are uniquely identified by the combination of:
- Source directory path
- Configuration file path

This enables you to work with the same source code using different build configurations (Debug/Release, different compiler flags, etc.) without cache conflicts. Each configuration gets its own cache directory.

### Using Incremental Analysis

**1. Automatic refresh on project initialization (recommended):**
```
"Set project directory to /my/project with config file /my/project/.cpp-analyzer-config.json and auto_refresh enabled"
```

The analyzer will automatically detect and re-analyze any changes since the last session.

**2. Manual refresh:**
```
"Refresh the project using incremental analysis"
```

The analyzer will detect all changes and re-analyze only affected files.

**3. Force full refresh (when needed):**
```
"Refresh the project with force_full enabled"
```

Re-analyzes everything from scratch. Use this after major configuration changes or if the cache seems corrupted.

### What Changes Are Detected?

1. **Source File Changes** → Only that file is re-analyzed
2. **Header File Changes** → All files that include it (directly or transitively) are re-analyzed
3. **New Files Added** → New files are analyzed
4. **Files Deleted** → Removed from cache (no re-analysis needed)
5. **`compile_commands.json` Changes** → Only files with changed compilation flags are re-analyzed

### More Information

- **User Guide**: See [CONFIGURATION.md](CONFIGURATION.md#incremental-analysis) for detailed usage instructions
- **Architecture**: See [docs/development/INCREMENTAL_ANALYSIS_DESIGN.md](docs/development/INCREMENTAL_ANALYSIS_DESIGN.md) for technical details

## Client Configuration

This MCP server can be used with various AI coding assistants and IDEs. See **[CLIENT_SETUP.md](CLIENT_SETUP.md)** for detailed configuration instructions for:

- **Claude Desktop** - Anthropic's desktop application
- **Claude Code** - VS Code extension by Anthropic
- **Cursor** - AI-first IDE
- **Cline** - VS Code extension (formerly Claude Dev)
- **Windsurf** - AI-native IDE
- **Continue** - Open-source VS Code extension
- **Other MCP clients** - Generic configuration guide

### Quick Start (Claude Desktop)

For Claude Desktop, add to your config file (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

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

Replace `/absolute/path/to/clang_index_mcp` with your actual installation path, then restart Claude Desktop.

**For complete setup instructions for your specific client, see [CLIENT_SETUP.md](CLIENT_SETUP.md)**

## Usage with Claude

Once configured, you can use the C++ analyzer in your conversations with Claude:

1. First, ask Claude to set your project directory using the MCP tool:
   ```
   "Use the cpp-analyzer tool to set the project directory to /path/to/your/cpp/project"
   ```
   
   **Note:** The initial indexing might take a long time for very large projects (several minutes for codebases with thousands of files). The server will cache the results for faster subsequent queries.

2. Then you can ask questions like:
   - "Find all classes containing 'Actor'"
   - "Show me the Component class details"
   - "What's the signature of BeginPlay function?"
   - "Search for physics-related functions"
   - "Show me the inheritance hierarchy for GameObject"
   - "Find all functions that call Update()"
   - "What functions does Render() call?"

## Architecture

- Uses libclang for accurate C++ parsing
- Caches parsed AST for improved performance
- Supports incremental analysis and project-wide search
- Provides detailed symbol information including:
  - Function signatures with parameter types and names
  - Class members, methods, and inheritance
  - Call graph analysis for understanding code flow
  - File locations for easy navigation

## Configuration Options

The server behavior can be configured via `cpp-analyzer-config.json`:

```json
{
  "exclude_directories": [".git", ".svn", "node_modules", "build", "Build"],
  "exclude_patterns": ["*.generated.h", "*.generated.cpp", "*_test.cpp"],
  "dependency_directories": ["vcpkg_installed", "third_party", "external"],
  "include_dependencies": true,
  "max_file_size_mb": 10,
  "compile_commands": {
    "enabled": true,
    "path": "compile_commands.json",
    "cache_enabled": true,
    "fallback_to_hardcoded": true,
    "cache_expiry_seconds": 300
  }
}
```

### General Options

- **exclude_directories**: Directories to skip during project scanning
- **exclude_patterns**: File patterns to exclude from analysis
- **dependency_directories**: Directories containing third-party dependencies
- **include_dependencies**: Whether to analyze files in dependency directories
- **max_file_size_mb**: Maximum file size to analyze (larger files are skipped)

### Compile Commands Integration

The server supports using `compile_commands.json` to provide accurate compilation arguments:

- **compile_commands.enabled**: Enable/disable compile commands support (default: `true`)
- **compile_commands.path**: Path to compile_commands.json file (default: `"compile_commands.json"`)
  - Can be relative to project root or absolute path
  - Examples: `"build/compile_commands.json"`, `"../compile_commands.json"`
- **compile_commands.cache_enabled**: Enable caching of compile commands (default: `true`)
- **compile_commands.fallback_to_hardcoded**: Fall back to default args if compile_commands.json not found (default: `true`)
- **compile_commands.cache_expiry_seconds**: Cache expiry time in seconds (default: `300`)

**Header File Analysis:**
- Project headers included by source files are automatically analyzed
- Headers processed only once even if included by multiple sources (5-10× performance improvement)
- Restart analyzer after modifying `compile_commands.json` for best results

**For detailed information about compile_commands.json integration, see [COMPILE_COMMANDS_INTEGRATION.md](docs/COMPILE_COMMANDS_INTEGRATION.md)**

## Troubleshooting

### Common Issues

1. **"libclang not found" error**
   - Run `server_setup.bat` (Windows) or `./server_setup.sh` (Linux/macOS) to let the project download libclang automatically
   - If automatic download fails, manually download libclang:
     1. Go to: https://github.com/llvm/llvm-project/releases
     2. Download the appropriate file for your system:
        - **Windows**: `clang+llvm-*-x86_64-pc-windows-msvc.tar.xz`
        - **macOS**: `clang+llvm-*-x86_64-apple-darwin.tar.xz`
        - **Linux**: `clang+llvm-*-x86_64-linux-gnu-ubuntu-*.tar.xz`
     3. Extract and copy the libclang library to the appropriate location:
        - **Windows**: Copy `bin\libclang.dll` to `lib\windows\libclang.dll`
        - **macOS**: Copy `lib\libclang.dylib` to `lib\macos\libclang.dylib`
        - **Linux**: Copy `lib\libclang.so.*` to `lib\linux\libclang.so`

2. **Server fails to start**
   - Check that Python 3.9+ is installed: `python --version`
   - Verify all dependencies are installed: `pip install -r requirements.txt`
   - Run the installation test to identify issues:
     ```bash
     source mcp_env/bin/activate  # Linux/macOS
     python scripts/test_installation.py
     ```

3. **Claude doesn't recognize the server**
   - Ensure the paths in `.claude.json` are absolute paths
   - Restart Claude Desktop after modifying the configuration

4. **Claude uses grep/glob instead of the C++ analyzer**
   - Be explicit in prompts: Say "use the cpp-analyzer to..." when asking about C++ code
   - Add instructions to your project's `CLAUDE.md` file telling Claude to prefer the cpp-analyzer for C++ symbol searches
   - The cpp-analyzer is much faster than grep for finding classes, functions, and understanding code structure

5. **Parse warnings vs. fatal errors**
   - **Note**: The analyzer now continues processing files with non-fatal parsing errors (syntax/semantic errors), extracting partial symbols. Only true fatal errors (TranslationUnitLoadError) cause file rejection.
   - If you see warnings like "Continuing despite N error(s)", this is expected behavior - the analyzer extracts what it can from the partial AST.
   - Diagnose why a specific file fails fatally:
     ```bash
     python scripts/diagnose_parse_errors.py /path/to/project /path/to/file.cpp
     ```
   - Check if files are found in compile_commands.json:
     ```bash
     python scripts/test_compile_commands_lookup.py /path/to/project /path/to/file.cpp
     ```
   - Common causes of **fatal** errors:
     - Path mismatch in compile_commands.json (e.g., generated in Docker with different username)
     - Missing source file
     - Severely malformed file that prevents TU creation
   - View all parse errors (including warnings):
     ```bash
     python scripts/view_parse_errors.py /path/to/project
     ```
