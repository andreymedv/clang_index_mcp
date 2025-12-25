# Future Work and Issues Tracker

This directory tracks postponed bugs, proposed features, and architectural improvements for the Clang Index MCP Server.

## Quick Reference

| ID | Title | Category | Priority | Status | Date |
|----|-------|----------|----------|--------|------|
| 001 | Cache Scalability for Large Codebases | Architecture | High | Postponed | 2025-11-16 |
| 002 | Test Freeze in Concurrent Cache Write Protection | Bug | High | Open | 2025-12-25 |

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

## How to Add New Issues

1. Create a new file: `NNN-short-title.md` (use next available number)
2. Copy template from `TEMPLATE.md`
3. Fill in all sections
4. Add entry to the table above
5. Commit with message: "docs: Add issue NNN - short title"

## Issue Files

- [001-cache-scalability.md](001-cache-scalability.md) - Cache Scalability for Large Codebases
- [002-test-freeze-concurrent-cache.md](002-test-freeze-concurrent-cache.md) - Test Freeze in Concurrent Cache Write Protection (🔴 **BLOCKS TEST SUITE**)
