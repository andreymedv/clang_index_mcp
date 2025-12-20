# CLAUDE.md

> **Purpose:** Development guide for AI assistants working on this codebase. For user-facing documentation, see [README.md](README.md).

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Model Context Protocol (MCP) server that provides semantic C++ code analysis using libclang. It allows AI assistants like Claude to understand C++ codebases through symbol indexing, class hierarchies, call graphs, and compile_commands.json integration.

**Key Features:**
- 16 MCP tools for C++ code analysis (search_classes, search_functions, get_class_info, call graph analysis, etc.)
- **Documentation extraction (Phase 2):** Extract brief and full documentation comments from C++ code
  - Supports Doxygen (///, /** */), JavaDoc, and Qt-style (/*!) comments
  - Returns documentation in MCP tool responses for LLM consumption
- Incremental analysis with intelligent change detection (30-300x faster re-indexing)
- SQLite-backed symbol cache with FTS5 full-text search
- Multi-process parallel parsing with GIL bypass for 6-7x speedup
- compile_commands.json support for accurate build configuration
- Header deduplication (first-win strategy) for 5-10x performance improvement

**Development Status:** Active development, not production-ready. Primary focus: Linux/macOS.

## Build and Development Commands

### Setup
```bash
# Initial setup (creates venv, installs deps, downloads libclang)
./server_setup.sh              # Linux/macOS
server_setup.bat                # Windows

# Activate virtual environment
source mcp_env/bin/activate     # Linux/macOS
mcp_env\Scripts\activate        # Windows

# Install dev dependencies
make install-dev

# Verify installation
python scripts/test_installation.py
```

### Testing
```bash
make test                       # Run all tests with pytest
make test-coverage              # Run tests with coverage report (htmlcov/)
make test-compile-commands      # Run compile_commands integration tests (tests/test_runner.py)
make test-installation          # Test installation and basic functionality

# Run specific tests
pytest tests/test_analyzer_integration.py
pytest tests/test_compile_commands_manager.py::test_specific
pytest -v -s                    # Verbose with print statements
```

### Code Quality
```bash
make lint                       # Run flake8 (max-line-length=100)
make format                     # Format code with black (line-length=100)
make format-check               # Check formatting without changes
make type-check                 # Run mypy type checking
make check                      # Run all checks (format, lint, type)
```

### Running the Server
```bash
make run                        # Run MCP server (stdio transport)
make dev                        # Run with MCP_DEBUG=1 and PYTHONUNBUFFERED=1

# Alternative transport protocols
python -m mcp_server.cpp_mcp_server                                        # stdio (default)
python -m mcp_server.cpp_mcp_server --transport http --port 8000           # HTTP
python -m mcp_server.cpp_mcp_server --transport sse --port 8000            # SSE
```

### Building and Distribution
```bash
make build                      # Build both wheel and source distributions
make build-wheel                # Build wheel only (dist/clang_index_mcp-*.whl)
make install-wheel              # Build and install wheel locally
make install-editable           # Install in editable mode (recommended for dev)

# After install-editable or install-wheel, you can run:
clang-index-mcp                 # Entry point script (equivalent to python -m mcp_server.cpp_mcp_server)
```

### Maintenance
```bash
make clean                      # Clean cache and build artifacts
make clean-cache                # Clean only .mcp_cache/
make clean-all                  # Clean everything including mcp_env/
make download-libclang          # Download libclang binary for platform
```

### Shortcuts
```bash
make t                          # test
make tc                         # test-coverage
make l                          # lint
make f                          # format
make c                          # clean
make r                          # run
make b                          # build
make ie                         # install-editable
```

## Architecture

### High-Level Component Structure

```
┌────────────────────────────────────────────────┐
│         MCP Client (Claude Desktop, etc.)      │
└───────────────────┬────────────────────────────┘
                    │ MCP Protocol (stdio/http/sse)
┌───────────────────▼────────────────────────────┐
│       cpp_mcp_server.py (16 MCP Tools)         │
│  Entry point, tool definitions, validation     │
└───────────────────┬────────────────────────────┘
                    │
┌───────────────────▼────────────────────────────┐
│            CppAnalyzer (core engine)           │
│  • Project indexing & incremental analysis     │
│  • Symbol extraction & query handling          │
│  • Multi-process parallel parsing              │
│  • compile_commands.json integration           │
└─┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬───┘
  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │
  │  │  │  │  │  │  │  │  │  │  │  │  │  │  └─ ErrorTracking
  │  │  │  │  │  │  │  │  │  │  │  │  │  └──── ProjectIdentity
  │  │  │  │  │  │  │  │  │  │  │  │  └───────── RegexValidator
  │  │  │  │  │  │  │  │  │  │  │  └──────────── ArgumentSanitizer
  │  │  │  │  │  │  │  │  │  │  └─────────────── StateManager
  │  │  │  │  │  │  │  │  │  └────────────────── IncrementalAnalyzer
  │  │  │  │  │  │  │  │  └───────────────────── ChangeScanner
  │  │  │  │  │  │  │  └──────────────────────── CompileCommandsDiffer
  │  │  │  │  │  │  └─────────────────────────── DependencyGraph
  │  │  │  │  │  └────────────────────────────── HeaderTracker
  │  │  │  │  └───────────────────────────────── CompileCommandsManager
  │  │  │  └──────────────────────────────────── SearchEngine
  │  │  └─────────────────────────────────────── CallGraphAnalyzer
  │  └────────────────────────────────────────── CacheManager
  │                                              └─ SQLiteCacheBackend (FTS5)
  └───────────────────────────────────────────── FileScanner
```

### Key Architectural Decisions

**1. Multi-Process Parallelism (ProcessPoolExecutor)**
- Bypasses Python's GIL for true parallelism on multi-core systems
- Each worker process gets isolated memory space (no shared state)
- 6-7x speedup on 4+ core systems
- Worker function: `_process_file_worker()` (module-level for pickling)
- Disable with `CPP_ANALYZER_USE_THREADS=true` (falls back to ThreadPoolExecutor)

**2. Header Deduplication (First-Win Strategy)**
- When using compile_commands.json, headers included by multiple sources are processed once
- First source file to include a header "claims" it via `HeaderProcessingTracker`
- 5-10x performance improvement for commonly-included headers
- Identity tracked by header path only (not compile args)
- See mcp_server/header_tracker.py

**3. Incremental Analysis Architecture**
- Tracks file changes via MD5 hashing (content-based, platform-independent)
- Builds dependency graphs to cascade header changes to dependent sources
- Detects compile_commands.json changes and re-analyzes affected files
- Provides 30-300x speedup for partial refreshes
- See mcp_server/incremental_analyzer.py, mcp_server/change_scanner.py

**4. SQLite Cache with FTS5**
- Symbol storage in SQLite with full-text search (2-5ms for 100K symbols)
- WAL mode for concurrent multi-process access
- Automatic VACUUM, OPTIMIZE, and ANALYZE maintenance
- Cache per project configuration: (source_dir, config_file) → unique cache dir
- See mcp_server/sqlite_cache_backend.py, mcp_server/schema.sql

**5. Compile Commands Integration**
- Parses compile_commands.json for accurate per-file compilation arguments
- Binary caching (.mcp_cache/<project>/compile_commands/<hash>.cache) for 10-100x faster startup
- Optional orjson for 3-5x faster JSON parsing (pip install .[performance])
- Fallback to hardcoded args if compile_commands.json not found
- See mcp_server/compile_commands_manager.py

**6. No Runtime Monitoring of compile_commands.json**
- Only checked on analyzer startup (not during runtime)
- Users must restart analyzer after modifying compilation database
- Trade-off: simplicity vs convenience (config changes are rare)

**7. Header Tracking Cache Optimization**
- Header tracking state saved once at end of indexing (not per-file)
- Eliminates race conditions in multi-process mode (was causing ~5000 writes for large projects)
- Cached as header_tracker.json in project cache directory
- Includes compile_commands.json hash for invalidation on config changes
- See mcp_server/header_tracker.py, cpp_analyzer.py:_save_header_tracking()

**8. libclang Error Recovery**
- Leverages libclang's built-in error recovery for non-fatal parse errors
- Files with syntax/semantic errors continue processing, extract partial symbols from usable AST
- Only TranslationUnitLoadError (no TU created) causes true failure
- Errors logged as warnings, cached with error_message for diagnostics
- Provides 90%+ symbol extraction vs 0% for files with minor issues
- See cpp_analyzer.py:index_file() error handling

**9. AST Traversal Optimization (System Header Skipping)**
- Early exit from AST traversal when encountering non-project file cursors
- Skips traversing entire AST subtrees of system headers and external dependencies
- Provides 5-7x speedup on large projects (3.5 hours → ~30-60 minutes for 5700 files)
- Safe because: symbol extraction already filtered, dependency discovery uses tu.get_includes() API
- Only traverses AST nodes from project files and files with active call tracking
- See cpp_analyzer.py:_process_cursor() early exit optimization (line ~946-954)

### Data Flow

**Indexing Flow:**
1. `set_project_directory()` called via MCP tool
2. CompileCommandsManager loads compile_commands.json (if enabled)
3. FileScanner discovers all C++ files in project
4. Files filtered by config (exclude_directories, exclude_patterns)
5. Parallel parsing with ProcessPoolExecutor (or ThreadPoolExecutor)
6. For each file:
   - CompileCommandsManager provides compilation args
   - libclang parses file → TranslationUnit (AST)
   - Error diagnostics extracted; non-fatal errors logged but processing continues
   - AST traversal extracts symbols (classes, functions, methods) from partial AST
   - HeaderTracker deduplicates header processing
   - Symbols stored in SQLite cache (with error_message if errors present)
7. Indexes built: class_index, function_index, file_index, usr_index
8. CallGraphAnalyzer tracks function calls
9. Cache metadata and header tracking state saved (once at end)

**Query Flow:**
1. MCP tool called (e.g., search_classes, find_callers)
2. CppAnalyzer checks indexing state
3. SearchEngine queries SQLite FTS5 indexes
4. Regex matching on symbol names (if pattern provided)
5. Results filtered (project_only flag, file filters)
6. JSON results returned via MCP TextContent

**Incremental Refresh Flow:**
1. `refresh_project()` called
2. ChangeScanner detects file changes (MD5 hashing)
3. CompileCommandsDiffer detects compile_commands.json changes
4. DependencyGraph identifies affected files (transitive header deps)
5. Only affected files re-parsed
6. Cache updated incrementally

### Critical Code Locations

- **MCP Tools Definition:** mcp_server/cpp_mcp_server.py:176-461 (`list_tools()`)
- **Core Analyzer:** mcp_server/cpp_analyzer.py (CppAnalyzer class)
- **Symbol Extraction:** mcp_server/cpp_analyzer.py:_process_cursor() (recursive AST traversal)
- **Documentation Extraction (Phase 2):** mcp_server/cpp_analyzer.py:_extract_documentation() (brief and doc_comment extraction)
- **Parallel Worker:** mcp_server/cpp_analyzer.py:72-131 (`_process_file_worker()` with singleton-per-process pattern and atexit cleanup)
- **SQLite FTS5:** mcp_server/sqlite_cache_backend.py, mcp_server/schema.sql (v8.0 with brief/doc_comment fields and call_sites table)
- **Header Tracking:** mcp_server/header_tracker.py (HeaderProcessingTracker)
- **Incremental Logic:** mcp_server/incremental_analyzer.py
- **Compile Commands:** mcp_server/compile_commands_manager.py

## Configuration

**Project config:** `cpp-analyzer-config.json` (project root or specified path)
- `exclude_directories`: Dirs to skip (e.g., [".git", "build", "node_modules"])
- `exclude_patterns`: File patterns to exclude (e.g., ["*.generated.h", "*_test.cpp"])
- `dependency_directories`: Third-party deps (e.g., ["vcpkg_installed", "third_party"])
- `include_dependencies`: Analyze files in dependency dirs (default: true)
- `max_file_size_mb`: Skip files larger than this (default: 10)
- `compile_commands.enabled`: Use compile_commands.json (default: true)
- `compile_commands.path`: Path to compile_commands.json (default: "compile_commands.json")
- `compile_commands.cache_enabled`: Cache parsed compile commands (default: true)

**Environment variables:**
- `CPP_ANALYZER_USE_THREADS=true`: Disable ProcessPoolExecutor, use ThreadPoolExecutor
- `MCP_DEBUG=1`: Enable debug logging
- `PYTHONUNBUFFERED=1`: Unbuffered Python output
- `LIBCLANG_PATH=/path/to/libclang.so`: Override libclang path

## Performance Diagnostics

```bash
# Profile analysis performance (identify bottlenecks)
python scripts/profile_analysis.py /path/to/project

# Check if GIL is limiting parallelism
python scripts/diagnose_gil.py /path/to/project

# View cache statistics
python scripts/cache_stats.py

# Diagnose cache health
python scripts/diagnose_cache.py
```

## Parse Error Diagnostics

```bash
# Diagnose why a specific file fails to parse
python scripts/diagnose_parse_errors.py /path/to/project /path/to/file.cpp

# Test if a file is found in compile_commands.json
python scripts/test_compile_commands_lookup.py /path/to/project /path/to/file.cpp

# View centralized parse error log
python scripts/view_parse_errors.py /path/to/project
```

The `diagnose_parse_errors.py` script tests parsing with different libclang options and shows:
- Compilation arguments being used
- Which parse options work
- Specific error messages from libclang
- Recommendations for fixing issues

## Common Workflows

### Adding a New MCP Tool
1. Define tool schema in `cpp_mcp_server.py` `list_tools()` function
2. Add handler in `cpp_mcp_server.py` `call_tool()` function
3. Implement analyzer method in `cpp_analyzer.py`
4. Add tests in `tests/test_*.py`
5. Update this CLAUDE.md if architecturally significant

### Modifying Symbol Extraction Logic
1. Edit `cpp_analyzer.py` `_process_cursor()` (recursive AST walker)
2. Update `symbol_info.py` if changing SymbolInfo structure
3. If changing SQLite schema:
   - Update `mcp_server/schema.sql` with new columns/tables
   - Increment schema version in schema.sql (e.g., "4.0" → "5.0")
   - Update `CURRENT_SCHEMA_VERSION` in `sqlite_cache_backend.py`
   - Database will automatically recreate on version mismatch (development mode)
4. Run `make test` to verify no regressions
5. Test with example project: `python -m mcp_server.cpp_mcp_server` + set examples/compile_commands_example/

### Cache Invalidation and Corruption Recovery

```bash
# Check for corrupted databases
python scripts/fix_corrupted_cache.py

# Check and fix specific project cache
python scripts/fix_corrupted_cache.py /path/to/project

# Manually clear all cache
rm -rf .mcp_cache/

# Manually clear specific project cache
rm -rf .mcp_cache/<project_hash>_*
```

**Database Corruption:**
If you see "database disk image is malformed" errors, the SQLite cache is corrupted. This can happen if indexing was interrupted improperly (e.g., SIGKILL, power loss). Use the `fix_corrupted_cache.py` script to diagnose and repair.

### Interrupt Handling (Ctrl-C)

**Proper usage:**
- Press Ctrl-C **ONCE** during indexing for clean shutdown
- Wait 1-2 seconds for executor to cancel pending work
- Pressing Ctrl-C multiple times causes forceful termination with stack traces (expected)

**Verification:**
```bash
# Test interrupt handling
python scripts/test_interrupt_cleanup.py /path/to/project
# Press Ctrl-C during indexing, then check: ps aux | grep python

# Should see NO orphaned worker processes
```

**For detailed information:**
See [docs/INTERRUPT_HANDLING.md](docs/INTERRUPT_HANDLING.md) for complete guide on:
- Expected behavior on interrupt
- Common issues and solutions
- Implementation details
- Debugging tips

## Testing Strategy

**Integration tests:** `tests/test_analyzer_integration.py`
- End-to-end analyzer functionality
- Real libclang parsing with sample C++ code
- Fixture-based with `tmp_path` for isolated testing

**Compile commands tests:** `tests/test_compile_commands_manager.py`
- Unit tests for compile_commands.json parsing
- Cache invalidation logic
- Test runner: `tests/test_runner.py` (also runnable as script)

**Test fixtures:** `tests/fixtures/sample_project/`
- Example C++ code for testing

**Coverage:** `make test-coverage` generates htmlcov/ report

## File Organization

```
mcp_server/
├── cpp_mcp_server.py           # MCP server entry point (16 tools, stdio/http/sse)
├── cpp_analyzer.py             # Core analyzer (indexing, querying, parallel parsing)
├── cache_manager.py            # Cache coordination layer
├── sqlite_cache_backend.py     # SQLite FTS5 backend implementation
├── schema.sql                  # SQLite schema with FTS5 indexes (version 8.0)
├── schema_migrations.py        # Schema migrations (deprecated, for legacy support only)
├── compile_commands_manager.py # compile_commands.json parsing & caching
├── incremental_analyzer.py     # Incremental analysis orchestration
├── change_scanner.py           # File change detection (MD5 hashing)
├── compile_commands_differ.py  # Compilation flag change detection
├── dependency_graph.py         # Header dependency tracking
├── header_tracker.py           # Header deduplication (first-win)
├── call_graph.py               # Function call graph analysis
├── search_engine.py            # Symbol search (regex, filters)
├── file_scanner.py             # File discovery
├── symbol_info.py              # SymbolInfo data structure
├── project_identity.py         # Project identity (source_dir, config) → cache dir
├── state_manager.py            # Indexing state tracking
├── error_tracking.py           # Parse error tracking
├── regex_validator.py          # User regex validation
├── argument_sanitizer.py       # Argument sanitization (security)
├── diagnostics.py              # Logging and diagnostics
├── http_server.py              # HTTP/SSE transport layer
└── migrations/                 # SQL migrations (deprecated, kept for tests only)

scripts/
├── download_libclang.py             # Downloads libclang binaries
├── test_installation.py             # Installation verification
├── test_mcp_console.py              # Manual MCP server testing with real codebase
├── test_interrupt_cleanup.py        # Test subprocess cleanup on Ctrl-C interrupt
├── fix_corrupted_cache.py           # Diagnose and fix corrupted SQLite cache
├── profile_analysis.py              # Performance profiling
├── diagnose_gil.py                  # GIL bottleneck detection
├── cache_stats.py                   # Cache statistics viewer
├── diagnose_cache.py                # Cache health diagnostics
├── diagnose_parse_errors.py         # Parse error diagnostics (libclang options testing)
├── test_compile_commands_lookup.py  # compile_commands.json lookup testing
└── view_parse_errors.py             # View centralized parse error log

examples/
└── compile_commands_example/   # Example CMake project with compile_commands.json
```

## libclang Setup

Libclang is auto-downloaded by setup scripts to `lib/{platform}/lib/`:
- **Windows:** lib/windows/lib/libclang.dll
- **macOS:** lib/macos/lib/libclang.dylib
- **Linux:** lib/linux/lib/libclang.so.1

If auto-download fails, manually download from https://github.com/llvm/llvm-project/releases and place in appropriate `lib/` directory.

## Important Notes for Claude Code

1. **When analyzing C++ code in a project:** Prefer using the cpp-analyzer MCP tools (if server is running) over grep/glob. The analyzer understands C++ semantics (classes, inheritance, call graphs) which grep cannot.

2. **Documentation extraction (Phase 2):** MCP tools (`search_classes`, `search_functions`, `get_class_info`) now return `brief` and `doc_comment` fields extracted from C++ documentation comments. This allows LLMs to understand symbol purpose without reading source files. Supports Doxygen (///, /** */), JavaDoc, and Qt-style (/*!) comments. Documentation is truncated at 4000 characters with "..." suffix if longer.

3. **Incremental analysis is automatic:** When using `refresh_project`, the analyzer intelligently detects changes. Only use `force_full=true` after major config changes or if cache corruption is suspected.

4. **Performance monitoring:** On large projects (1000+ files), use `get_indexing_status` to monitor progress. Use `wait_for_indexing` before queries to ensure complete results.

5. **compile_commands.json:** If present, analyzer will use it for accurate compilation arguments. Restart analyzer after modifying compile_commands.json.

6. **Multi-process mode:** Default mode bypasses GIL for true parallelism. If debugging parse issues, set `CPP_ANALYZER_USE_THREADS=true` to use ThreadPoolExecutor (easier to debug, but slower).

7. **SQLite cache:** Lives in `.mcp_cache/` (multi-config support). Compile commands cache stored in `.mcp_cache/<project>/compile_commands/`. Safe to delete for fresh indexing. WAL mode enables concurrent access. **Schema version 8.0** includes documentation fields (brief, doc_comment) and call_sites table for line-level call graph tracking.

8. **Development mode auto-recreation:** During development, the SQLite database is automatically recreated when the schema version changes. This simplifies development by avoiding migration complexity. When you change `schema.sql`, just increment the version number and update `CURRENT_SCHEMA_VERSION` in `sqlite_cache_backend.py`. On next run, the old database will be deleted and recreated with the new schema.

9. **Parse error recovery:** The analyzer leverages libclang's error recovery to extract symbols from files with non-fatal parsing errors. Files with syntax or semantic errors will log warnings but continue processing, extracting partial symbols from the usable AST. Only true fatal errors (no TranslationUnit created) cause file rejection. This means you get partial results instead of nothing for files with minor issues.

10. **Test before committing:** Always run `make test` and `make check` before creating PRs.
