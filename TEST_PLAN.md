# Comprehensive Test Plan for Clang Index MCP

## Document Purpose

This document maps each requirement from REQUIREMENTS.md to specific test cases, organized by category. Each test case specifies what should be tested, expected outcomes, and test data needed.

**Note**: The test plan has been split into modular files for better manageability. Use the links below to navigate to specific test categories.

### Recent Enhancements

The following test coverage has been added to ensure comprehensive validation of all MCP server functionality:

**Section 4 - MCP Tool Tests:**
- Added edge case tests for search_classes (empty patterns, Unicode, long patterns, special regex chars)
- Added path validation tests for find_in_file (path traversal, special characters)

**Section 5 - Compilation Configuration Tests:**
- REQ-5.1: Added command string parsing test (shlex with quotes and spaces)
- REQ-5.2: Added vcpkg auto-detection test (REQ-5.2.5)

**Section 6 - Caching and Performance Tests:**
- REQ-6.2: Added cache version mismatch invalidation test (REQ-6.2.5)
- REQ-6.4: Added indexing progress file persistence test (REQ-6.4.6)
- REQ-6.4: Added terminal detection for adaptive progress reporting (REQ-6.4.7)

**Section 7 - Project Management Tests:**
- REQ-7.3: Added platform-specific libclang path tests (macOS, Linux, Windows)
- REQ-7.5: Added environment variable test for diagnostic level (CPP_ANALYZER_DIAGNOSTIC_LEVEL)

**Section 5 - Compilation Configuration Tests:**
- REQ-5.5: Added vcpkg integration tests (auto-detection, include paths)
- REQ-5.6: Added Compile Commands Manager Extended APIs tests (6 new test functions)

**Section 6 - Caching and Performance Tests:**
- REQ-6.5: Added Progress Persistence tests (7 new test functions for save/load/status tracking)

**Section 7 - Project Management Tests:**
- REQ-7.5.5-7.5.6: Added DiagnosticLogger API tests (set_level, set_output_stream, configure_from_config)

**Section 8 - Statistics and Monitoring Tests (NEW SECTION):**
- REQ-8.1: Runtime Statistics APIs (3 test functions)
- REQ-8.2: Call Graph Statistics (4 test functions for code quality analysis)
- REQ-8.3: Cache Management APIs (4 test functions)

**Section 10 - Security, Robustness, and Edge Case Tests (NEW SECTION):**
- **REQ-SEC-1**: Comprehensive security tests (5 P0-critical test functions)
  - Path traversal attack prevention (9 attack vectors)
  - Regex DoS prevention (catastrophic backtracking detection)
  - Command injection prevention in compile_commands.json
  - Symlink attack prevention
  - Malicious configuration value validation
- **REQ-ROB-1**: Data integrity and atomic operations (4 P0-critical test functions)
  - Atomic cache write verification
  - Malformed JSON cache recovery (4 corruption types)
  - Cache consistency after interruption
  - Concurrent cache write protection
- **REQ-ERR-1**: Comprehensive error handling (6 P0-P1 test functions)
  - File permission error handling
  - Disk full scenario handling
  - Corrupt compile_commands.json recovery (5 corruption types)
  - Empty and whitespace-only file handling
  - Null bytes in source files
  - Extremely long symbol names (5000+ characters)
- **REQ-EDGE-1**: Boundary conditions and edge cases (4 P1-P2 test functions)
  - File size boundary testing (exact limit behavior)
  - Maximum inheritance depth (100-level hierarchy)
  - Many function overloads (50+ overloads)
  - Concurrent file modification during parsing
- **REQ-PLAT-1**: Platform-specific tests (3 P1 test functions)
  - Unix file permission handling
  - Windows path separator normalization
  - Windows MAX_PATH (260 char) limit handling

**Total New Tests in Section 10**: 22 test functions covering 90+ identified gaps
**Priority Distribution**: 9 P0 (Critical), 8 P1 (High), 5 P2 (Medium)

---

## Table of Contents

### Test Plan Documents

1. **[Base Functionality](./TEST_PLAN_BASE_FUNCTIONALITY.md)**
   - Core Functional Requirements Tests (REQ-1.x)
   - Entity Extraction Tests (REQ-2.x)
   - Entity Relationship Tests (REQ-3.x)

2. **[MCP Tools](./TEST_PLAN_MCP_TOOLS.md)**
   - MCP Tool Tests (REQ-4.x)
   - All 14 MCP tools with happy path, validation, and edge cases

3. **[Compilation Configuration](./TEST_PLAN_COMPILE_COMMANDS.md)**
   - Compilation Configuration Tests (REQ-5.x)
   - compile_commands.json handling
   - vcpkg integration

