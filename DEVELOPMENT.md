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
├── docs/COMPILE_COMMANDS_INTEGRATION.md # compile_commands.json guide
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

### Header Extraction Architecture

When using `compile_commands.json`, the analyzer automatically extracts symbols from project headers included by source files. This section documents the architectural decisions and design patterns for this feature.

For comprehensive details, see `HEADER_EXTRACTION_ARCHITECTURE.md`.

#### Key Architectural Decisions

**Decision 1: Use First-Win Strategy**
- **What**: First source file to include a header extracts its symbols; subsequent sources skip it
- **Why**: Provides 5-10× performance improvement for headers included by multiple sources
- **Trade-off**: Assumes headers produce consistent symbols across different inclusion contexts
- **Alternative Considered**: Re-extract from every source (rejected: too slow)

**Decision 2: Track by Header Path Only**
- **What**: Header identity is based solely on file path, not compile args
- **Why**: Simplifies tracking and maximizes deduplication
- **Trade-off**: If same header has different compile args in different sources, we use first-encountered context
- **Alternative Considered**: Track `(header_path, compile_args_hash)` tuples (rejected: too complex, rare benefit)

**Decision 3: No Cross-Source Validation**
- **What**: Don't verify that same header produces identical symbols when included from different sources
- **Why**: Adds complexity and performance overhead; violates core assumption
- **Trade-off**: Won't detect headers with macro-dependent behavior
- **Future Enhancement**: Could add optional `--validate-headers` mode for debugging

**Decision 4: No Runtime Monitoring of compile_commands.json**
- **What**: Only check for `compile_commands.json` changes on analyzer startup
- **Why**: Changes during runtime are rare; simplifies implementation
- **Trade-off**: Users must restart analyzer after modifying compilation database
- **User Guidance**: Document this requirement clearly

**Decision 5: Reset All Tracking on compile_commands.json Change**
- **What**: When `compile_commands.json` hash changes, clear all header tracking
- **Why**: Compilation flags may affect header parsing results
- **Trade-off**: Forces full re-analysis (acceptable: config changes are infrequent)
- **Alternative Considered**: Selective invalidation (rejected: complex, error-prone)

#### Design Patterns Used

**Thread-Safe Tracker with Lock-Based Coordination**
```python
class HeaderProcessingTracker:
    def __init__(self):
        self._lock = Lock()
        self._processed: Dict[str, str] = {}  # path -> file_hash
        self._in_progress: Set[str] = set()

    def try_claim_header(self, header_path, file_hash):
        with self._lock:
            # Atomic check-and-claim operation
            if header_path in self._processed:
                return self._processed[header_path] != file_hash  # Re-claim if changed
            if header_path in self._in_progress:
                return False  # Another thread processing
            self._in_progress.add(header_path)
            return True
```

**Why**: Prevents race conditions when multiple threads analyze different sources simultaneously.

**Closure-Based Filtering (Callback Pattern)**
```python
def _index_translation_unit(self, tu, source_file):
    headers_to_extract = set()
    skipped_headers = set()

    def should_extract_from_file(file_path):
        if file_path == source_file:
            return True
        if not self._is_project_file(file_path):
            return False
        file_hash = self._calculate_file_hash(file_path)
        return self.header_tracker.try_claim_header(file_path, file_hash)

    self._process_cursor(tu.cursor, should_extract_from_file)
```

**Why**: Encapsulates extraction logic, allows single-pass AST traversal with dynamic filtering.

**USR-Based Symbol Deduplication**
```python
def _add_with_dedup(self, symbol_info):
    usr = symbol_info.usr
    if usr in self.usr_index:
        # Symbol already exists (from another header/source)
        return False  # Skip
    self._add_to_indexes(symbol_info)
    return True
```

**Why**: Safety net ensuring no duplicate symbols even if header tracking has bugs.

**Hash-Based Change Detection**
```python
# File-level hash tracking
file_hash = hashlib.md5(open(header_path, 'rb').read()).hexdigest()
if cached_hash != file_hash:
    invalidate_and_reprocess(header_path)

# Config-level hash tracking
compile_commands_hash = hashlib.md5(open('compile_commands.json', 'rb').read()).hexdigest()
if cached_cc_hash != compile_commands_hash:
    clear_all_header_tracking()
```

