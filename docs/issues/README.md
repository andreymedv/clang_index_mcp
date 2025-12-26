# Future Work and Issues Tracker

This directory tracks postponed bugs, proposed features, and architectural improvements for the Clang Index MCP Server.

## Quick Reference

| ID | Title | Category | Priority | Status | Date |
|----|-------|----------|----------|--------|------|
| 001 | Cache Scalability for Large Codebases | Architecture | High | ✅ Completed | 2025-11-16 → 2025-11-17 |
| 002 | Test Freeze in Concurrent Cache Write Protection | Bug | High | ✅ Fixed | 2025-12-25 → 2025-12-26 |
| 003 | macOS libclang Discovery - Hardcoded Paths | Bug | Medium | ✅ Fixed | 2025-12-25 → 2025-12-26 |
| 004 | Memory Leak During Large Project Indexing | Bug | High | ✅ Fixed | 2025-12-26 |
| 005 | Status Reports Zero Files Before Refresh | Bug | Medium | ✅ Fixed | 2025-12-26 |
| 006 | Server Shutdown Hangs on Ctrl-C | Bug | Medium | ✅ Fixed | 2025-12-26 |

## Categories

- **Architecture**: System-level design improvements
- **Feature**: New functionality or capabilities
- **Performance**: Optimization and speed improvements
- **Bug**: Known issues deferred for later
- **Technical Debt**: Code quality and maintainability

## Priority Levels

- **High**: Important for production use or affects many users
- **Medium**: Useful improvement but not critical
- **Low**: Nice to have or exploratory idea

## Status Values

- **Proposed**: Initial idea, needs discussion
- **Postponed**: Decided to defer implementation
- **Planned**: Accepted and scheduled for future sprint
- **In Progress**: Currently being implemented
- **Blocked**: Waiting on dependencies or decisions
- **Open**: Issue identified, not yet started
- **✅ Completed/Fixed**: Issue resolved and verified

## How to Add New Issues

1. Create a new file: `NNN-short-title.md` (use next available number)
2. Copy template from `TEMPLATE.md`
3. Fill in all sections
4. Add entry to the table above
5. Commit with message: "docs: Add issue NNN - short title"

## Issue Files

- [001-cache-scalability.md](001-cache-scalability.md) - Cache Scalability for Large Codebases (✅ **COMPLETED** v3.0.0)
- [002-test-freeze-concurrent-cache.md](002-test-freeze-concurrent-cache.md) - Test Freeze in Concurrent Cache Write Protection (✅ **FIXED** commit 828b648)
- [003-macos-libclang-discovery.md](003-macos-libclang-discovery.md) - macOS libclang Discovery - Hardcoded Paths (✅ **FIXED** commit 0ca96eb)
- [004-memory-leak-during-indexing.md](004-memory-leak-during-indexing.md) - Memory Leak During Large Project Indexing (✅ **FIXED** PR #77)
- [005-status-zero-files-before-refresh.md](005-status-zero-files-before-refresh.md) - Status Reports Zero Files Before Refresh (✅ **FIXED** PR #78)
- [006-server-shutdown-hang.md](006-server-shutdown-hang.md) - Server Shutdown Hangs on Ctrl-C (✅ **FIXED** PR #79)
