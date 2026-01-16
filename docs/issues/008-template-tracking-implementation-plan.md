# Template Information Tracking - Implementation Plan

**Related**: GitHub Issue #85, Beads cplusplus_mcp-2an
**Status**: Planning
**Date**: 2026-01-14

---

## Overview

This document provides a detailed, decomposed implementation plan for template information tracking. Each task is designed to be independently implementable where possible, with clear dependencies marked.

**Key Principles:**
- ✅ Start simple, iterate based on MVP feedback
- ✅ Each task delivers incremental value
- ✅ Clear dependencies to enable parallel work
- ✅ Research points marked for MVP validation

---

## Task Breakdown

### Phase 1: Investigation (Parallel execution possible)

**Goal**: Validate libclang capabilities and design feasibility

#### Task 1.1: libclang Template Detection Research
**Priority**: P2 (must have)
**Effort**: 4-6 hours
**Dependencies**: None
**Deliverable**: Technical report on libclang cursor kinds for templates

**Scope**:
- Research cursor kinds for templates:
  - `CXCursor_FunctionTemplate`
  - `CXCursor_ClassTemplate`
  - `CXCursor_ClassTemplatePartialSpecialization`
- Test detection on sample code
- Document how to distinguish primary vs. specialization
- Verify what metadata is available

**Acceptance Criteria**:
- Report documents all relevant cursor kinds
- Sample code demonstrates detection
- Confirms feasibility of basic detection

---

#### Task 1.2: Template Parameter Extraction Research
**Priority**: P2 (must have)
**Effort**: 4-6 hours
**Dependencies**: None
**Deliverable**: Working prototype for extracting template parameters

**Scope**:
- Research `clang_Cursor_getNumTemplateArguments()`
- Research `clang_Cursor_getTemplateArgumentKind()`
- Test parameter extraction on:
  - Simple: `template<typename T>`
  - Multiple: `template<typename T, typename U>`
  - Non-type: `template<int N>`
  - Variadic: `template<typename... Args>`
  - Defaults: `template<typename T = int>`
