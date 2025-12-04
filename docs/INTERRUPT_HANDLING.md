# Interrupt Handling (Ctrl-C) in C++ MCP Server

This document explains how the C++ MCP server handles interrupts (Ctrl-C / SIGINT) during indexing, and what to expect when terminating the process.

## Overview

The server uses `ProcessPoolExecutor` for parallel C++ file parsing. When you press Ctrl-C during indexing, the server needs to:
1. Stop accepting new work
2. Cancel pending tasks
3. Wait for running worker processes to finish
4. Close database connections cleanly
5. Exit without leaving orphaned processes

## Expected Behavior

### Single Ctrl-C (Clean Shutdown)

**What you should see:**
```
Progress: 10/8389 files (0%) - Success: 7 - Failed: 3...
^C
[INFO] Indexing interrupted by user (Ctrl-C)

Interrupted by user (Ctrl-C)
Cleaning up...
Analyzer closed successfully
```

**What happens:**
- KeyboardInterrupt is raised in the main process
- Executor shutdown is triggered with `executor.shutdown(wait=True)`
- Pending futures are canceled
- Running workers complete their current file
- Database is closed cleanly
- **No orphaned processes remain**

You may see a few "Exception ignored" messages from libclang if a worker was mid-parsing when interrupted. This is normal and harmless.

### Multiple Ctrl-C (Forceful Termination)

**What you should see:**
Many stack traces from worker processes, showing KeyboardInterrupt at various points in multiprocessing internals.

**Why this happens:**
- First Ctrl-C: Starts clean shutdown
- Second/Third Ctrl-C: SIGINT sent to all processes again
- Worker processes dump stack traces before being killed
- This is **expected behavior** for forceful termination

**Recommendation:**
Press Ctrl-C **ONCE** and wait 1-2 seconds for clean shutdown. Only press multiple times if the process appears hung (very rare).

## Common Issues and Solutions

### Issue: "database disk image is malformed"

**Cause:** Database was corrupted by:
- Previous interrupted session (before fixes)
- SIGKILL (kill -9) instead of SIGINT
- Power loss / system crash
- Disk I/O errors

**Solution:**
```bash
# Check and fix corrupted database
python scripts/fix_corrupted_cache.py /path/to/project

# Or manually delete cache
rm -rf ~/.mcp_cache/
```

### Issue: Orphaned python processes after interrupt

**Check:**
```bash
ps aux | grep python
```

**Expected:** Only your current shell's python process (if any)

**If you see orphaned workers:**
This indicates a bug in interrupt handling. Please report with:
1. Python version: `python --version`
2. OS: `uname -a`
3. Steps to reproduce

### Issue: "Exception ignored in: <function _CXString.__del__>"

**This is normal** when interrupting mid-parse. libclang's Python bindings use ctypes callbacks that can't be cleanly canceled. These exceptions are harmless and don't indicate corruption.

## Implementation Details

### Signal Handling Strategy

**Before (problematic):**
- Custom signal handlers registered with `signal.signal()`
- Signal handlers inherited by worker processes
- Workers tried to close database on SIGINT → corruption

**Current (correct):**
- No custom signal handlers
- Python's built-in KeyboardInterrupt exception handling
- Only main process closes database
- Workers receive SIGINT but don't access database
- `executor.shutdown(wait=True)` ensures clean worker termination

### Code Locations

- **Main interrupt handling:** `mcp_server/cpp_analyzer.py:1449-1464`
  - KeyboardInterrupt exception handler
  - Executor shutdown with `wait=True`

- **Test scripts:**
  - `scripts/test_mcp_console.py` - Manual testing
  - `scripts/test_interrupt_cleanup.py` - Verify no orphaned processes

### Why asyncio.run() was removed

The test scripts originally used `asyncio.run()` which:
- Installs its own signal handler (`_on_sigint`)
- Raises KeyboardInterrupt in ALL processes (main + workers)
- Caused excessive stack traces even on single Ctrl-C

Since the test functions weren't actually async (no `await`), we removed asyncio entirely for cleaner interrupt handling.

## Testing Interrupt Handling

### Manual Test

```bash
# Start indexing a large project
python scripts/test_mcp_console.py /path/to/large/project

# Wait for indexing to start (see progress output)
# Press Ctrl-C ONCE
# Wait 1-2 seconds

# Verify clean shutdown:
# - Should see "Indexing interrupted by user (Ctrl-C)"
# - Should see "Analyzer closed successfully"
# - No database corruption errors

# Verify no orphaned processes:
ps aux | grep python
# Should see only your shell (if any)
```

### Automated Test

```bash
# Verify executor cleanup
python scripts/test_interrupt_cleanup.py /path/to/project
# Press Ctrl-C during indexing
# Check ps output at the end
```

## Best Practices

1. **Single Ctrl-C:** Always try single Ctrl-C first and wait for clean shutdown
2. **Database safety:** SQLite WAL mode allows some concurrent access, but clean shutdown is still important
3. **Large projects:** Clean shutdown may take 1-2 seconds to cancel all pending work
4. **If hung:** If process doesn't respond to Ctrl-C within 5 seconds, use `kill` (not `kill -9`)

## Platform Differences

### Linux
- Clean signal handling with fork-based multiprocessing
- No known issues

### macOS
- Same as Linux (fork-based multiprocessing)
- No known issues

### Windows
- Uses spawn instead of fork for multiprocessing
- Signal handling differs slightly
- Not thoroughly tested yet

## Debugging

### Enable debug logging

```bash
export MCP_DEBUG=1
python scripts/test_mcp_console.py /path/to/project
```

### Check database health

```bash
# Scan all caches
python scripts/fix_corrupted_cache.py

# Check specific project
python scripts/fix_corrupted_cache.py /path/to/project
```

### Profile interrupt timing

```bash
time python scripts/test_mcp_console.py /path/to/project
# Press Ctrl-C immediately after indexing starts
# Time should be < 3 seconds for clean shutdown
```

## Related Files

- `mcp_server/cpp_analyzer.py` - Main interrupt handling
- `scripts/test_mcp_console.py` - Manual test script
- `scripts/test_interrupt_cleanup.py` - Automated test
- `scripts/fix_corrupted_cache.py` - Database recovery tool
- `CLAUDE.md` - Architecture documentation

## Future Improvements

Possible enhancements (not currently implemented):
- Progress bar that updates during shutdown
- Estimate of shutdown time remaining
- Save partial results on interrupt
- Resume from partial indexing

## Questions?

If you encounter issues not covered here:
1. Check the issue tracker
2. Run with `MCP_DEBUG=1` for verbose output
3. Check database health with `fix_corrupted_cache.py`
4. Report bugs with full reproduction steps
