# Agent Diagnostics Guide

Read this file when debugging performance issues, resource leaks, parse errors, or interrupt handling.

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

## Resource Monitoring (File Descriptors & Memory)

Monitor file descriptors and resource usage during indexing to detect leaks:

```bash
# Get the MCP server PID
MCP_PID=$(pgrep -f "python -m clang_index_mcp" | head -1)

# Monitor file descriptor counts (should stay stable at ~10-15)
watch -n 2 'echo "=== FD Monitor ==="; \
  echo "Main: $(ls /proc/'$MCP_PID'/fd 2>/dev/null | wc -l) FDs"; \
  pgrep -P '$MCP_PID' | while read wpid; do \
    echo "Worker $wpid: $(ls /proc/$wpid/fd 2>/dev/null | wc -l) FDs"; \
  done'

# Check open C++ source files (should be 0 or very low)
lsof -p $MCP_PID $(pgrep -P $MCP_PID | tr '\n' ',' | sed 's/,$//' | sed 's/^/,/') 2>/dev/null | \
  grep -E '\.(cpp|h|cc|hpp)$' | wc -l

# View which specific files are open
lsof -p $MCP_PID $(pgrep -P $MCP_PID | tr '\n' ',' | sed 's/,$//' | sed 's/^/,/') 2>/dev/null | \
  grep -E '\.(cpp|h|cc|hpp)$' | awk '{print $NF}' | sort | uniq

# File type summary (should show minimal .h/.cpp files)
lsof -p $MCP_PID $(pgrep -P $MCP_PID | tr '\n' ',' | sed 's/,$//' | sed 's/^/,/') 2>/dev/null | \
  grep REG | awk '{print $NF}' | sed 's/.*\.//' | sort | uniq -c | sort -rn

# Memory usage per process
ps -p $MCP_PID $(pgrep -P $MCP_PID | tr '\n' ',') -o pid,rss,cmd --no-headers | \
  awk '{printf "PID %s: %.1f MB - %s\n", $1, $2/1024, substr($0, index($0,$3))}'
```

**Expected healthy values:**
- Main process: 10-15 FDs
- Worker processes: 8-10 FDs each
- Open C++ files: 0-2 (near zero)
- Total FDs: 30-60 for 8 workers (stable, not growing)

**Signs of file descriptor leak:**
- FDs continuously increasing during indexing
- 100+ .h or .cpp files kept open
- "Too many open files" errors
- FD count approaching system limit (usually 1024 per process)

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

## Interrupt Handling (Ctrl-C)

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

## libclang Setup

Libclang is auto-downloaded by setup scripts to `clang_index_mcp/libclang/`:
- **Windows:** clang_index_mcp/libclang/lib/libclang.dll
- **macOS:** clang_index_mcp/libclang/lib/libclang.dylib
- **Linux:** clang_index_mcp/libclang/lib/libclang.so.1

If auto-download fails, manually download from https://github.com/llvm/llvm-project/releases and place in `clang_index_mcp/libclang/lib/`.