- Compare with type alias parameter extraction (PR #125)

**Acceptance Criteria**:
- Prototype extracts parameter names
- Prototype extracts parameter kinds (type/non-type/template)
- Prototype detects variadic parameters
- Prototype detects default arguments (if possible)

**Note**: Reuse code/patterns from type alias tracking where applicable

---

#### Task 1.3: Primary-Specialization Linking Research
**Priority**: P2 (must have)
**Effort**: 6-8 hours
**Dependencies**: None
**Deliverable**: Working approach for linking specializations to primary

**Scope**:
- Research `clang_getSpecializedCursorTemplate()`
- Test on full specializations:
  ```cpp
  template<typename T> void foo(T);
  template<> void foo<int>(int);  // Link to primary
  ```
- Test on partial specializations:
  ```cpp
  template<typename T, typename U> class Pair;
  template<typename T> class Pair<T, T>;  // Link to primary
  ```
- Determine if libclang provides primary USR or requires manual search
- Document edge cases

**Acceptance Criteria**:
- Prototype links full specialization → primary template
- Prototype links partial specialization → primary template
- Documents limitations/edge cases
- Provides fallback strategy if libclang API insufficient

---

#### Task 1.4: Real-World Template Examples Test
**Priority**: P2 (must have)
**Effort**: 3-4 hours
**Dependencies**: 1.1, 1.2, 1.3
**Deliverable**: Test suite with diverse template patterns

**Scope**:
- Create `tests/fixtures/template_examples/` with:
  - Function template + full specialization
  - Class template + partial specialization
  - Variadic template
  - Template with default arguments
  - Nested templates
  - Template in namespace
- Run detection/extraction prototypes on all examples
- Document success/failure for each pattern

**Acceptance Criteria**:
- Test suite covers MVP scope (function/class templates, specializations)
- All examples successfully detected and extracted
- Edge cases documented for future work

---

### Phase 2: Schema Design

**Goal**: Design database schema for template metadata

#### Task 2.1: Design Schema Changes
**Priority**: P2 (must have)
**Effort**: 4-6 hours
**Dependencies**: 1.1, 1.2, 1.3
**Deliverable**: Updated schema.sql with template support

**Scope**:
- Design schema additions to `symbols` table:
  ```sql
  ALTER TABLE symbols ADD COLUMN is_template BOOLEAN DEFAULT 0;
  ALTER TABLE symbols ADD COLUMN template_parameters TEXT DEFAULT NULL;  -- JSON
  ALTER TABLE symbols ADD COLUMN template_kind TEXT DEFAULT NULL;
  ALTER TABLE symbols ADD COLUMN primary_template_usr TEXT DEFAULT NULL;
  ```
- Define JSON format for `template_parameters`:
  ```json
  [
    {"name": "T", "kind": "type", "is_variadic": false},
    {"name": "N", "kind": "non_type", "is_variadic": false},
    {"name": "Args", "kind": "type", "is_variadic": true}
  ]
  ```
- Define `template_kind` values: `"primary"`, `"full_specialization"`, `"partial_specialization"`
- Document schema version bump strategy
- Create index on `primary_template_usr` for reverse lookup

**Acceptance Criteria**:
- Schema documented in schema.sql
- JSON format specification complete
- Migration strategy defined (auto-recreation in dev mode)

**Research Point for MVP**: Evaluate if separate `templates` table would be better after seeing data size

---

#### Task 2.2: Implement Schema Migration
**Priority**: P2 (must have)
**Effort**: 2-3 hours
**Dependencies**: 2.1
**Deliverable**: Schema version bump + auto-recreation logic

**Scope**:
- Update `schema.sql` with new columns
- Bump schema version to v13.0
- Update `CURRENT_SCHEMA_VERSION` in `sqlite_cache_backend.py`
- Test auto-recreation on schema change

**Acceptance Criteria**:
- Schema applies cleanly on fresh database
- Old databases auto-recreate with new schema
- No data loss on schema change (expected in dev mode)

---

### Phase 3: Core Extraction

**Goal**: Extract template metadata from AST during indexing

#### Task 3.1: Extract is_template Flag
**Priority**: P2 (must have)
**Effort**: 3-4 hours
**Dependencies**: 2.1, 1.1
**Deliverable**: is_template detection in _process_cursor()

**Scope**:
- Update `cpp_analyzer.py:_process_cursor()`
- Detect template cursor kinds:
  - `CXCursor_FunctionTemplate`
  - `CXCursor_ClassTemplate`
  - `CXCursor_ClassTemplatePartialSpecialization`
- Set `is_template = True` for template symbols
- Update `SymbolInfo` dataclass with `is_template` field

**Acceptance Criteria**:
- Function templates marked as `is_template=True`
- Class templates marked as `is_template=True`
- Non-template symbols marked as `is_template=False`
- Unit test: detect template vs non-template

**Value**: Enables LLM to distinguish templates from overloads (solves core problem)

---

#### Task 3.2: Extract Template Parameters
**Priority**: P2 (must have)
**Effort**: 6-8 hours
**Dependencies**: 2.1, 1.2, 3.1
**Deliverable**: template_parameters extraction

**Scope**:
- Create `_extract_template_parameters()` helper in `cpp_analyzer.py`
- Extract for each parameter:
  - `name` (string)
  - `kind` (type/non_type/template)
  - `is_variadic` (boolean)
- Return as JSON-serializable list of dicts
- Handle edge cases:
  - Unnamed parameters (e.g., `template<typename>`)
  - Default arguments (extract if available, else omit)
- Update `SymbolInfo` with `template_parameters` field

**Acceptance Criteria**:
- Extracts parameters from `template<typename T>`
- Extracts parameters from `template<typename T, int N>`
- Detects variadic parameters `template<typename... Args>`
- Handles unnamed parameters gracefully
- Unit test: various parameter configurations

**Note**: Can reuse patterns from type alias parameter extraction (PR #125)

---

#### Task 3.3: Detect Template Kind
**Priority**: P2 (must have)
**Effort**: 4-5 hours
**Dependencies**: 2.1, 1.1, 3.1
**Deliverable**: template_kind classification

**Scope**:
- Distinguish cursor kinds:
  - Primary template: `CXCursor_FunctionTemplate`, `CXCursor_ClassTemplate`
  - Full specialization: Check if `clang_getSpecializedCursorTemplate()` returns valid cursor + no template parameters
  - Partial specialization: `CXCursor_ClassTemplatePartialSpecialization`
- Set `template_kind` field:
  - `"primary"` for primary templates
  - `"full_specialization"` for full specs
  - `"partial_specialization"` for partial specs
- Update `SymbolInfo` with `template_kind` field

**Acceptance Criteria**:
- Primary templates classified correctly
- Full specializations classified correctly
- Partial specializations classified correctly
- Unit test: each template kind

---

#### Task 3.4: Link Specializations to Primary
**Priority**: P2 (must have)
**Effort**: 6-8 hours
**Dependencies**: 2.1, 1.3, 3.3
**Deliverable**: primary_template_usr linking

**Scope**:
- Use `clang_getSpecializedCursorTemplate()` to get primary template cursor
- Extract USR from primary template cursor
- Store in `primary_template_usr` field (NULL for primary templates)
- Handle edge cases:
  - Primary not found (log warning, leave NULL)
  - Forward declarations
- Update `SymbolInfo` with `primary_template_usr` field

**Acceptance Criteria**:
- Full specializations linked to primary (USR matches)
- Partial specializations linked to primary (USR matches)
- Primary templates have `primary_template_usr=NULL`
- Unit test: verify linking on sample code

**Value**: Enables finding all specializations of a template

---

#### Task 3.5: (OPTIONAL) Extract Specialization Args for Partial Specs
**Priority**: P3 (research on MVP)
**Effort**: 8-12 hours
**Dependencies**: 2.1, 3.4
**Deliverable**: specialization_args for partial specializations

**Scope**:
- Extract specialization arguments from partial specializations:
  - `template<typename T> class Pair<T, T>` → `["T", "T"]`
  - `template<typename T> class Foo<T*>` → `["T*"]`
- Store as JSON array in `specialization_args` field
- Add schema column (optional, can be NULL)

**Acceptance Criteria**:
- Extracts args from partial specializations
- NULL for primary templates and full specializations
- Unit test: various partial spec patterns

**Research Point**: Evaluate necessity during MVP testing on large-project project

---

### Phase 4: Storage

**Goal**: Store template metadata in SQLite cache

#### Task 4.1: Update SQLite Storage
**Priority**: P2 (must have)
**Effort**: 3-4 hours
**Dependencies**: 2.2, 3.1, 3.2, 3.3, 3.4
**Deliverable**: Store template metadata in database

**Scope**:
- Update `sqlite_cache_backend.py:store_symbol()`
- Store new fields:
  - `is_template`
  - `template_parameters` (JSON string)
  - `template_kind`
  - `primary_template_usr`
- Update `_symbol_from_row()` to deserialize JSON
- Create index on `primary_template_usr`

**Acceptance Criteria**:
- Template metadata persisted to database
- Template metadata retrieved from database correctly
- JSON serialization/deserialization works
- Index created for reverse lookup

---

#### Task 4.2: Update Cache Serialization
**Priority**: P2 (must have)
**Effort**: 2-3 hours
**Dependencies**: 4.1
**Deliverable**: In-memory cache includes template metadata

**Scope**:
- Update `CacheManager` to include template fields
- Update `SymbolInfo` dataclass (already done in 3.x tasks)
- Verify serialization in worker processes

**Acceptance Criteria**:
- Template metadata available in memory after indexing
- Worker processes correctly serialize/deserialize

---

### Phase 5: MCP Tools

**Goal**: Expose template metadata through MCP tools

#### Task 5.1: Update search_functions
**Priority**: P2 (must have)
**Effort**: 2-3 hours
**Dependencies**: 4.2
**Deliverable**: search_functions returns template metadata

**Scope**:
- Update `search_functions` MCP tool response format
- Add fields to JSON response:
  - `is_template` (boolean)
  - `template_parameters` (array, NULL if not template)
  - `template_kind` (string, NULL if not template)
  - `primary_template_usr` (string, NULL if primary or not template)
- Ensure backward compatibility (additive change)

**Acceptance Criteria**:
- Template functions include new fields
- Non-template functions have NULL/false values
- Existing clients continue to work (additive change)
- Documentation updated

---

#### Task 5.2: Update get_function_info
**Priority**: P2 (must have)
**Effort**: 2-3 hours
**Dependencies**: 4.2
**Deliverable**: get_function_info returns template metadata

**Scope**:
- Update `get_function_info` response format
- Same fields as 5.1
- Include in detailed info

**Acceptance Criteria**:
- Detailed function info includes template metadata
- Backward compatible

---

#### Task 5.3: Update search_classes
**Priority**: P2 (must have)
**Effort**: 2-3 hours
**Dependencies**: 4.2
**Deliverable**: search_classes returns template metadata

**Scope**:
- Update `search_classes` response format
- Same fields as 5.1

**Acceptance Criteria**:
- Class templates include metadata
- Backward compatible

---

#### Task 5.4: Update get_class_info
**Priority**: P2 (must have)
**Effort**: 2-3 hours
**Dependencies**: 4.2
**Deliverable**: get_class_info returns template metadata

**Scope**:
- Update `get_class_info` response format
- Same fields as 5.1

**Acceptance Criteria**:
- Detailed class info includes template metadata
- Backward compatible

---

#### Task 5.5: (OPTIONAL) Add get_template_specializations Tool
**Priority**: P3 (research on MVP)
**Effort**: 4-6 hours
**Dependencies**: 4.2
**Deliverable**: New MCP tool to find all specializations

**Scope**:
- Create `get_template_specializations` MCP tool
- Input: USR of primary template (or any specialization)
- Output: List of all related templates (primary + all specializations)
- Query SQLite by `primary_template_usr`
- Handle reverse lookup (if input is specialization, find primary first)

**Acceptance Criteria**:
- Returns all specializations for given primary template
- Returns primary + specializations if given specialization USR
- Efficient SQL query

**Research Point**: Evaluate necessity during MVP testing. May be sufficient to use existing tools with template metadata.

---

#### Task 5.6: (OPTIONAL) Add Reverse Lookup to Existing Tools
**Priority**: P3 (research on MVP)
**Effort**: 3-4 hours
**Dependencies**: 5.5
**Deliverable**: Enhanced search tools with "include_related" flag

**Scope**:
- Add optional parameter to search tools: `include_related_templates=false`
- If true, when finding a specialization, also return primary + other specializations
- Useful for "show me all versions of this function"

**Acceptance Criteria**:
- Optional flag available
- Default behavior unchanged (backward compatible)
- Returns related templates when requested

**Research Point**: Evaluate UX during MVP testing

---

### Phase 6: Testing

**Goal**: Comprehensive test coverage for template tracking

#### Task 6.1: Unit Tests - Template Detection
**Priority**: P2 (must have)
**Effort**: 3-4 hours
**Dependencies**: 3.1, 3.3
**Deliverable**: Tests for is_template and template_kind

**Scope**:
- Test detection of function templates
- Test detection of class templates
- Test classification: primary vs. full_spec vs. partial_spec
- Test non-template symbols (is_template=False)

**Acceptance Criteria**:
- 100% coverage for detection logic
- All template kinds tested

---

#### Task 6.2: Unit Tests - Parameter Extraction
**Priority**: P2 (must have)
**Effort**: 3-4 hours
**Dependencies**: 3.2
**Deliverable**: Tests for template_parameters extraction

**Scope**:
- Test single type parameter: `template<typename T>`
- Test multiple parameters: `template<typename T, int N>`
- Test variadic: `template<typename... Args>`
- Test unnamed parameters: `template<typename>`
- Test edge cases

**Acceptance Criteria**:
- All parameter kinds tested
- Edge cases covered

---

#### Task 6.3: Integration Tests - Function Templates
**Priority**: P2 (must have)
**Effort**: 4-5 hours
**Dependencies**: 4.2, 5.1, 5.2
**Deliverable**: End-to-end tests for function templates

**Scope**:
- Create test fixture with:
  - Primary function template
  - Full specialization
  - Multiple specializations
- Index project
- Query with search_functions
- Verify template metadata in response
- Verify linking (primary_template_usr)

**Acceptance Criteria**:
- Full workflow tested (index → query → verify)
- Template metadata correct
- Linking verified

---

#### Task 6.4: Integration Tests - Class Templates
**Priority**: P2 (must have)
**Effort**: 4-5 hours
**Dependencies**: 4.2, 5.3, 5.4
**Deliverable**: End-to-end tests for class templates

**Scope**:
- Create test fixture with:
  - Primary class template
  - Partial specialization
  - Full specialization
- Index project
- Query with search_classes
- Verify template metadata

**Acceptance Criteria**:
- Class templates tested end-to-end
- Partial specializations detected and linked

---

#### Task 6.5: Integration Tests - Specialization Linking
**Priority**: P2 (must have)
**Effort**: 4-5 hours
**Dependencies**: 6.3, 6.4
**Deliverable**: Tests for primary-specialization relationships

**Scope**:
- Test finding primary from specialization
- Test finding all specializations from primary
- Test with nested namespaces
- Test with forward declarations

**Acceptance Criteria**:
- Linking verified in all scenarios
- Edge cases handled

---

#### Task 6.6: Performance Tests - Large Codebase
**Priority**: P3 (should have)
**Effort**: 4-6 hours
**Dependencies**: 6.3, 6.4, 6.5
**Deliverable**: Performance benchmarks

**Scope**:
- Test on large-project project (~5700 files)
- Measure indexing time impact
- Measure query time impact
- Measure cache size increase

**Acceptance Criteria**:
- < 10% indexing time increase
- < 5% query time increase
- Cache size impact documented

**Research Point**: Identify optimization opportunities

---

### Phase 7: MVP Validation

**Goal**: Validate design decisions on real-world codebase

#### Task 7.1: Test on large-project Project
**Priority**: P2 (must have)
**Effort**: 4-6 hours
**Dependencies**: 6.6
**Deliverable**: Real-world validation report

**Scope**:
- Index large-project project with template tracking
- Test template detection on real code
- Verify template metadata quality
- Document issues found
- Gather usage patterns

**Acceptance Criteria**:
- Successfully indexes large-project project
- Template metadata extracted for real templates
- Issues documented
- Recommendations for improvements

---

#### Task 7.2: Evaluate specialization_args Necessity
**Priority**: P3 (research)
**Effort**: 2-3 hours
**Dependencies**: 7.1
**Deliverable**: Decision on Task 3.5 priority

**Scope**:
- Review large-project usage of partial specializations
- Assess if `specialization_args` provides value
- Compare: with args vs. reading source file
- Document use cases where it's critical

**Acceptance Criteria**:
- Decision: implement now / defer to v2 / skip
- Rationale documented

---

#### Task 7.3: Evaluate Reverse Lookup Tool Necessity
**Priority**: P3 (research)
**Effort**: 2-3 hours
**Dependencies**: 7.1
**Deliverable**: Decision on Task 5.5/5.6 priority

**Scope**:
- Test workflows with existing tools + template metadata
- Assess if dedicated tool adds value
- Consider: query by primary_template_usr vs. dedicated tool
- Document user workflows

**Acceptance Criteria**:
- Decision: implement get_template_specializations / enhance existing / skip
- Rationale documented

---

## Dependency Graph

```
Phase 1: Investigation (parallel)
├── 1.1: Template Detection Research
├── 1.2: Parameter Extraction Research
├── 1.3: Primary Linking Research
└── 1.4: Real-World Examples ← (1.1, 1.2, 1.3)

Phase 2: Schema
├── 2.1: Design Schema ← (1.1, 1.2, 1.3)
└── 2.2: Implement Migration ← (2.1)

Phase 3: Extraction (some parallel)
├── 3.1: is_template Flag ← (2.1, 1.1)
├── 3.2: Template Parameters ← (2.1, 1.2, 3.1)
├── 3.3: Template Kind ← (2.1, 1.1, 3.1)
├── 3.4: Primary Linking ← (2.1, 1.3, 3.3)
└── 3.5: [OPTIONAL] Specialization Args ← (2.1, 3.4)

Phase 4: Storage
├── 4.1: SQLite Storage ← (2.2, 3.1, 3.2, 3.3, 3.4)
└── 4.2: Cache Serialization ← (4.1)

Phase 5: MCP Tools (parallel)
├── 5.1: search_functions ← (4.2)
├── 5.2: get_function_info ← (4.2)
├── 5.3: search_classes ← (4.2)
├── 5.4: get_class_info ← (4.2)
├── 5.5: [OPTIONAL] get_template_specializations ← (4.2)
└── 5.6: [OPTIONAL] Reverse Lookup ← (5.5)

Phase 6: Testing (some parallel)
├── 6.1: Unit - Detection ← (3.1, 3.3)
├── 6.2: Unit - Parameters ← (3.2)
├── 6.3: Integration - Functions ← (4.2, 5.1, 5.2)
├── 6.4: Integration - Classes ← (4.2, 5.3, 5.4)
├── 6.5: Integration - Linking ← (6.3, 6.4)
└── 6.6: Performance ← (6.3, 6.4, 6.5)

Phase 7: MVP Validation
├── 7.1: Test on large-project ← (6.6)
├── 7.2: Evaluate specialization_args ← (7.1)
└── 7.3: Evaluate reverse lookup tool ← (7.1)
```

---

## Recommended Execution Order

### Iteration 1: Core MVP (Minimum Viable Product)
**Goal**: Get basic template tracking working end-to-end

1. ✅ 1.1: Template Detection Research
2. ✅ 1.2: Parameter Extraction Research
3. ✅ 1.3: Primary Linking Research
4. ✅ 1.4: Real-World Examples
5. ✅ 2.1: Design Schema
6. ✅ 2.2: Implement Migration
7. ✅ 3.1: is_template Flag
8. ✅ 3.2: Template Parameters
9. ✅ 3.3: Template Kind
10. ✅ 3.4: Primary Linking
11. ✅ 4.1: SQLite Storage
12. ✅ 4.2: Cache Serialization
13. ✅ 5.1: search_functions
14. ✅ 5.2: get_function_info
15. ✅ 6.1: Unit - Detection
16. ✅ 6.2: Unit - Parameters
17. ✅ 6.3: Integration - Functions

**Milestone**: Can detect and query function templates with metadata

### Iteration 2: Class Templates
**Goal**: Add class template support

18. ✅ 5.3: search_classes
19. ✅ 5.4: get_class_info
20. ✅ 6.4: Integration - Classes
21. ✅ 6.5: Integration - Linking

**Milestone**: Can detect and query class templates with metadata

### Iteration 3: Real-World Validation
**Goal**: Test on large-project project, gather insights

22. ✅ 6.6: Performance
23. ✅ 7.1: Test on large-project
24. ✅ 7.2: Evaluate specialization_args
25. ✅ 7.3: Evaluate reverse lookup tool

**Milestone**: Validated on real codebase, decisions made on optional features

### Iteration 4: Optional Enhancements (Based on Validation)
**Goal**: Add features identified as valuable during MVP

26. ⚠️ 3.5: Specialization Args (if 7.2 says yes)
27. ⚠️ 5.5: get_template_specializations (if 7.3 says yes)
28. ⚠️ 5.6: Reverse Lookup (if 7.3 says yes)

**Milestone**: Full feature set based on real-world needs

---

## Priority Legend

- **P2 (Must Have)**: Core MVP functionality
- **P3 (Should Have)**: Valuable but can defer
- **P3 (Research)**: Decision point after MVP validation
- **⚠️ Optional**: Implement only if MVP validation confirms value

---

## Effort Estimates

**Total for Iteration 1 (Core MVP)**: ~60-75 hours
**Total for Iteration 2 (Class Templates)**: ~15-20 hours
**Total for Iteration 3 (Validation)**: ~10-15 hours
**Total for Iteration 4 (Optional)**: ~15-25 hours (if all implemented)

**Total Project**: 100-135 hours (depending on optional features)

---

## Success Criteria

**MVP Success**:
- ✅ LLM can distinguish templates from overloads
- ✅ LLM can see template parameters
- ✅ LLM can identify specializations
- ✅ Specializations linked to primary templates
- ✅ < 10% performance impact on indexing
- ✅ Works on large-project project

**Full Success**:
- All MVP criteria +
- Optional features implemented if validated as valuable
- Comprehensive test coverage
- Documentation complete

---

## Next Steps

1. **Review this plan** with stakeholder
2. **Create beads issues** for each task
3. **Set dependencies** in beads
4. **Start with Iteration 1** (Investigation phase)
5. **Iterate based on MVP feedback**

---

## Notes

- Tasks can be worked on in parallel where dependencies allow
- Each task is small enough to complete in 1-2 work sessions
- Research points ensure we don't over-engineer
- MVP validation prevents scope creep
- Clear milestones enable progress tracking
