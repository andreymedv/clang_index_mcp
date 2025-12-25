# Archived Documentation

This directory contains historical documentation from earlier development phases and completed work that has been archived to reduce token usage. These files are preserved for reference but are no longer actively used in day-to-day development.

## Recently Archived (2025-12-25) - Issue Fixes

### Completed Issue Investigation Files
- **FIX_ISSUE_3_ANALYSIS.md** (2.2K) - Detailed analysis of file descriptor leak fix (Issue #3, PR #62)
- **ISSUE_3_INVESTIGATION.md** (3.8K) - Investigation notes for file descriptor leak (Issue #3)

### Detailed Planning Documents (Completed Work - Token Savings: ~65K)
- **MANUAL_TEST_OBSERVATIONS_DETAILED.md** (56K, 1553 lines) - Full detailed manual testing observations
  - Contains comprehensive investigation notes, root cause analysis, and validation details for all 13 issues
  - **Current compact version:** `../MANUAL_TEST_OBSERVATIONS.md` (90 lines)

- **ISSUE_FIXING_PLAN_DETAILED.md** (19K, 488 lines) - Complete issue fixing plan with implementation details
  - Contains detailed root cause analysis, solution options, and validation steps for all fixed issues
  - **Current compact version:** `../ISSUE_FIXING_PLAN.md` (89 lines)

## Historical Requirements and Analysis (Pre-2025)

### Requirements Documents
- **REQUIREMENTS.md** - Original project requirements document (superseded by current implementation)
- **REQUIREMENTS_GAPS_ANALYSIS.md** - Gap analysis between requirements and implementation (historical)
- **REQUIREMENTS_HTTP_SUPPORT.md** - HTTP/SSE transport requirements (implemented in v0.3.0)
- **MCP_TOOLS_EVALUATION.md** - Evaluation of MCP tool designs (historical analysis)

## Token Savings Summary

Archiving these files saves approximately **70K+ tokens** when working with documentation:
- Issue #3 investigation files: ~6K tokens
- MANUAL_TEST_OBSERVATIONS compaction: ~50K tokens
- ISSUE_FIXING_PLAN compaction: ~15K tokens

## When to Reference Archived Files

Reference these archived files when you need:
- **Historical context** on why specific decisions were made
- **Detailed investigation notes** for similar future issues
- **Complete root cause analysis** for educational purposes
- **Full validation details** for regression testing
- **Implementation alternatives** that were considered but not chosen

## Current Active Documentation

For current, actively-used documentation, see the main `docs/` directory:

**Issue Tracking:**
- `MANUAL_TEST_OBSERVATIONS.md` - Compact issue summary table with status and workarounds
- `ISSUE_FIXING_PLAN.md` - Summary with deferred issues (Phase 4) and next steps

**Architecture & Design:**
- `ANALYSIS_STORAGE_ARCHITECTURE.md` - Storage architecture (active)
- `INCREMENTAL_ANALYSIS_DESIGN.md` - Incremental analysis design (active)
- `HEADER_EXTRACTION_ARCHITECTURE.md` - Header extraction design
- `COMPILE_COMMANDS_INTEGRATION.md` - compile_commands.json integration

**Testing & Operations:**
- `CLAUDE_TESTING_GUIDE.md` - Testing guide for Claude Code
- `INTERRUPT_HANDLING.md` - Interrupt handling documentation
- `TESTING.md`, `TESTING_GUIDE.md` - General testing documentation

**See [/CLAUDE.md](/CLAUDE.md) for complete project documentation and architecture overview.**