4. **[Advanced Features](./TEST_PLAN_ADVANCED_FEATURES.md)**
   - Caching and Performance Tests (REQ-6.x)
   - Project Management Tests (REQ-7.x)

5. **[Statistics and Monitoring](./TEST_PLAN_STATISTICS.md)**
   - Statistics and Monitoring Tests (REQ-8.x)
   - Runtime statistics and call graph analytics

6. **[Integration and Test Fixtures](./TEST_PLAN_INTEGRATION.md)**
   - Test Fixtures Required
   - Integration test utilities

7. **[Security, Robustness, and Edge Cases](./TEST_PLAN_SECURITY_ROBUSTNESS.md)** ⚠️ **CRITICAL**
   - Security Tests (REQ-SEC-1) - P0 Priority
   - Data Integrity Tests (REQ-ROB-1) - P0 Priority
   - Error Handling Tests (REQ-ERR-1) - P1 Priority
   - Edge Case Tests (REQ-EDGE-1) - P1 Priority
   - Platform-Specific Tests (REQ-PLAT-1) - P1 Priority

---

## Test Execution Strategy

### Phase Approach

Tests should be executed in the following order:

1. **Phase 0: Infrastructure Setup**
   - Set up test environment
   - Create fixtures and utilities
   - Validate test framework

2. **Phase 1: Base Functionality**
   - Core indexing and extraction (Section 1-3)
   - Establish baseline functionality

3. **Phase 2: MCP Tools**
   - All 14 MCP tool tests (Section 4)
   - Verify API contracts

4. **Phase 3: Advanced Features**
   - Compilation configuration (Section 5)
   - Caching and performance (Section 6)
   - Project management (Section 7)

4. **Phase 4: Statistics and Integration**
   - Statistics APIs (Section 8)
   - Integration tests (Section 9)

5. **Phase 5: Security and Robustness** ⚠️ **CRITICAL**
   - All P0 security tests must pass
   - All P0 data integrity tests must pass
   - P1 error handling and edge cases

### Test Priorities

- **P0 (Critical)**: Must pass before any release - 9 tests
- **P1 (High)**: Should pass before release - 8 tests
- **P2 (Medium)**: Can be addressed post-release - 5 tests
- **P3 (Low)**: Nice to have

---

## Coverage Goals

- **Statement Coverage**: 80%+ overall
- **Branch Coverage**: 70%+ for critical paths
- **Security Tests**: 100% pass rate for P0 tests
- **Data Integrity Tests**: 100% pass rate for P0 tests
- **MCP Tool Tests**: 100% pass rate for all 14 tools

---

## Test Metrics to Track

### Execution Metrics
- Total tests executed
- Tests passed
- Tests failed
- Tests skipped
- Pass rate percentage

### Coverage Metrics
- Statement coverage %
- Branch coverage %
- Function coverage %
- Lines of code tested vs. total

### Performance Metrics
- Test execution time
- Indexing performance benchmarks
- Memory usage during tests

### Quality Metrics
- Critical bugs found
- Security vulnerabilities identified
- Regression issues caught

---

## Quick Reference

| Test Category | Document | Priority | Est. Tests |
|---------------|----------|----------|------------|
| Base Functionality | [TEST_PLAN_BASE_FUNCTIONALITY.md](./TEST_PLAN_BASE_FUNCTIONALITY.md) | P1 | 50+ |
| MCP Tools | [TEST_PLAN_MCP_TOOLS.md](./TEST_PLAN_MCP_TOOLS.md) | P0-P1 | 56+ |
| Compile Commands | [TEST_PLAN_COMPILE_COMMANDS.md](./TEST_PLAN_COMPILE_COMMANDS.md) | P1 | 25+ |
| Advanced Features | [TEST_PLAN_ADVANCED_FEATURES.md](./TEST_PLAN_ADVANCED_FEATURES.md) | P1-P2 | 40+ |
| Statistics | [TEST_PLAN_STATISTICS.md](./TEST_PLAN_STATISTICS.md) | P2 | 11 |
| Integration | [TEST_PLAN_INTEGRATION.md](./TEST_PLAN_INTEGRATION.md) | P1 | N/A |
| **Security & Robustness** | [**TEST_PLAN_SECURITY_ROBUSTNESS.md**](./TEST_PLAN_SECURITY_ROBUSTNESS.md) | **P0-P1** | **22** |
| **TOTAL** | | | **200+** |

---

**Last Updated**: 2025-11-14
**Version**: 3.0 (Modularized Structure)
