# [006] Server Shutdown Hangs on Ctrl-C

**Category:** Bug
**Priority:** Medium
**Status:** Proposed
**Date Identified:** 2025-12-26
**Estimated Effort:** 2-3 days
**Complexity:** Medium

---

## Problem Statement

SSE server does not exit cleanly on first Ctrl-C. Requires multiple Ctrl-C presses (observed: 5 times) to force shutdown. Server appears to hang during cleanup phase, specifically when waiting for ProcessPoolExecutor workers and async event loop to terminate.

### Current Behavior

**Observed Sequence:**

1. **First Ctrl-C**: Server acknowledges shutdown but hangs
   ```
   ^CINFO:     Shutting down
   INFO:     Waiting for application shutdown.
   INFO:     Application shutdown complete.
   INFO:     Finished server process [20039]
   [Process hangs here - does not exit]
   ```

2. **Second Ctrl-C**: Interrupts threading shutdown
   ```
   ^CTraceback (most recent call last):
     File "/usr/lib/python3.12/threading.py", line 1592, in _shutdown
       atexit_call()
     File "/usr/lib/python3.12/concurrent/futures/process.py", line 102, in _python_exit
       t.join()
   ```

3. **Third-Fifth Ctrl-C**: Interrupts multiprocessing cleanup
   ```
   ^CException ignored in atexit callback: <function _exit_function at 0x...>
   Traceback (most recent call last):
     File "/usr/lib/python3.12/multiprocessing/util.py", line 360, in _exit_function
       p.join()
     File "/usr/lib/python3.12/multiprocessing/process.py", line 149, in join
   ```

**Test Environment:**
- **Platform**: Linux
- **Transport**: SSE on port 8080
- **State**: Server with project set, indexing may or may not be in progress
- **Python**: 3.12

### Expected/Desired Behavior

1. **First Ctrl-C**:
   - Server receives SIGINT
   - Cancels ongoing indexing operations
   - Terminates worker processes gracefully
   - Cleans up async tasks
   - Exits within 2-3 seconds

2. **Clean shutdown log:**
   ```
   ^CINFO:     Shutting down
   INFO:     Cancelling indexing operations...
   INFO:     Terminating worker processes...
   INFO:     Waiting for workers to exit... (done)
   INFO:     Application shutdown complete.
   INFO:     Finished server process [20039]
   [Process exits]
   ```

---

## Impact Assessment

**User Impact:**
- **Workflow Disruption**: Must press Ctrl-C multiple times
- **Confusion**: Appears frozen, users may force kill (SIGKILL)
- **Testing**: Slows down development iteration cycle

**Development Impact:**
- **Testing**: Annoying during manual testing
- **CI/CD**: May cause timeout issues in automated tests

**Business Impact:**
- **Low**: Cosmetic/UX issue, does not affect functionality
- **Professionalism**: Reflects poorly on quality

---

## Technical Analysis

### Root Causes (Hypotheses)

**1. ProcessPoolExecutor Blocking on Worker Join**

The traceback shows:
```python
File "/usr/lib/python3.12/concurrent/futures/process.py", line 102, in _python_exit
  t.join()  # ← Blocking here
```

**Possible causes:**
- Workers stuck in long-running operations (indexing large files)
- Workers waiting on I/O (SQLite locks, file reads)
- Workers not responding to termination signals

**2. Async Event Loop Not Cancelling Tasks**

After "Application shutdown complete", process doesn't exit. Suggests:
- Background async tasks still running
- Event loop not properly closed
- Pending futures not cancelled

**3. SSE Server Lifecycle Issue**

Uvicorn/FastAPI shutdown may not be properly coordinating with:
- Background indexing task
- ProcessPoolExecutor cleanup
- MCP server cleanup

**4. Atexit Handlers Blocking**

Multiple atexit callbacks trying to join worker processes:
```python
File "/usr/lib/python3.12/multiprocessing/util.py", line 360, in _exit_function
  p.join()  # ← Blocking on worker process exit
```

Workers may not be terminating because:
- Still processing files
- Stuck in libclang parsing
- Waiting on shared resources (locks, queues)

---

## Code Investigation Targets

### Critical Files

1. **mcp_server/cpp_mcp_server.py**:
   - Signal handling (SIGINT, SIGTERM)
   - Lifespan event handlers
   - Background task management

2. **mcp_server/cpp_analyzer.py**:
   - `index_project()` - check for interrupt handling
   - ProcessPoolExecutor shutdown logic
   - Worker cleanup in `_cleanup_worker_analyzer()`

3. **mcp_server/http_server.py** (if using SSE mode):
   - Uvicorn/FastAPI shutdown coordination
   - Background task cancellation

### Questions to Answer

1. Is there proper signal handler for SIGINT?
2. Are background indexing tasks cancellable?
3. Does ProcessPoolExecutor use timeout on shutdown?
4. Are workers checking for termination signals?
5. Does SSE server coordinate with analyzer shutdown?

---

## Proposed Solutions

### Option 1: Add Executor Shutdown Timeout

**Concept**: Don't wait indefinitely for workers to exit