**Why**: Efficient change detection without timestamp issues (platform-independent, content-based).

#### Data Flow: Header Extraction

```
1. index_file("main.cpp") called
2. CompileCommandsManager provides compile args for main.cpp
3. libclang parses main.cpp → TranslationUnit (TU)
   └─ TU contains AST for main.cpp + all included headers
4. _index_translation_unit(tu, "main.cpp") called
5. Define should_extract_from_file(file_path) closure:
   ├─ If file_path == "main.cpp" → return True
   ├─ If not _is_project_file(file_path) → return False
   ├─ Calculate file_hash
   └─ Try header_tracker.try_claim_header(file_path, file_hash)
       ├─ If already processed with same hash → return False
       ├─ If file_hash changed → invalidate old, return True
       └─ If not processed → claim, return True
6. Traverse TU.cursor recursively:
   ├─ For each cursor, get cursor.location.file
   ├─ Call should_extract_from_file(file)
   ├─ If True: extract symbol, add to indexes
   └─ If False: skip extraction, continue traversal
7. Mark newly processed headers as complete:
   └─ header_tracker.mark_completed(header_path, file_hash)
8. Save header tracker cache to disk
9. Return {processed: [...], skipped: [...]}
```

#### Cache Structure

**Header Tracker Cache** (`{cache_dir}/header_tracker.json`):
```json
{
  "version": "1.0",
  "compile_commands_hash": "abc123...",
  "processed_headers": {
    "/project/include/Common.h": "def456...",
    "/project/include/Utils.h": "ghi789..."
  },
  "timestamp": 1699900000
}
```

**Per-File Cache Extension** (`{cache_dir}/files/{hash}.json`):
```json
{
  "file_path": "src/main.cpp",
  "file_hash": "...",
  "symbols": [...],
  "headers_extracted": {  // NEW: for diagnostics
    "include/Common.h": "hash1",
    "include/Utils.h": "hash2"
  },
  "headers_skipped": [    // NEW: for diagnostics
    "include/Precompiled.h"
  ]
}
```

#### Future Enhancement Opportunities

**Optional: Cross-Source Validation Mode**
```bash
python -m mcp_server.cpp_analyzer --validate-headers
```
- Extract headers in all inclusion contexts
- Compare USR sets
- Warn if differences detected
- Helps identify problematic headers with macro-dependent behavior

**Optional: Header Dependency Graph Tracking**
```python
class HeaderDependencyTracker:
    def __init__(self):
        self.source_to_headers: Dict[str, Set[str]] = {}
        self.header_to_sources: Dict[str, Set[str]] = {}
```
- Track which sources include which headers
- Enable smarter cache invalidation (invalidate only affected sources)
- Provide dependency visualization

**Optional: Runtime compile_commands.json Monitoring**
```python
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class CompileCommandsWatcher(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith('compile_commands.json'):
            self.analyzer.invalidate_all_caches()
```
- Auto-detect changes during runtime
- Trigger re-indexing without restart

**Optional: Per-Compile-Args Header Tracking**
```python
# Track: (header_path, compile_args_hash) -> symbols
self._processed: Dict[Tuple[str, str], str] = {}
```
- Handle edge case of same header with different compilation contexts
- More accurate but adds significant complexity
- Only beneficial for projects with inconsistent build configurations

#### Implementation Checklist Reference

For step-by-step implementation tasks, see:
- **Architecture**: `HEADER_EXTRACTION_ARCHITECTURE.md`
- **Implementation Plan**: `HEADER_EXTRACTION_IMPLEMENTATION_PLAN.md`
- **Requirements**: `docs/REQUIREMENTS.md` Section 10

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
- **Compile Commands Integration**: See [COMPILE_COMMANDS_INTEGRATION.md](docs/COMPILE_COMMANDS_INTEGRATION.md)

## Getting Help

- Check existing [Issues](https://github.com/andreymedv/clang_index_mcp/issues)
- Review [Discussions](https://github.com/andreymedv/clang_index_mcp/discussions)
- Read the [README](README.md)
- See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines
- For client/IDE setup: [CLIENT_SETUP.md](CLIENT_SETUP.md)
- For compile_commands.json setup: [COMPILE_COMMANDS_INTEGRATION.md](docs/COMPILE_COMMANDS_INTEGRATION.md)
