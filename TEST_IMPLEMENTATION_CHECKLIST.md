# Test Implementation Checklist

**Purpose**: Track future test enhancements
**Status**: ✅ **Production Ready** - 118/123 tests passing (95.9%)
**Last Updated**: 2025-11-14

See [TEST_COVERAGE.md](TEST_COVERAGE.md) for detailed coverage information.

---

## Phase 4: Future Enhancements

**Status**: Not Started
**Priority**: Optional improvements for production hardening

### 4.1 Critical Security Enhancement (P0)

- [ ] **Task 4.1.1**: Implement ReDoS prevention
  - **Current State**: Known vulnerability - catastrophic backtracking patterns cause 30s+ timeouts
  - **Target**: Pre-execution regex complexity analysis
  - **Approach**:
    - Analyze regex pattern before execution
    - Detect patterns with exponential backtracking: `(a+)+`, `(a*)*`, `(a|a)*`
    - Reject dangerous patterns or use timeout-safe regex engine
    - Consider libraries: `regex` (module), `re2`, or custom validator
  - **Test**: Unskip `test_regex_dos_prevention` after implementation
  - **Files to Modify**:
    - `mcp_server/search_engine.py` - Add regex validation
    - `tests/security/test_regex_security.py` - Remove skip, verify protection
  - **Priority**: P0 - Security vulnerability
  - **Estimated Time**: 4-6 hours

### 4.2 Integration Testing (P1)

- [ ] **Task 4.2.1**: Add MCP protocol integration tests
  - Test actual MCP server with real protocol messages
  - Verify all 14 MCP tools work end-to-end
  - Test with `mcp` Python package in client mode
  - **Priority**: P1
  - **Estimated Time**: 6-8 hours

- [ ] **Task 4.2.2**: Add vcpkg integration tests on real projects
  - Test with actual vcpkg-managed dependencies
  - Verify include path detection
  - Test with common libraries (boost, fmt, etc.)
  - **Priority**: P2
  - **Estimated Time**: 3-4 hours

### 4.3 Performance & Benchmarking (P2)

- [ ] **Task 4.3.1**: Add performance benchmarks
  - Benchmark indexing speed (files/second)
  - Benchmark search performance
  - Track regression over time
  - Use `pytest-benchmark` plugin
  - **Priority**: P2
  - **Estimated Time**: 4-6 hours

- [ ] **Task 4.3.2**: Add memory profiling tests
  - Profile memory usage during large project indexing
  - Detect memory leaks
  - Verify cache doesn't grow unbounded
  - Use `memory_profiler` or `tracemalloc`
  - **Priority**: P2
  - **Estimated Time**: 3-4 hours

### 4.4 Test Quality Improvements (P2)

- [ ] **Task 4.4.1**: Add mutation testing
  - Use `mutmut` or `cosmic-ray`
  - Verify tests catch introduced bugs
  - Target: 80%+ mutation score
  - **Priority**: P2
  - **Estimated Time**: 4-6 hours

- [ ] **Task 4.4.2**: Generate HTML test reports
  - Use `pytest-html` for rich reports
  - Include in CI/CD pipeline
  - Track historical trends
  - **Priority**: P2
  - **Estimated Time**: 2-3 hours

### 4.5 Windows Testing (P1)

- [ ] **Task 4.5.1**: Run tests on Windows CI
  - Set up Windows GitHub Actions runner
  - Verify all platform tests pass
  - Fix Windows-specific issues
  - **Priority**: P1
  - **Estimated Time**: 3-4 hours

---

## Known Limitations

### 1. ⚠️ ReDoS Prevention Not Implemented (P0)
**Impact**: Regex patterns with catastrophic backtracking cause 30s+ timeouts
**Test**: `tests/security/test_regex_security.py` - Currently skipped
**Resolution**: Task 4.1.1 above

### 2. Platform Tests Skipped
**Impact**: Windows behavior not validated on Linux CI
**Tests**: 3 Windows-specific tests skip on Linux
**Resolution**: Task 4.5.1 above

### 3. Slow Tests Skipped by Default
**Impact**: Long-running tests not in standard test run
**Tests**: 2 tests (out of memory, 10k files)
**Run With**: `pytest tests/ -m slow`

---

## Test Execution Quick Reference

```bash
# Run all tests
pytest tests/

# Run critical tests only
pytest tests/ -m critical

# Run specific category
pytest tests/ -m security

# Run with coverage
pytest tests/ --cov=mcp_server --cov-report=html

# Run slow tests (not default)
pytest tests/ -m slow
```

---

**Last Updated**: 2025-11-14