**Implementation**:
```python
# In cpp_analyzer.py index_project()
finally:
    if executor:
        executor.shutdown(wait=True, cancel_futures=True)
        # Add timeout
        try:
            # Wait maximum 5 seconds for workers
            executor.shutdown(wait=True, cancel_futures=True)
        except Exception:
            # Force kill workers after timeout
            for pid in worker_pids:
                os.kill(pid, signal.SIGKILL)
```

**Pros:**
- Prevents indefinite hang
- Forceful but effective

**Cons:**
- Workers may be killed mid-operation
- Potential cache corruption if killed during write

**Estimated Effort:** 1 day
**Risk Level:** Low

---

### Option 2: Implement Graceful Cancellation

**Concept**: Signal workers to stop processing and exit cleanly

**Implementation**:
1. Add shared `multiprocessing.Event` for cancellation
2. Check event periodically in worker loop
3. Signal event on Ctrl-C
4. Workers exit cleanly when event is set

**Pros:**
- Clean shutdown, no corruption risk
- Workers can finish current file
- Proper resource cleanup

**Cons:**
- More complex implementation
- Requires worker cooperation

**Estimated Effort:** 2-3 days
**Risk Level:** Medium

---

### Option 3: Background Indexing with Async Cancellation

**Concept**: Run indexing in background asyncio task, cancel on shutdown

**Implementation**:
```python
# In cpp_mcp_server.py
async def background_index():
    try:
        await asyncio.to_thread(analyzer.index_project, files)
    except asyncio.CancelledError:
        # Gracefully stop indexing
        analyzer.cancel_indexing()
        raise

# On shutdown
indexing_task.cancel()
await indexing_task  # Wait for cancellation
```

**Pros:**
- Proper async/await pattern
- Clean integration with FastAPI/Uvicorn
- Cancellable by design

**Cons:**
- Requires restructuring indexing code
- Need to make indexing cancellable

**Estimated Effort:** 3-4 days
**Risk Level:** Medium-High

---

## Recommended Approach

### Primary Recommendation: **Option 1 (Shutdown Timeout) + Option 2 (Graceful Cancellation)**

**Phase 1: Quick Fix (Option 1)**
- Add 5-second timeout to executor.shutdown()
- Prevents indefinite hang
- Acceptable for development use

**Phase 2: Proper Fix (Option 2)**
- Implement cancellation event
- Workers check event and exit cleanly
- No corruption risk

**Rationale:**
1. Phase 1 provides immediate relief (1 day)
2. Phase 2 provides proper long-term solution (2-3 days)
3. Incremental approach reduces risk
4. Can ship Phase 1 while working on Phase 2

---

## Testing Requirements

### Manual Tests

1. **Shutdown During Indexing**:
   - Start indexing large project
   - Press Ctrl-C after 30 seconds
   - Verify: Exits within 5 seconds

2. **Shutdown While Idle**:
   - Server running, no indexing
   - Press Ctrl-C
   - Verify: Exits immediately

3. **Shutdown During Refresh**:
   - Trigger refresh_project
   - Press Ctrl-C during refresh
   - Verify: Clean exit, no corruption

### Automated Tests

1. **Unit Test**: Executor shutdown with timeout
2. **Integration Test**: Full shutdown sequence
3. **Stress Test**: Rapid shutdown requests

---

## Decision Log

**2025-12-26**: Initial identification during memory leak testing
- **Observation**: Server requires 5 Ctrl-C presses to exit
- **Impact**: Annoying during manual testing, blocks quick iteration
- **Decision**: Document for future investigation after memory leak fix
- **Priority**: Medium - affects UX but not critical
- **Next Steps**:
  1. Focus on memory leak fix first (higher priority)
  2. Implement Phase 1 quick fix (shutdown timeout)
  3. Plan Phase 2 proper fix (graceful cancellation)

---

## References

**Code References:**
- `mcp_server/cpp_mcp_server.py` - Server lifecycle
- `mcp_server/cpp_analyzer.py:index_project()` - Indexing with ProcessPoolExecutor
- `mcp_server/cpp_analyzer.py:_cleanup_worker_analyzer()` - Worker cleanup
- `mcp_server/http_server.py` - SSE server

**Related Issues:**
- Issue #14 / docs/issues/004: Memory leak - observed during testing of that issue
- Interrupt handling documentation: docs/INTERRUPT_HANDLING.md

**External Resources:**
- [Python ProcessPoolExecutor shutdown](https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.Executor.shutdown)
- [FastAPI shutdown events](https://fastapi.tiangolo.com/advanced/events/)
- [Python signal handling](https://docs.python.org/3/library/signal.html)

---

## Next Steps

1. **After Memory Leak Fix** (Issue #14):
   - Implement Phase 1: Shutdown timeout (1 day)
   - Test with large projects
   - Deploy if acceptable

2. **Future Enhancement**:
   - Implement Phase 2: Graceful cancellation (2-3 days)
   - Add automated shutdown tests
   - Document proper shutdown procedure

**Trigger Conditions** (when to prioritize):
- User complaints about shutdown behavior
- CI/CD timeouts due to shutdown hang
- After Issue #14 resolved

**Owner**: TBD
