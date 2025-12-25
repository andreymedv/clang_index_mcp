# Test Warnings: Resource Leaks and Deprecations

**Status:** ⚠️ **NEEDS INVESTIGATION**
**Date Reported:** 2025-12-25
**Severity:** Medium - Does not block tests but indicates resource leaks
**Affected:** SSE transport tests, concurrent tests

## Summary

`make test` produces several warnings indicating potential resource leaks and deprecation issues that should be addressed.

## Warning Categories

### 1. 🔴 Fork Deprecation Warning (CRITICAL - See Issue #002)

**Affected Tests:**
- `tests/edge_cases/test_race_conditions.py::TestConcurrentModification::test_concurrent_file_modification`
- `tests/robustness/test_data_integrity.py::TestAtomicCacheWrites::test_concurrent_cache_write_protection`
- `tests/test_concurrent_queries_during_indexing.py` (4 tests)
- `tests/test_tools_during_analysis_progress.py::test_background_indexer_progress_integration`

**Warning:**
```
/usr/lib/python3.12/multiprocessing/popen_fork.py:66: DeprecationWarning:
This process (pid=80488) is multi-threaded, use of fork() may lead to
deadlocks in the child.
  self.pid = os.fork()
```

**Analysis:** Same root cause as Issue #002 - ProcessPoolExecutor using fork() in multi-threaded process

