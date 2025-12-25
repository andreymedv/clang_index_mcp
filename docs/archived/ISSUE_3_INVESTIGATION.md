# Issue #3: File Descriptor Leak Investigation

**Priority:** HIGH (blocks manual testing on Linux)

## Problem Statement

File descriptor leak occurs during large project indexing (~5700 files):
- Error: `[Errno 24] Too many open files`
- Occurs after ~1500 files processed (estimate)
- **Platform-specific:** Only on Linux, does NOT occur on macOS
- System limit: `ulimit -n` = 1,048,576 (very high - confirms severe leak)

## Critical Observation

**test_mcp_console.py SUCCEEDS on same Linux host with same project**
- Same 5700-file project
- Same host/OS
- No file descriptor errors
- This means: Issue is NOT inherent to the indexing logic itself

## Key Differences to Investigate

### Test Script vs MCP Server Execution:

**test_mcp_console.py (WORKS):**
```python
analyzer = CppAnalyzer(project_path)
indexed_count = analyzer.index_project(force=False, include_dependencies=True)
```

**MCP Server (FAILS):**
```python
analyzer = CppAnalyzer(project_path, config_file=config_file)
background_indexer = BackgroundIndexer(analyzer, state_manager)
await background_indexer.start_indexing(force=False, include_dependencies=True)

# state_manager.py:228
await loop.run_in_executor(None, lambda: self.analyzer.index_project(...))
```

**Possible differences:**
1. **async executor context** (`loop.run_in_executor`)
2. **config_file parameter** provided to MCP server
3. **Parse error handling** (Linux has more parse errors than macOS)
4. **compile_commands.json processing** (user's hypothesis - HIGH PRIORITY)

## File Descriptor Sources (Per Worker Process)

Each worker process creates NEW CppAnalyzer instance per file:

```python
def _process_file_worker(args_tuple):
    analyzer = CppAnalyzer(project_root)  # NEW instance per file!
    # ... process file ...
    # analyzer goes out of scope, relies on GC
```

**Resources per CppAnalyzer instance:**
- SQLite connection (1 FD) - `cache_manager.cache_backend.conn`
- Parse error log file (opened/closed with context manager - OK)
- libclang Index (thread-local storage)
- TranslationUnit objects (stored in `self.translation_units` dict)

**With 8 workers processing 5700 files:**
- Each worker processes ~712 files
- Creates ~712 CppAnalyzer instances sequentially
- Relies on Python GC to clean up

## What We Know DOESN'T Leak

1. **TranslationUnit storage** - Initial hypothesis was wrong because test script also stores TUs
2. **System limits** - 1M file descriptors is huge
3. **The indexing algorithm itself** - test_mcp_console.py proves it works

## Investigation Focus

### HIGH PRIORITY:
1. **Compare compile_commands.json handling** between MCP server and test script
2. **Parse error logging** - does async context affect file handle cleanup?
3. **SQLite connection lifecycle** in async executor context

### Code Locations:

**Parse error logging:**
- `mcp_server/cache_manager.py:420` - `log_parse_error()`
- Opens `parse_errors.jsonl` with context manager (line 454)

**SQLite connection:**
- `mcp_server/sqlite_cache_backend.py:51` - `self.conn`
- `__del__` method exists (line 259-261)
- `_close()` method exists (line 240-248)

**Worker function:**
- `mcp_server/cpp_analyzer.py:59-109` - `_process_file_worker()`

**Async executor:**
- `mcp_server/state_manager.py:228` - `loop.run_in_executor()`

## Next Steps

1. **Trace compile_commands.json differences** between test script and MCP server
2. **Add file descriptor monitoring** to identify exact leak source
3. **Test hypothesis:** Run MCP server WITHOUT async executor to see if issue persists
4. **Check parse error frequency** correlation with FD exhaustion

## Environment Info

- **Platform:** Linux 6.14.0-37-generic
- **Project:** ~5700 C++ files
- **Parse errors:** More on Linux than macOS (exact count TBD)
- **Failure point:** ~1500 files processed
- **System FD limit:** 1,048,576
