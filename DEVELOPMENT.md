# Development Guide

This guide covers everything you need to know to develop and contribute to Clang Index MCP.

## Table of Contents

- [Project Structure](#project-structure)
- [Development Setup](#development-setup)
- [Architecture Overview](#architecture-overview)
- [Common Development Tasks](#common-development-tasks)
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
│   ├── cpp_analyzer_config.py # Configuration loader
│   ├── file_scanner.py        # File discovery
│   ├── search_engine.py       # Search functionality
│   └── symbol_info.py         # Symbol data structures
├── scripts/                    # Utility scripts
│   ├── download_libclang.py   # Downloads libclang binaries
│   ├── test_installation.py   # Installation verification
│   └── test_deletion_fix.py   # Deletion handling test
├── lib/                        # Platform-specific libraries
│   ├── windows/
│   ├── macos/
│   └── linux/
├── .mcp_cache/                 # Cache directory (gitignored)
├── cpp-analyzer-config.json   # Project configuration
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
└──┬──────┬──────┬──────┬──────┬──────┬──────┘
   │      │      │      │      │      │
   ▼      ▼      ▼      ▼      ▼      ▼
┌──────┐ ┌────┐ ┌─────┐ ┌────┐ ┌────┐ ┌──────┐
│File  │ │lib │ │Sym  │ │Call│ │Sear│ │Cache │
│Scan  │ │clang│ │Info │ │Graph│ │ch  │ │Mgr  │
└──────┘ └────┘ └─────┘ └────┘ └────┘ └──────┘
```

### Data Flow

#### Indexing Flow
```
1. set_project_directory() called
2. FileScanner finds all C++ files
3. Files filtered by config (exclude patterns)
4. Parallel parsing with ThreadPoolExecutor
5. libclang parses each file → AST
6. AST traversal extracts symbols
7. SymbolInfo objects created
8. Indexes built (class_index, function_index, etc.)
9. CallGraph tracks function calls
10. Per-file cache saved
11. Global cache saved
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
make help           # Show all available commands
make test           # Run all tests
make test-coverage  # Run tests with coverage report
make lint           # Run linting checks
make format         # Format code with black
make clean          # Clean cache and build artifacts
make setup          # Run setup script
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
├── test_cpp_analyzer.py      # Core analyzer tests
├── test_cache_manager.py     # Cache tests
├── test_call_graph.py        # Call graph tests
├── test_search_engine.py     # Search tests
└── fixtures/                  # Test data
    └── sample_project/
```

### Running Tests

```bash
# All tests
pytest

# Specific test file
pytest tests/test_cpp_analyzer.py

# Specific test
pytest tests/test_cpp_analyzer.py::test_class_search

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

## Getting Help

- Check existing [Issues](https://github.com/andreymedv/clang_index_mcp/issues)
- Review [Discussions](https://github.com/andreymedv/clang_index_mcp/discussions)
- Read the [README](README.md)
- See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines
