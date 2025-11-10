# Development Guide

This guide covers everything you need to know to develop and contribute to Clang Index MCP.

## Table of Contents

- [Project Structure](#project-structure)
- [Development Setup](#development-setup)
- [Architecture Overview](#architecture-overview)
- [Common Development Tasks](#common-development-tasks)
  - [Using the Makefile](#using-the-makefile)
  - [Building and Distributing the Package](#building-and-distributing-the-package)
- [Testing](#testing)
- [Debugging](#debugging)
- [Performance Optimization](#performance-optimization)
- [Troubleshooting](#troubleshooting)

## Project Structure

```
clang_index_mcp/
├── mcp_server/                 # Main server package
│   ├── __init__.py
│   ├── cpp_mcp_server.py      # MCP server entry point (13 tools)
│   ├── cpp_analyzer.py        # Core C++ analysis engine
│   ├── cache_manager.py       # Caching system
│   ├── call_graph.py          # Call graph analysis
│   ├── compile_commands_manager.py # compile_commands.json support
│   ├── cpp_analyzer_config.py # Configuration loader
│   ├── file_scanner.py        # File discovery
│   ├── search_engine.py       # Search functionality
│   └── symbol_info.py         # Symbol data structures
├── scripts/                    # Utility scripts
│   ├── download_libclang.py   # Downloads libclang binaries
│   ├── test_installation.py   # Installation verification
│   └── test_deletion_fix.py   # Deletion handling test
├── tests/                      # Test suite
│   ├── __init__.py
│   ├── test_analyzer_integration.py    # Analyzer integration tests
│   ├── test_compile_commands_manager.py # Compile commands tests
│   └── test_runner.py         # Test runner script
├── examples/                   # Example projects
│   └── compile_commands_example/       # CMake project example
├── lib/                        # Platform-specific libraries
│   ├── windows/
│   ├── macos/
│   └── linux/
├── .mcp_cache/                 # Cache directory (gitignored)
├── cpp-analyzer-config.json   # Project configuration
├── CLIENT_SETUP.md            # Client/IDE configuration guide
├── COMPILE_COMMANDS_INTEGRATION.md # compile_commands.json guide
├── requirements.txt           # Python dependencies
├── server_setup.sh            # Linux/macOS setup
├── server_setup.bat           # Windows setup
└── README.md                  # Project documentation
```

## Development Setup

### Prerequisites

- **Python**: 3.9 or higher
- **Git**: Latest version
- **Platform-specific requirements**:
  - **Windows**: Visual Studio Build Tools or MSVC
  - **macOS**: Xcode Command Line Tools
  - **Linux**: build-essential package

### Initial Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/andreymedv/clang_index_mcp.git
   cd clang_index_mcp
   ```

2. **Run setup script**:
   ```bash
   # Linux/macOS
   ./server_setup.sh

   # Windows
   server_setup.bat
   ```

   This will:
   - Create a virtual environment (`mcp_env/`)
   - Install Python dependencies
   - Download libclang binaries
   - Set up platform-specific libraries

3. **Activate virtual environment**:
   ```bash
   # Linux/macOS
   source mcp_env/bin/activate

   # Windows
   mcp_env\Scripts\activate
   ```

4. **Verify installation**:
   ```bash
   python scripts/test_installation.py
   ```

### Development Dependencies

For development, you may want additional tools:

```bash
pip install pytest pytest-cov pytest-asyncio black flake8 mypy pre-commit
```

## Architecture Overview

### Component Diagram

```
┌─────────────────────────────────────────────┐
│         MCP Client (Claude)                 │
└────────────────┬────────────────────────────┘
                 │ MCP Protocol (stdio)
┌────────────────▼────────────────────────────┐
│         cpp_mcp_server.py                   │
│  • 13 MCP Tool definitions                  │
│  • Request handling and validation          │
└────────────────┬────────────────────────────┘
                 │
┌────────────────▼────────────────────────────┐
│         CppAnalyzer                         │
│  • Project indexing                         │
│  • Symbol extraction                        │
│  • Query handling                           │
│  • compile_commands.json support            │
└──┬──────┬──────┬──────┬──────┬──────┬──────┬──────┘
   │      │      │      │      │      │      │
   ▼      ▼      ▼      ▼      ▼      ▼      ▼
┌──────┐ ┌────┐ ┌─────┐ ┌────┐ ┌────┐ ┌──────┐ ┌────────┐
│File  │ │lib │ │Sym  │ │Call│ │Sear│ │Cache │ │Compile │
│Scan  │ │clang│ │Info │ │Graph│ │ch  │ │Mgr  │ │Commands│
└──────┘ └────┘ └─────┘ └────┘ └────┘ └──────┘ └────────┘
```

### Data Flow

#### Indexing Flow
```
1. set_project_directory() called
2. CompileCommandsManager loads compile_commands.json (if available)
3. FileScanner finds all C++ files
4. Files filtered by config (exclude patterns)
5. Parallel parsing with ThreadPoolExecutor
6. CompileCommandsManager provides compilation args per file
7. libclang parses each file → AST (with project-specific build args)
8. AST traversal extracts symbols
9. SymbolInfo objects created
10. Indexes built (class_index, function_index, etc.)
11. CallGraph tracks function calls
12. Per-file cache saved
13. Global cache saved
```

#### Query Flow
```
1. MCP tool called (e.g., search_classes)
2. Analyzer checks if indexing needed
3. SearchEngine queries pre-built indexes
4. Regex matching on symbol names
5. Results filtered (project_only flag)
6. Results formatted as JSON
7. Returned via MCP TextContent
```

### Key Design Patterns

- **Lazy Initialization**: Indexing deferred until first query
- **Index Pattern**: Pre-built O(1) lookup dictionaries
- **Factory Pattern**: Thread-local Index creation
- **Observer Pattern**: Cache invalidation on file changes
- **Strategy Pattern**: Platform-specific library loading

## Common Development Tasks

### Running the Server

**Standalone (for testing)**:
```bash
python -m mcp_server.cpp_mcp_server
```

**With MCP Client**:
```json
// In MCP client config
{
  "mcpServers": {
    "clang-index": {
      "command": "python",
      "args": ["-m", "mcp_server.cpp_mcp_server"],
      "cwd": "/path/to/clang_index_mcp"
    }
  }
}
```

### Using the Makefile

Common commands:
```bash
make help            # Show all available commands
make test            # Run all tests
make test-coverage   # Run tests with coverage report
make lint            # Run linting checks
make format          # Format code with black
make clean           # Clean cache and build artifacts
make setup           # Run setup script
make build           # Build wheel and source distributions
make build-wheel     # Build wheel distribution only
make install-wheel   # Build and install wheel locally
make install-editable # Install package in editable mode
```

### Building and Distributing the Package

The project supports building wheel packages for distribution.

#### Building a Wheel Package

```bash
# Build both wheel and source distributions
make build

# Or build wheel only
make build-wheel

# Or build source distribution only
make build-sdist
```

The built packages will be available in the `dist/` directory:
- **Wheel package**: `dist/clang_index_mcp-0.1.0-py3-none-any.whl`
- **Source distribution**: `dist/clang_index_mcp-0.1.0.tar.gz`

#### Installing from Wheel

```bash
# Install locally built wheel
make install-wheel

# Or manually with pip
pip install dist/clang_index_mcp-0.1.0-py3-none-any.whl
```

#### Installing in Editable Mode (Recommended for Development)

For development, install the package in editable mode so changes are immediately reflected:

```bash
# Install in editable mode
make install-editable

# Or manually with pip
pip install -e .
```

Editable mode creates a link to your source code instead of copying files. This means:
- Changes to the code are immediately available without reinstalling
- The `clang-index-mcp` command always runs the latest code
- Ideal for active development and testing

#### Installing the Package Entry Point

The wheel package includes an entry point script `clang-index-mcp` that can be used to run the server:

```bash
# After installing the wheel
clang-index-mcp
```

This is equivalent to:
```bash
python -m mcp_server.cpp_mcp_server
```

#### Package Configuration

The package configuration is managed in `pyproject.toml`:

- **Package metadata**: name, version, description, authors
- **Dependencies**: MCP and libclang libraries
- **Build system**: setuptools with wheel support
- **Entry points**: Command-line scripts
- **Development dependencies**: Testing and linting tools

Additional files included in the distribution are specified in `MANIFEST.in`:
- Documentation files (README.md, LICENSE, etc.)
- Configuration examples (cpp-analyzer-config.json)
- Setup scripts (server_setup.sh, server_setup.bat)
- Example projects

#### Publishing to PyPI

To publish the package to PyPI (requires PyPI account and credentials):

```bash
# Install twine for uploading
pip install twine

# Build the distributions
make build

# Check the distributions
twine check dist/*

# Upload to Test PyPI first (recommended)
twine upload --repository testpypi dist/*

# Upload to PyPI
twine upload dist/*
```

#### Version Management

To update the package version:

1. Update the version in `pyproject.toml`:
   ```toml
   [project]
   name = "clang-index-mcp"
   version = "0.2.0"  # Update this
   ```

2. Clean old builds:
   ```bash
   make clean
   ```

3. Build new package:
   ```bash
   make build
   ```

### Adding a New MCP Tool

1. **Define tool schema** in `cpp_mcp_server.py`:
   ```python
   @server.list_tools()
   async def list_tools() -> list[Tool]:
       return [
           # ... existing tools ...
           Tool(
               name="your_new_tool",
               description="Description of what it does",
               inputSchema={
                   "type": "object",
                   "properties": {
                       "param_name": {
                           "type": "string",
                           "description": "Parameter description"
                       }
                   },
                   "required": ["param_name"]
               }
           )
       ]
   ```

2. **Add handler** in `cpp_mcp_server.py`:
   ```python
   @server.call_tool()
   async def call_tool(name: str, arguments: Any) -> list[TextContent]:
       if name == "your_new_tool":
           param = arguments.get("param_name")
           # Validation
           if not param:
               return [TextContent(type="text", text="Error: ...")]

           # Call analyzer method
           result = analyzer.your_method(param)

           # Format and return
           return [TextContent(
               type="text",
               text=json.dumps(result, indent=2)
           )]
   ```

3. **Implement method** in `cpp_analyzer.py`:
   ```python
   def your_method(self, param: str) -> Dict:
       """Your method implementation."""
       self._ensure_indexed()
       # Implementation here
       return result
   ```

4. **Add tests** in `tests/test_your_feature.py`

### Adding Configuration Options

1. **Update default config** in `cpp_analyzer_config.py`:
   ```python
   "new_option": "default_value"
   ```

2. **Use in code**:
   ```python
   config = CppAnalyzerConfig.load()
   value = config.config.get("new_option")
   ```

3. **Document** in `cpp-analyzer-config.json` and README

## Testing

### Test Structure

```
tests/
├── __init__.py
├── test_analyzer_integration.py        # Analyzer integration tests
├── test_compile_commands_manager.py    # Compile commands tests
├── test_runner.py                      # Test runner script
└── fixtures/                           # Test data
    └── sample_project/
```

### Running Tests

```bash
# All tests
pytest

# Run with test runner (compile_commands integration tests)
python tests/test_runner.py

# Specific test file
pytest tests/test_compile_commands_manager.py

# Specific test
pytest tests/test_analyzer_integration.py::test_specific

# With coverage
pytest --cov=mcp_server --cov-report=html

# Verbose output
pytest -v

# Show print statements
pytest -s
```

### Writing Tests

```python
import pytest
from mcp_server.cpp_analyzer import CppAnalyzer

@pytest.fixture
def sample_project(tmp_path):
    """Create a sample C++ project for testing."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    (project_dir / "main.cpp").write_text("""
    class TestClass {
    public:
        void testMethod();
    };
    """)

    return str(project_dir)

def test_class_search(sample_project):
    """Test that class search finds classes correctly."""
    analyzer = CppAnalyzer(sample_project)
    analyzer.index_project()

    results = analyzer.search_classes("Test.*")

    assert len(results) == 1
    assert results[0]["name"] == "TestClass"
```

## Debugging

### Debug Logging

Add logging to your code:
```python
import logging

logger = logging.getLogger(__name__)
logger.debug(f"Processing file: {file_path}")
logger.info(f"Indexed {len(results)} symbols")
logger.warning(f"Failed to parse: {file_path}")
logger.error(f"Error: {str(e)}")
```

Enable debug logging:
```bash
export PYTHONUNBUFFERED=1
export MCP_DEBUG=1
python -m mcp_server.cpp_mcp_server
```

### libclang Debugging

To see libclang diagnostics:
```python
tu = index.parse(file_path, args=args)
for diag in tu.diagnostics:
    print(f"[{diag.severity}] {diag.spelling}")
```

### Cache Debugging

Disable cache to test fresh indexing:
```python
# In cpp_analyzer.py
self.use_cache = False  # Temporarily disable
```

Or delete cache manually:
```bash
rm -rf .mcp_cache/
```

## Performance Optimization

### Profiling

```bash
# Profile script
python -m cProfile -o profile.stats -m mcp_server.cpp_mcp_server

# Analyze results
python -m pstats profile.stats
```

### Optimization Tips

1. **Parallel processing**: Already implemented for indexing
2. **Caching**: Use CacheManager effectively
3. **Index sizes**: Monitor memory usage with large projects
4. **File filtering**: Exclude unnecessary files in config
5. **Lazy loading**: Don't index until needed

## Troubleshooting

### libclang Not Found

**Issue**: `libclang.so not found` or similar

**Solutions**:
- Run `python scripts/download_libclang.py` again
- Check `lib/` directory for platform-specific binaries
- On Linux, ensure `libtinfo` is available
- Set `LIBCLANG_PATH` environment variable

### Parse Errors

**Issue**: Files not parsing correctly

**Solutions**:
- Check C++ standard setting (default: C++17)
- Add missing include paths to parse args
- Check for platform-specific macros needed
- Review libclang diagnostics

### Cache Issues

**Issue**: Stale or corrupted cache

**Solutions**:
```bash
# Clear all cache
rm -rf .mcp_cache/

# Or just for specific project
rm -rf .mcp_cache/your_project_*
```

### Memory Issues

**Issue**: High memory usage with large projects

**Solutions**:
- Increase `max_file_size_mb` filter
- Exclude large dependency directories
- Reduce parallel thread count
- Process files in batches

### Windows Path Issues

**Issue**: Path separators causing problems

**Solutions**:
- Use `Path` from `pathlib`
- Normalize paths with `os.path.normpath()`
- Use raw strings for Windows paths: `r"C:\path"`

## Additional Resources

- **MCP Documentation**: https://modelcontextprotocol.io
- **libclang Documentation**: https://libclang.readthedocs.io
- **Python AST**: https://clang.llvm.org/doxygen/group__CINDEX.html
- **Client/IDE Configuration**: See [CLIENT_SETUP.md](CLIENT_SETUP.md)
- **Compile Commands Integration**: See [COMPILE_COMMANDS_INTEGRATION.md](COMPILE_COMMANDS_INTEGRATION.md)

## Getting Help

- Check existing [Issues](https://github.com/andreymedv/clang_index_mcp/issues)
- Review [Discussions](https://github.com/andreymedv/clang_index_mcp/discussions)
- Read the [README](README.md)
- See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines
- For client/IDE setup: [CLIENT_SETUP.md](CLIENT_SETUP.md)
- For compile_commands.json setup: [COMPILE_COMMANDS_INTEGRATION.md](COMPILE_COMMANDS_INTEGRATION.md)
