# Development Workflow for Test Implementation

## Document Overview

**Purpose**: Define the standard workflow for implementing and tracking tests in the Clang Index MCP project
**Audience**: Contributors working on test implementation
**Created**: 2025-11-14
**Last Updated**: 2025-11-14

---

## Table of Contents

- [Core Workflow Principle](#core-workflow-principle)
- [Per-Item Workflow](#per-item-workflow)
- [Commit Message Guidelines](#commit-message-guidelines)
- [Branch Strategy](#branch-strategy)
- [Workflow Examples](#workflow-examples)
- [Common Scenarios](#common-scenarios)
- [Checklist Update Rules](#checklist-update-rules)
- [Quality Gates](#quality-gates)

---

## Core Workflow Principle

**Every checklist item completion must be tracked in git history.**

This ensures:
- ✅ Clear progress tracking
- ✅ Easy rollback if needed
- ✅ Granular git history
- ✅ Transparent work visibility
- ✅ Resumability after interruptions

---

## Per-Item Workflow

### Standard 4-Step Process

For **each checklist item**, follow these steps in order:

```
1. Implement → 2. Commit Implementation → 3. Update Checklist → 4. Commit Checklist → 5. Push
```

#### Step 1: Implement the Task
- Write the test file
- Ensure code follows project conventions
- Add appropriate pytest markers
- Include docstrings and comments

#### Step 2: Commit the Implementation
```bash
# Add the implementation files
git add <test-file-path>

# Commit with descriptive message
git commit -m "<Implementation commit message>"
```

#### Step 3: Update the Checklist
- Open `TEST_IMPLEMENTATION_CHECKLIST.md`
- Change `[ ]` to `[x]` for the completed item
- Add notes about what was implemented
- Update timestamps if needed

#### Step 4: Commit the Checklist Update
```bash
# Add the checklist file
git add TEST_IMPLEMENTATION_CHECKLIST.md

# Commit with clear message
git commit -m "Mark task <X.X.X> complete in checklist"
```

#### Step 5: Push to Remote
```bash
# Push both commits
git push -u origin <branch-name>
```

---

## Commit Message Guidelines

### Implementation Commits

Format: `<Action> <component> - <requirement-id>`

**Examples:**
```bash
git commit -m "Implement test_project_indexing.py - REQ-1.1"
git commit -m "Add test_class_extraction.py with 8 test cases - REQ-2.1"
git commit -m "Implement security tests for path traversal - REQ-10.1"
git commit -m "Fix test_search_functions.py - Handle empty results"
```

**Components:**
- Use descriptive action verbs: `Implement`, `Add`, `Fix`, `Update`, `Refactor`
- Include file name or feature being worked on
- Reference requirement ID when applicable
- Keep under 72 characters for summary line

### Checklist Update Commits

Format: `Mark task <X.X.X> complete in checklist`

**Examples:**
```bash
git commit -m "Mark task 1.1.1 complete in checklist"
git commit -m "Mark task 1.2.5 complete in checklist"
git commit -m "Update Phase 1.3 progress - 4/6 tasks complete"
```

### Multi-Item Commits (Exceptions)

When multiple small related items are completed together:

```bash
git commit -m "Implement all MCP tool validation tests - REQ-4.x

- Add test_list_classes_validation.py
- Add test_search_functions_validation.py
- Add test_get_call_graph_validation.py
All tests follow standard validation pattern."
```

Then update checklist:
```bash
git commit -m "Mark tasks 1.4.1-1.4.3 complete in checklist"
```

---

## Branch Strategy

### Development Branch

All work happens on: `claude/review-test-plan-01NiY3GieEhzgcSvANCawmoL`

```bash
# Always verify you're on the correct branch
git branch --show-current

# If not on the correct branch
git checkout claude/review-test-plan-01NiY3GieEhzgcSvANCawmoL
```

### Pushing Rules

```bash
# Always use -u flag for first push of a session
git push -u origin claude/review-test-plan-01NiY3GieEhzgcSvANCawmoL

# For subsequent pushes in the same session
git push
```

**CRITICAL**: Branch must start with `claude/` and end with session ID, otherwise push will fail with 403.

### Network Retry Strategy

If push/pull fails due to network errors:
- Retry up to 4 times with exponential backoff: 2s, 4s, 8s, 16s
- Example: try push → wait 2s → retry → wait 4s → retry → etc.

---

## Workflow Examples

### Example 1: Simple Test Implementation

```bash
# Step 1: Implement test
vim tests/base_functionality/test_project_indexing.py
# Write test functions...

# Step 2: Commit implementation
git add tests/base_functionality/test_project_indexing.py
git commit -m "Implement test_project_indexing.py - REQ-1.1

- Add test_index_single_file()
- Add test_index_multiple_files()
- Add test_index_with_subdirectories()
- Add test_incremental_indexing()
All tests use indexed_analyzer fixture."

# Step 3: Update checklist
vim TEST_IMPLEMENTATION_CHECKLIST.md
# Change [ ] to [x] for task 1.1.1
# Add notes: "Implemented 4 test cases for project indexing"

# Step 4: Commit checklist update
git add TEST_IMPLEMENTATION_CHECKLIST.md
git commit -m "Mark task 1.1.1 complete in checklist"

# Step 5: Push
git push
```

### Example 2: Test Implementation with Bug Fix

```bash
# Step 1: Implement test
vim tests/security/test_path_traversal.py
# Write security tests...

# Step 2: Commit implementation
git add tests/security/test_path_traversal.py
git commit -m "Implement test_path_traversal.py - REQ-10.1"

# Step 3: Update checklist
vim TEST_IMPLEMENTATION_CHECKLIST.md
# Change [ ] to [x] for task 3.1.1

# Step 4: Commit checklist
git add TEST_IMPLEMENTATION_CHECKLIST.md
git commit -m "Mark task 3.1.1 complete in checklist"

# Step 5: Push
git push

# Later: Discover bug in test
vim tests/security/test_path_traversal.py
# Fix the bug...

# Commit the fix separately
git add tests/security/test_path_traversal.py
git commit -m "Fix test_path_traversal.py - Handle Windows path separators"

# Push the fix
git push
```

### Example 3: Multiple Related Tests

```bash
# Step 1: Implement all related tests
vim tests/base_functionality/test_class_search.py
vim tests/base_functionality/test_function_search.py
vim tests/base_functionality/test_namespace_search.py

# Step 2: Commit all together (related functionality)
git add tests/base_functionality/test_*_search.py
git commit -m "Implement all search functionality tests - REQ-2.x

- test_class_search.py: 6 test cases
- test_function_search.py: 5 test cases
- test_namespace_search.py: 4 test cases
Total: 15 test functions covering all search operations."

# Step 3: Update checklist
vim TEST_IMPLEMENTATION_CHECKLIST.md
# Mark tasks 1.2.1, 1.2.2, 1.2.3 as complete

# Step 4: Commit checklist
git add TEST_IMPLEMENTATION_CHECKLIST.md
git commit -m "Mark tasks 1.2.1-1.2.3 complete in checklist"

# Step 5: Push
git push
```

---

## Common Scenarios

### Scenario 1: Forgot to Update Checklist

```bash
# You committed implementation but forgot checklist update
git log -1  # Shows: "Implement test_foo.py"

# Update checklist now
vim TEST_IMPLEMENTATION_CHECKLIST.md
# Mark task complete

# Commit checklist update
git add TEST_IMPLEMENTATION_CHECKLIST.md
git commit -m "Mark task X.X.X complete in checklist (missed in previous commit)"
git push
```

### Scenario 2: Need to Revise Implementation

```bash
# Original implementation
git commit -m "Implement test_bar.py - REQ-5.1"
git commit -m "Mark task 5.1.1 complete in checklist"
git push

# Realize changes needed
vim tests/test_bar.py
# Make improvements...

# Commit revision
git add tests/test_bar.py
git commit -m "Refactor test_bar.py - Add edge case coverage"
git push

# No need to update checklist again (task still complete)
```

### Scenario 3: Blocked on External Dependency

```bash
# Can't complete task due to blocker
vim TEST_IMPLEMENTATION_CHECKLIST.md
# Change [ ] to [!] for blocked task
# Add notes: "Blocked: Waiting for CppAnalyzer.get_call_graph() implementation"

# Commit checklist update
git add TEST_IMPLEMENTATION_CHECKLIST.md
git commit -m "Mark task X.X.X as blocked - Missing dependency"
git push

# Later, when unblocked
vim TEST_IMPLEMENTATION_CHECKLIST.md
# Change [!] to [~] (in progress)
git commit -m "Unblock task X.X.X - Dependency now available"

# Implement
vim tests/test_foo.py
git add tests/test_foo.py
git commit -m "Implement test_foo.py - REQ-X.X"

# Mark complete
vim TEST_IMPLEMENTATION_CHECKLIST.md
# Change [~] to [x]
git commit -m "Mark task X.X.X complete in checklist"
git push
```

---

## Checklist Update Rules

### Status Transitions

Valid status transitions:
```
[ ] → [~] → [x]  (Normal flow)
[ ] → [!]        (Blocked)
[!] → [~] → [x]  (Unblocked)
[ ] → [?]        (Needs review)
[?] → [x]        (Reviewed and approved)
```

### What to Include in Notes

When updating checklist, add notes with:
- **Implementation details**: "Implemented 5 test cases covering X, Y, Z"
- **File references**: "Created test_foo.py with 3 test functions"
- **Blockers**: "Blocked: Needs clarification on requirement REQ-X.X"
- **Issues found**: "Found issue: Test fails on Windows, needs investigation"
- **Time spent**: "Estimated: 2h, Actual: 3h"
- **Dependencies**: "Depends on task 1.2.1 completion"

### When to Update Progress Summary Table

Update the Progress Summary table after completing:
- All tasks in a phase
- Every 5 tasks
- End of each work session

---

## Quality Gates

### Before Committing Implementation

✅ Code follows project style (PEP 8)
✅ Appropriate pytest markers applied
✅ Docstrings added to test functions
✅ Imports organized correctly
✅ No syntax errors (basic validation)

**Note**: Tests don't need to pass yet in Phase 1 (we're just writing them).

### Before Committing Checklist Update

✅ Correct task marked complete
✅ Notes added explaining what was done
✅ Status indicator correct
✅ Timestamp updated if needed

### Before Pushing

✅ On correct branch (`claude/review-test-plan-*`)
✅ Both commits present (implementation + checklist)
✅ Commit messages follow guidelines
✅ No untracked files that should be committed

---

## Automation Opportunities

### Future Enhancements

Consider adding scripts for:
1. **Auto-checklist validation**: Verify workflow was followed
2. **Pre-commit hooks**: Remind to update checklist
3. **Status dashboard**: Visualize progress from checklist
4. **Time tracking**: Log actual vs estimated time

---

## Questions or Issues?

If you encounter workflow issues:

1. **Check git status**: `git status`
2. **Review recent commits**: `git log -5 --oneline`
3. **Verify branch**: `git branch --show-current`
4. **Check unpushed commits**: `git log origin/$(git branch --show-current)..HEAD`

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────┐
│ Per-Item Workflow (DO THIS FOR EVERY TASK)         │
├─────────────────────────────────────────────────────┤
│ 1. Implement the task                               │
│ 2. git add <files> && git commit -m "Implement..." │
│ 3. Edit TEST_IMPLEMENTATION_CHECKLIST.md           │
│ 4. git add TEST_IMPLEMENTATION_CHECKLIST.md        │
│ 5. git commit -m "Mark task X.X.X complete"        │
│ 6. git push                                         │
└─────────────────────────────────────────────────────┘
```

---

**Last Updated**: 2025-11-14
**Version**: 1.0
**Maintained By**: Clang Index MCP Project Contributors