**Resolution:** See [TEST_FREEZE_ISSUE.md](TEST_FREEZE_ISSUE.md) and [Issue #002](issues/002-test-freeze-concurrent-cache.md)

**Fix:** Set multiprocessing to use 'spawn' in tests/conftest.py

---

### 2. ⚠️ Unclosed MemoryObjectReceiveStream (SSE Transport)

**Severity:** Medium - Resource leak in tests or production code
**Impact:** May cause resource exhaustion over time if in production code

**Affected Tests:**
- `tests/test_sse_transport.py::test_sse_session_id_in_endpoint_event`
- `tests/test_sse_transport.py::test_sse_endpoint_event`
- `tests/test_sse_transport.py::test_sse_with_messages_endpoint`
- `tests/test_sse_transport.py::TestSSEProtocol::test_sse_content_type`
- `tests/test_sse_transport.py::TestSSEProtocol::test_sse_cache_control`
- `tests/test_sse_transport.py::TestSSEProtocol::test_sse_reconnection`
- `tests/test_tools_during_analysis_progress.py::test_progress_callback_invoked` (2 instances)

**Warning:**
```
/home/andrey/repos/cplusplus_mcp/mcp_env/lib/python3.12/site-packages/anyio/streams/memory.py:183:
ResourceWarning: Unclosed <MemoryObjectReceiveStream at 794e706e3920>
  warnings.warn(
Enable tracemalloc to get traceback where the object was allocated.
See https://docs.pytest.org/en/stable/how-to/capture-warnings.html#resource-warnings for more info.
```

#### Root Cause Analysis

**Location:** `anyio/streams/memory.py` - Part of anyio library used for async I/O in SSE transport

**Likely Causes:**

1. **SSE Transport Cleanup Issue** (Most Likely)
   - `mcp_server/http_server.py` - SSE endpoint implementation
   - MemoryObjectReceiveStream not properly closed on disconnect
   - Missing cleanup in exception handlers
   - Async context not properly managed

2. **Test Cleanup Issue**
   - Tests not properly closing SSE connections
   - Missing `await connection.close()` or similar cleanup
   - Async fixtures not properly torn down

3. **anyio Library Issue**
   - Could be a known issue in anyio library version
   - May need library upgrade

#### Investigation Steps

**1. Enable tracemalloc to get allocation traceback:**
```python
# Add to test file or conftest.py
import tracemalloc
tracemalloc.start()
```

Then run:
```bash
pytest tests/test_sse_transport.py -v -W error::ResourceWarning
```

**2. Check SSE endpoint cleanup in production code:**
```python
# mcp_server/http_server.py - Check for missing cleanup
# Look for:
# - try/finally blocks around SSE streaming
# - Proper close() calls on MemoryObjectReceiveStream
# - Context manager usage (async with)
```

**3. Check test cleanup:**
```python
# tests/test_sse_transport.py - Check for missing teardown
# Ensure all SSE connections are properly closed in tests
```

#### Potential Fix Locations

**Production Code:**
- `mcp_server/http_server.py` - SSE endpoint handlers
  - Lines with `MemoryObjectReceiveStream` usage
  - Event streaming loops
  - Connection cleanup on disconnect/error

**Test Code:**
- `tests/test_sse_transport.py` - SSE test fixtures
  - Add proper cleanup in teardown
  - Use async context managers
  - Ensure connections closed after each test

#### Recommended Fix Pattern

```python
# In mcp_server/http_server.py or tests
async def sse_endpoint():
    stream = MemoryObjectReceiveStream()
    try:
        # ... SSE logic ...
        async for event in stream:
            yield event
    finally:
        await stream.aclose()  # Ensure cleanup
```

Or use context manager:
```python
async def sse_endpoint():
    async with MemoryObjectReceiveStream() as stream:
        async for event in stream:
            yield event
```

---

### 3. ℹ️ Template Calls Warning (Known Limitation)

**Status:** Expected - Not a bug
**Severity:** Informational

**Affected Test:**
- `tests/test_call_sites_extraction.py::TestTemplateCalls::test_template_instantiation_calls`

**Warning:**
```
/home/andrey/repos/cplusplus_mcp/tests/test_call_sites_extraction.py:252: UserWarning:
Template calls not tracked - this is a known limitation with libclang
  warnings.warn("Template calls not tracked - this is a known limitation with libclang")
```

**Analysis:** This is intentional and documented. Libclang has known limitations with template instantiation tracking.

**Action:** None required - warning is informational

---

## Impact Assessment

### Resource Leaks

**If in Production Code:**
- ⚠️ **Memory leak:** Unclosed streams accumulate over time
- ⚠️ **Resource exhaustion:** Long-running servers may run out of file descriptors
- ⚠️ **Performance degradation:** Leaked resources consume memory/CPU

**If Only in Tests:**
- ✅ **No production impact**
- ⚠️ **Test suite resource usage:** May slow down test execution
- ⚠️ **CI/CD impact:** May cause intermittent failures in resource-constrained environments

### Fork Warnings

See [TEST_FREEZE_ISSUE.md](TEST_FREEZE_ISSUE.md) - Can cause deadlocks and test freezes

---

## Action Plan

### Immediate (Diagnostics)

1. ✅ **Document warnings** (this file)
2. 🔲 **Enable tracemalloc in tests:**
   ```python
   # tests/conftest.py
   import tracemalloc
   tracemalloc.start()
   ```
3. 🔲 **Run tests with ResourceWarning as error:**
   ```bash
   pytest tests/test_sse_transport.py -W error::ResourceWarning
   ```
4. 🔲 **Identify allocation source** from traceback

### Short Term (Fix)

1. 🔲 **Review SSE transport code** for missing cleanup:
   - Check `mcp_server/http_server.py` SSE endpoints
   - Add proper cleanup in finally blocks
   - Use async context managers where appropriate

2. 🔲 **Review test cleanup** in `tests/test_sse_transport.py`:
   - Ensure all connections closed in teardown
   - Add cleanup fixtures if needed

3. 🔲 **Fix identified leaks** in production and/or test code

4. 🔲 **Verify fix** - warnings should disappear:
   ```bash
   make test 2>&1 | grep -A 2 "ResourceWarning"
   # Should return no results
   ```

### Long Term (Prevention)

1. 🔲 **Add resource leak detection to CI:**
   ```yaml
   # .github/workflows/test.yml
   - name: Run tests with resource warnings
     run: pytest -W error::ResourceWarning
   ```

2. 🔲 **Document cleanup patterns** for async code:
   - Best practices for SSE/async cleanup
   - Required cleanup in all async endpoints

3. 🔲 **Add linter rules** for resource management:
   - Detect missing cleanup in async code
   - Require context managers for streams

---

## Testing

### Reproduce Warnings

```bash
# All warnings
make test 2>&1 | grep -A 5 "ResourceWarning\|DeprecationWarning"

# Only SSE warnings
pytest tests/test_sse_transport.py -v 2>&1 | grep -A 3 "ResourceWarning"

# With tracemalloc (shows allocation source)
PYTHONTRACEMALLOC=1 pytest tests/test_sse_transport.py -v
```

### Verify Fix

After fixing:
```bash
# Should have no ResourceWarning
make test 2>&1 | grep "ResourceWarning"
# Exit code should be 1 (no matches)

# Should pass with warnings as errors
pytest tests/test_sse_transport.py -W error::ResourceWarning
```

---

## Related Issues

- **Issue #002:** Test freeze due to fork() deprecation
- **SSE Transport:** `mcp_server/http_server.py`
- **anyio Documentation:** https://anyio.readthedocs.io/en/stable/streams.html

---

## Summary of Warnings

| Warning Type | Count | Severity | Status | Fix Priority |
|--------------|-------|----------|--------|--------------|
| Fork deprecation | 7 tests | Critical | See Issue #002 | HIGH |
| Unclosed MemoryObjectReceiveStream | 8 instances | Medium | Needs investigation | MEDIUM |
| Template calls limitation | 1 test | Info | Expected/documented | N/A |

**Total Warnings:** 16 (7 critical, 8 medium, 1 informational)

---

**Last Updated:** 2025-12-25
**Priority:** MEDIUM (High for fork issue - see #002)
**Next Step:** Enable tracemalloc and identify SSE resource leak source
