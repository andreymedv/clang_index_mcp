# Remaining Issues Summary

**Last Updated:** 2025-12-26
**Status:** 2 open issues remain (1 HIGH, 1 MEDIUM priority)

---

## 🔴 HIGH Priority - Open Issues

### Issue 002: Test Freeze in Concurrent Cache Write Protection
- **Status:** 🔴 Open - **BLOCKS TEST SUITE**
- **Impact:** Test `test_concurrent_cache_write_protection` freezes indefinitely
- **Root Cause:** Multi-threaded process using `fork()` → deadlock (Python 3.12+)
- **Quick Fix:** Set multiprocessing to use 'spawn' instead of 'fork' in `tests/conftest.py`
- **Documentation:** [issues/002-test-freeze-concurrent-cache.md](issues/002-test-freeze-concurrent-cache.md)

---

## 🟡 MEDIUM Priority - Open Issues

### Issue 003: macOS libclang Discovery - Hardcoded Paths
- **Status:** 🟡 Open - **macOS ONLY**
- **Impact:** Downloads bundled libclang instead of using system installations
- **Root Cause:** Hardcoded paths don't include Xcode CLT or Homebrew locations
- **Workaround:** `export LIBCLANG_PATH=/Library/Developer/CommandLineTools/usr/lib/libclang.dylib`
- **Recommended Fix:** Hybrid approach with smart discovery (`xcrun`, `brew --prefix llvm`)
- **Documentation:** [issues/003-macos-libclang-discovery.md](issues/003-macos-libclang-discovery.md)

---

## 📋 Deferred Issues (Lower Priority)

These issues have acceptable workarounds and are deferred:

### Manual Test Issue #4: Class Search Substring Matching
- **Priority:** Low
- **Impact:** Minor usability (searches for "View" returns View, ViewManager, ListView)
- **Workaround:** Use exact patterns when needed

### Manual Test Issue #5: Tool Descriptions for Small Models
- **Priority:** Low
- **Impact:** Edge case (affects only small models like Qwen3-4B)
- **Workaround:** Use more capable models (GPT-4, Claude)

### Manual Test Issue #7: Unauthorized Full Refresh
- **Priority:** Medium (mitigated by other fixes)
- **Impact:** Small models may trigger expensive full refresh
- **Mitigation:** Fast incremental refresh reduces likelihood

### Manual Test Issue #9: libclang Paths on macOS
- **Priority:** Low (same as Issue 003)
- **Note:** This is the same as Issue 003 above (documented in two places)

---

## ✅ Recently Completed Issues

### 2025-12-26 (Large Project Stability)
- **Issue 004 / #14:** Memory leak during indexing - PR #77 (9-11x memory reduction)
- **Issue 005 / #15:** Status reports zero files before refresh - PR #78
- **Issue 006 / #16:** Server shutdown hangs on Ctrl-C - PR #79

### 2025-12-21 to 2025-12-25 (Manual Test Issues)
- **Issue #1:** State synchronization race - PR #66
- **Issue #2:** refresh_project timeout - PR #63
- **Issue #3:** File descriptor leak - PR #62
- **Issue #6:** Sequential processing - PR #73
- **Issue #8:** Missing header symbols - PR #71
- **Issue #10:** Zero file counts - PR #64
- **Issue #11:** Missing progress - PR #72
- **Issue #12:** DB connection lifecycle - PR #69
- **Issue #13:** Headers with fallback args - PR #67

### 2025-11-17 (Architecture)
- **Issue 001:** Cache Scalability - Completed in v3.0.0 (SQLite migration)

---

## Summary Statistics

**Total Issues Documented:** 16 (excluding duplicates)
- ✅ **Completed/Fixed:** 13 (81%)
- 🔴 **Open (High Priority):** 1 (6%)
- 🟡 **Open (Medium Priority):** 1 (6%)
- 📋 **Deferred (Low Priority):** 4 (25%)

**Net Open Issues:** 2 (both have workarounds or are platform-specific)

---

## Next Actions

### Immediate (This Week)
1. **Fix Issue 002 (Test Freeze)** - Blocking test suite
   - Add `multiprocessing.set_start_method('spawn', force=True)` to `tests/conftest.py`
   - Verify all 580+ tests pass
   - Estimated: 2-4 hours

### Short-term (Next 1-2 Weeks)
2. **Fix Issue 003 (macOS libclang)** - Platform compatibility
   - Implement hybrid discovery with expanded search paths
   - Test on Apple Silicon and Intel Macs
   - Estimated: 1-2 days

### Long-term (Future)
3. **Review Phase 5 Deferred Issues** - UX polish
   - Evaluate if issues #4, #5, #7 warrant fixes
   - Collect user feedback
   - Prioritize based on real-world impact

---

## References

- **Issue Tracker:** [docs/issues/README.md](issues/README.md)
- **Manual Test Observations:** [docs/MANUAL_TEST_OBSERVATIONS.md](MANUAL_TEST_OBSERVATIONS.md)
- **Issue Fixing Plan:** [docs/ISSUE_FIXING_PLAN.md](ISSUE_FIXING_PLAN.md)
