# Archived Documentation

This directory contains historical documentation from earlier development phases and completed work that has been archived to reduce token usage. These files are preserved for reference but are no longer actively used in day-to-day development.

## Recently Archived (2026-01-08)

### Qualified Name Support - Design Phase Artifacts (Token Savings: ~15K)

Located in `experiments/` and `experiment-scripts/` subdirectories:

- **experiments/LIBCLANG_VALIDATION_EXPERIMENT.md** (8.5K) - Detailed experiment guide for validating libclang assumptions
  - 6 test cases (TC1-TC6) for type alias expansion, template detection
  - Decision points, expected outcomes, validation criteria
  - **Results:** All assumptions validated, documented in QUALIFIED_NAME_DISCUSSION_LOG.md

- **experiments/LIBCLANG_EXPERIMENT_RESULTS_TEMPLATE.md** (4.4K) - Results documentation template
  - Structure for recording experiment findings
  - **Actual results:** Documented in discussion log, template no longer needed

- **experiments/README.md** (2.1K) - Quick start guide for running experiments
  - 40-minute experiment execution plan
  - **Status:** Experiments complete, results validated

- **experiment-scripts/test_libclang_behavior.py** (16.4K) - Automated validation script
  - Tests type alias resolution, template function detection, canonical type handling
  - **Key findings:** TC4 (aliases expanded + qualified), TC5 (cursor.kind detection)
  - **Status:** Validation complete, no longer needed for implementation

**Why archived:**
- Design phase complete - all decisions made (Q1-Q10 resolved)
- Experiments validated critical assumptions (TC4: Q3 works, TC5: F4 works)
- Results documented in `docs/proposals/QUALIFIED_NAME_DISCUSSION_LOG.md`
- Implementation planning phase begins - experiments artifacts no longer needed

**When to reference:**
- Understanding rationale for Q2 (template detection via cursor.kind)
- Understanding rationale for Q3 (canonical type expansion)
- Replicating validation methodology for future features

---

## Previously Archived (2025-12-29)

### Testing Framework Development (Token Savings: ~100K)
- **MCP_TESTING_SKILL.md** (715 lines) - Complete technical specification for /test-mcp skill
  - Architecture, implementation plan, all 5 phases
  - Custom YAML scenarios, project management, server orchestration
  - **Current usage docs:** `../TEST_MCP_USER_GUIDE.md`, `../TEST_MCP_COMMAND_REFERENCE.md`, `../TEST_MCP_FAQ.md`

- **MCP_TESTING_SKILL_STATUS.md** (451 lines) - Phase-by-phase implementation tracking
  - All 5 phases complete (Phase 1-5: MVP, Project Management, Extended Scenarios, Advanced Features, Polish)
  - Detailed progress notes, deliverables, success criteria
  - **Note:** Development complete, skill is production-ready

These documents were moved to archive after completing all 5 phases of /test-mcp skill development. For using the skill, see the user-focused documentation in main docs/ directory.

## Previously Archived (2025-12-25)

### Development Session Documents (Token Savings: ~21K)
Located in `development-sessions-2025/` subdirectory:
- **FIXES_APPLIED.md** (6.6K) - Session persistence & fast cache resume fixes (Dec 14, 2025)
- **INCREMENTAL_ANALYSIS_FIX.md** (5.1K) - Fix for false "9788 files added" after cache load (Dec 14, 2025)
- **TESTING_AUTO_REFRESH_FIX.md** (4.3K) - Auto-refresh testing notes (Dec 14, 2025)
- **TEST_REPORT_FILE_NAME_FILTER.md** (4.7K) - Test report for file_name filter feature (Dec 17, 2025)

These were temporary development session notes documenting specific bug fixes and features. The features are now implemented and tested; keeping these in the root directory was redundant.

### Test Coverage Analysis (Token Savings: ~7K)
- **TEST_COVERAGE_INCREMENTAL_ANALYSIS.md** (7.4K) - Detailed test coverage analysis for incremental analysis feature
  - Maps specific user requirements to test coverage for incremental analysis
  - Documents 77 tests specific to incremental analysis functionality
  - **Current general coverage:** `../TEST_COVERAGE.md` covers all features

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

Archiving these files saves approximately **113K+ tokens** when working with documentation:
- Qualified name support design artifacts (2026-01-08): ~15K tokens
- Testing framework development: ~100K tokens (archived 2025-12-29)
- Development session documents: ~21K tokens
- Test coverage analysis (incremental-specific): ~7K tokens
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

**See [/CLAUDE.md](../../CLAUDE.md) for complete project documentation and architecture overview.**
