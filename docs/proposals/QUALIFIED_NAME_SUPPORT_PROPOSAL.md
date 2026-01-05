# Proposal: Qualified Name Addressing for C++ Symbols

**Status:** 🟡 Draft - Awaiting Discussion
**Created:** 2026-01-05
**Author:** System Analysis (based on manual testing observations)
**Related Issues:** #98, #100, #102, #85, #99, #101

---

## Executive Summary

### Problem Statement

The current MCP server implementation uses **unqualified names** for symbol identification (e.g., `"View"` instead of `"ns1::View"`). This design choice, inherited from the original fork, creates critical issues in large C++ codebases:

1. **Ambiguity:** Multiple symbols with same unqualified name (e.g., `ns1::View`, `ns2::View`) cannot be distinguished
2. **Search failures:** Qualified name patterns (e.g., `"ns2::View"`) return empty results
3. **LLM errors:** Lightweight models frequently pick wrong symbol from ambiguous results
4. **Template complications:** Template specializations cannot be precisely identified

**Testing evidence:** Manual testing on ~5700 file codebase revealed these issues cause **incorrect analysis chains** and require **extensive system prompt workarounds**.

### Proposed Solution

Implement comprehensive **qualified name support** across all MCP tools:

- **Store** fully qualified names during indexing (using libclang APIs)
- **Accept** qualified, partially qualified, and unqualified patterns
- **Disambiguate** results using namespace information
- **Maintain** backward compatibility through dual-mode operation

### Impact Assessment

**Benefits:**
- ✅ Eliminates namespace ambiguity (solves Issues #98, #100, #102)
- ✅ Enables precise symbol identification in large codebases
- ✅ Reduces LLM errors and system prompt complexity
- ✅ Aligns with C++ semantics and developer expectations
- ✅ Foundation for template support (#85, #99, #101)

**Costs:**
- ⚠️ 6-8 weeks implementation effort (3 phases)
- ⚠️ SQLite schema changes (cache invalidation)
- ⚠️ API surface area increase (new parameters)
- ⚠️ Pattern matching complexity

**Risks:**
- 🔴 Breaking changes if not carefully managed
- 🟡 Performance impact on pattern matching
- 🟡 Design complexity for partial qualification rules

### Implementation Roadmap

**Phase 1 (2-3 weeks):** Foundation - Store and return qualified names
**Phase 2 (1-2 weeks):** Qualified Search - Accept qualified patterns
**Phase 3 (2-3 weeks):** Advanced Features - Namespace filtering, templates

**Total estimated effort:** 6-8 weeks

---

## Background

### Project History

**Original fork characteristics:**
- Simplified codebase representation (tree-sitter-like approach)
- Focus on rapid prototyping over precision
- Unqualified name model for symbol identification
- Assumption: Small to medium codebases, limited namespace usage

**Current state (MVP):**
- Inherited unqualified name approach
- Uses libclang for parsing (capable of full qualification)
- Successfully tested on small projects
- **Critical issues revealed on large codebase (5700+ files)**

### Why This Matters Now

**Large project characteristics:**
1. **Name collisions:** Hundreds of symbols with same unqualified name across namespaces
2. **Overload proliferation:** Dozens of overloaded functions per name
3. **Intensive aliasing:** `using` and `typedef` at multiple levels
4. **Template complexity:** Partial/full specializations with different implementations

**Without qualified name support:**
- Users cannot specify which symbol they mean
- LLMs guess incorrectly, leading to wrong analysis paths
- System prompts grow complex with disambiguation logic
- Template-based architectures become opaque

**With libclang:**
- We have precise symbol information (USR, qualified names, namespaces)
- Not using it is leaving value on the table
- Other tools (clangd, clang-tidy) leverage this precision

### Related Issues

This proposal directly addresses:

- **Issue #98:** Support Qualified Names in Search Tools
- **Issue #100:** Namespace Filtering and Disambiguation (HIGH priority)
- **Issue #102:** Template Arguments Use Unqualified Names (bug)

This proposal is foundational for:

- **Issue #85:** Template Information Tracking
- **Issue #99:** Template Class Search and Specialization Discovery
- **Issue #101:** Template-Based Transitive Inheritance Detection

---

## Requirements

### User Requirements

#### UR1: Search by Fully Qualified Name
**Priority:** HIGH
**Description:** User can search using complete qualified name to get exact symbol

**Example:**
```json
search_classes({"pattern": "myapp::ui::View"})
// Returns: Only myapp::ui::View (not other Views)
```

**Success criteria:** Zero ambiguity, exact match on qualified name

---

#### UR2: Disambiguate Namespace Conflicts
**Priority:** HIGH
**Description:** When multiple symbols share unqualified name, user can distinguish them

**Example:**
```cpp
namespace ns1 { class Config { }; }
namespace ns2 { class Config { }; }
```

```json
// Current: Ambiguous - returns both
search_classes({"pattern": "Config"})

// Proposed: Clear specification
search_classes({"pattern": "ns1::Config"})  // Only ns1
search_classes({"pattern": "Config", "namespace": "ns1"})  // Alternative
```

**Success criteria:** User can unambiguously select desired symbol

---

#### UR3: Backward Compatibility
**Priority:** CRITICAL
**Description:** Existing unqualified searches continue to work without changes

**Example:**
```json
// Must continue to work as before
search_classes({"pattern": "View"})
// Returns: All Views (with qualified_name shown for disambiguation)
```

**Success criteria:** Zero breaking changes for existing clients/LLMs

---

#### UR4: Partially Qualified Matching
**Priority:** MEDIUM
**Description:** User can specify partial qualification for convenience

**Example:**
```cpp
namespace company {
  namespace project1 { namespace ui { class View {}; } }
  namespace project2 { namespace ui { class View {}; } }
}
```

```json
// Partially qualified: matches suffix
search_classes({"pattern": "ui::View"})
// Returns: Both project1::ui::View and project2::ui::View
```

**Success criteria:** Intuitive suffix matching behavior

---

#### UR5: Template Specialization Identification
**Priority:** MEDIUM (foundational for #99, #101)
**Description:** Templates can be identified with qualified argument types

**Example:**
```cpp
namespace ns1 { class Foo {}; }
namespace ns2 { class Foo {}; }

template<typename T> class Container {};
```

```json
// Unambiguous specialization reference
get_class_info({"class_name": "Container<ns1::Foo>"})
// Not: "Container<Foo>" (ambiguous!)
```

**Success criteria:** Template arguments use qualified names (fixes #102)

---

### LLM Requirements

#### LR1: Consistent Qualified Names in Results
**Priority:** HIGH
**Description:** All tool results prominently display qualified names

**Current problem:**
```json
// Ambiguous result:
{"name": "View", ...}
// Which View?
```

**Proposed:**
```json
{
  "name": "View",
  "qualified_name": "myapp::ui::View",  // Prominent!
  "namespace": "myapp::ui",
  ...
}
```

**Success criteria:** LLM can extract qualified name without ambiguity

---

#### LR2: Disambiguation Hints
**Priority:** MEDIUM
**Description:** When ambiguous, tool provides helpful hints

**Example:**
```json
// If search returns multiple matches:
{
  "data": [
    {"name": "View", "qualified_name": "ns1::View", ...},
    {"name": "View", "qualified_name": "ns2::View", ...}
  ],
  "metadata": {
    "warning": "Multiple symbols found. Use qualified name for precision.",
    "suggestion": "Try: search_classes({\"pattern\": \"ns1::View\"})"
  }
}
```

**Success criteria:** LLM learns to use qualified names through hints

---

#### LR3: Intuitive Pattern Matching
**Priority:** HIGH
**Description:** Pattern syntax is natural and predictable

**Expected behaviors:**
- `"View"` → all Views (unqualified)
- `"ns::View"` → Views in namespace ns (qualified)
- `".*::View"` → regex matching (all Views in any namespace)
- `"View.*"` → classes starting with View

**Success criteria:** No surprising edge cases, documented clearly

---

### System Requirements

#### SR1: Performance
**Priority:** HIGH
**Description:** Qualified name matching does not degrade search performance significantly

**Targets:**
- Search latency: < 50ms for 100K symbols (currently ~2-5ms)
- Indexing time: < 10% increase
- SQLite size: < 20% increase

**Success criteria:** Acceptable performance on large codebases

---

#### SR2: Storage Efficiency
**Priority:** MEDIUM
**Description:** Store qualified name information without excessive overhead

**Considerations:**
- Qualified names can be long: `company::product::module::submodule::Class`
- Namespace duplication across symbols
- FTS5 index size

**Success criteria:** Storage increase proportional to qualified name length

---

#### SR3: Backward Compatibility
**Priority:** CRITICAL
**Description:** No breaking changes to existing API contracts

**Requirements:**
- Existing tool calls work identically
- Results include new fields (non-breaking addition)
- Optional parameters (not required)

**Success criteria:** Pass all existing tests without modification

---

## Use Cases

### UC1: Search in Specific Namespace
**Actor:** User (via LLM)
**Goal:** Find all classes in `myapp::core` namespace

**Current workflow:**
1. `search_classes({"pattern": ".*"})` → returns thousands
2. Manual filtering by namespace in results → tedious

**Proposed workflow:**
```json
search_classes({
  "pattern": "",  // All classes
  "namespace": "myapp::core"
})
```

**Benefit:** Direct namespace scoping, no post-filtering

---

### UC2: Disambiguate Symbol References
**Actor:** LLM analyzing code
**Goal:** Understand which `Config` class is used

**Current workflow:**
1. User: "Analyze how `Config` is used in startup.cpp"
2. LLM: `search_classes({"pattern": "Config"})` → 5 matches
3. LLM picks first → **WRONG ONE** (common with lightweight models)
4. Analysis proceeds with incorrect class → invalid conclusions

**Proposed workflow:**
1. User: "Analyze how `app::Config` is used" (qualified in request)
2. LLM: `search_classes({"pattern": "app::Config"})` → 1 match
3. Correct class analyzed

**Alternative workflow:**
1. User: "Analyze Config" (still ambiguous)
2. LLM: `search_classes({"pattern": "Config"})` → 5 matches with qualified names
3. LLM: Asks user "Which Config? app::Config, test::Config, prod::Config..."
4. User clarifies → LLM searches with qualified name

**Benefit:** Reduced errors, correct analysis

---

### UC3: Template Specialization Identification
**Actor:** Developer using MCP tools directly
**Goal:** Find which classes derive from `Container<int>`

**Current workflow:**
```json
get_derived_classes({"class_name": "Container<int>"})
// Works, but template arg types are unqualified (Issue #102)
// Result ambiguous if multiple namespaces have `int` aliases
```

**Proposed workflow:**
```json
get_derived_classes({"class_name": "Container<std::int32_t>"})
// Qualified template arg → precise
```

**Benefit:** Unambiguous template specialization references

---

### UC4: Cross-Namespace Analysis
**Actor:** LLM performing architectural analysis
**Goal:** Compare implementations across namespaces

**Scenario:**
```cpp
namespace dev { class Database { void connect(); }; }
namespace prod { class Database { void connect(); }; }
```

**Workflow:**
```json
// Get both implementations
search_classes({"pattern": "Database"})
// Returns: [{"qualified_name": "dev::Database", ...},
//           {"qualified_name": "prod::Database", ...}]

// Analyze each separately
get_class_info({"class_name": "dev::Database"})
get_class_info({"class_name": "prod::Database"})
```

**Benefit:** Parallel analysis of similar symbols in different contexts

---

### UC5: Refactoring Impact Analysis
**Actor:** Developer planning refactoring
**Goal:** Identify all code depending on `legacy::Api`

**Workflow:**
```json
// Find the class
get_class_info({"class_name": "legacy::Api"})

// Find all derived classes (only in legacy namespace)
get_derived_classes({"class_name": "legacy::Api"})

// Find all callers (qualified function names)
find_callers({"function_name": "legacy::Api::execute"})
```

**Benefit:** Precise scoping of refactoring impact

---

## Design

### Data Model

#### Current Schema (Simplified)
```sql
CREATE TABLE symbols (
  usr TEXT PRIMARY KEY,
  name TEXT,              -- "View" (unqualified)
  kind TEXT,              -- "class", "function"
  file_path TEXT,
  ...
);

CREATE VIRTUAL TABLE symbols_fts USING fts5(
  name,                   -- Indexed for search
  ...
);
```

**Problems:**
- No `qualified_name` storage
- No `namespace` column
- FTS5 only indexes unqualified names

---

#### Proposed Schema (Option A: Monolithic)
```sql
CREATE TABLE symbols (
  usr TEXT PRIMARY KEY,
  name TEXT,              -- "View" (unqualified)
  qualified_name TEXT,    -- "ns1::ui::View" (fully qualified)
  namespace TEXT,         -- "ns1::ui" (parent namespace)
  kind TEXT,
  file_path TEXT,
  ...
);

CREATE VIRTUAL TABLE symbols_fts USING fts5(
  name,                   -- Unqualified search
  qualified_name,         -- Qualified search
  content='symbols',
  content_rowid='rowid'
);

CREATE INDEX idx_symbols_namespace ON symbols(namespace);
CREATE INDEX idx_symbols_qualified_name ON symbols(qualified_name);
```

**Pros:**
- Simple schema
- Straightforward queries
- FTS5 indexes both qualified and unqualified

**Cons:**
- Storage duplication (qualified name contains namespace + name)
- Parsing required for partial matching

---

#### Proposed Schema (Option B: Component-Based)
```sql
CREATE TABLE symbols (
  usr TEXT PRIMARY KEY,
  name TEXT,              -- "View"
  namespace_path TEXT,    -- "ns1::ui" or JSON ["ns1", "ui"]
  parent_usr TEXT,        -- USR of enclosing class/namespace
  kind TEXT,
  file_path TEXT,
  ...
);

-- Computed column or view for qualified_name
CREATE VIEW symbols_qualified AS
SELECT
  *,
  CASE
    WHEN namespace_path = '' THEN name
    ELSE namespace_path || '::' || name
  END AS qualified_name
FROM symbols;

CREATE VIRTUAL TABLE symbols_fts USING fts5(
  name,
  qualified_name,
  content='symbols_qualified',
  ...
);
```

**Pros:**
- Structured data (easier for complex queries)
- Can query namespace hierarchy
- Less duplication

**Cons:**
- More complex schema
- View or computed column overhead
- JSON parsing if using JSON for namespace_path

---

#### Recommendation: **Option A (Monolithic) for v1**

**Rationale:**
- Simpler implementation
- libclang provides qualified_name directly
- Storage overhead acceptable (qualified names typically < 200 chars)
- Can migrate to component-based later if needed

**Migration from current:**
- Add columns: `qualified_name TEXT`, `namespace TEXT`
- Populate during indexing (libclang APIs)
- Update FTS5 to include qualified_name
- Increment schema version → auto-recreation

---

### API Design

#### Pattern Matching Rules

**Principle:** Auto-detect pattern type based on syntax

**Detection logic:**
```python
def detect_pattern_mode(pattern: str) -> str:
    if '::' in pattern:
        return 'qualified'
    elif any(c in pattern for c in r'.*+?[]{}()|^$\\'):
        return 'regex'
    else:
        return 'unqualified'
```

**Matching behaviors:**

| Pattern | Mode | Matches | Example |
|---------|------|---------|---------|
| `"View"` | unqualified | All symbols named View | `ns1::View`, `ns2::View`, `::View` |
| `"ns1::View"` | qualified | Exact or suffix match | `ns1::View`, `app::ns1::View` |
| `".*::View"` | regex | Regex on qualified_name | Any View in any namespace |
| `"View.*"` | regex | Regex on name | `View`, `ViewManager`, `ListView` |

**Partial qualification:**
- `"ui::View"` matches `app::ui::View`, `legacy::ui::View` (suffix matching)
- `"::View"` matches only global namespace `::View` (absolute reference)

---

#### Backward Compatibility Strategy

**Option A: Dual Mode (RECOMMENDED)**

**Implementation:**
- All tools accept both qualified and unqualified patterns
- Auto-detection based on `::` presence
- No breaking changes

**Example:**
```json
// Works exactly as before:
search_classes({"pattern": "View"})

// New capability:
search_classes({"pattern": "ns1::View"})

// Both return results with qualified_name field
```

**Pros:**
- Zero breaking changes
- Natural user experience
- LLM can use either mode

**Cons:**
- Potential edge cases if pattern contains `::` unintentionally
  - Not possible in C++ (:: is reserved)
  - Only issue if someone searches for literal `::` string (rare)

---

**Option B: Explicit Parameter**

```json
search_classes({
  "pattern": "View",
  "match_mode": "qualified" | "unqualified" | "auto"
})
```

**Pros:**
- Explicit control
- No ambiguity in behavior

**Cons:**
- More complex API
- Existing clients need updates for `match_mode` parameter
  - Could default to "auto" for backward compat

---

**Option C: API Versioning**

- `/v1/tools/call` - Unqualified only (deprecated)
- `/v2/tools/call` - Qualified-aware

**Pros:**
- Clean separation
- No backward compat concerns

**Cons:**
- Maintaining two APIs
- Migration burden for clients
- Not standard in MCP protocol

---

**Recommendation: Option A (Dual Mode)**

Simplest for users, no breaking changes, natural behavior.

---

#### New Tool Parameters

**1. Namespace Filtering (All Search Tools)**

```json
search_classes({
  "pattern": "Config",
  "namespace": "app::core"  // Optional: filter by namespace
})
```

**Behavior:**
- If omitted: search all namespaces (current behavior)
- If provided: only return symbols in that namespace (or child namespaces?)

**Question:** Should `"namespace": "app"` match:
- Only `app::Config`? (exact)
- Or also `app::core::Config`? (prefix matching)

**Recommendation:** Prefix matching (more useful)

---

**2. Qualified Name Preference (All Tools)**

```json
get_class_info({
  "class_name": "View",
  "prefer_namespace": "ui"  // Optional: rank ui::View first
})
```

**Behavior:**
- When multiple matches exist, prefer symbols in specified namespace
- Useful for LLMs to incorporate user context

---

### Algorithm Design

#### Qualified Name Matching

**Pseudocode:**
```python
def search_symbols(pattern: str, namespace: str = None):
    mode = detect_pattern_mode(pattern)

    if mode == 'unqualified':
        # Match on name field
        sql = "SELECT * FROM symbols_fts WHERE name MATCH ?"
        params = [pattern]

    elif mode == 'qualified':
        # Suffix matching on qualified_name
        # "ui::View" matches "*::ui::View"
        if pattern.startswith('::'):
            # Absolute reference
            sql = "SELECT * FROM symbols WHERE qualified_name = ?"
            params = [pattern[2:]]  # Remove leading ::
        else:
            # Suffix match
            sql = "SELECT * FROM symbols WHERE qualified_name LIKE ?"
            params = [f'%::{pattern}' if '::' not in pattern.split('::')[0]
                      else f'%{pattern}']

    elif mode == 'regex':
        # Regex matching (Python-side after SQL fetch)
        sql = "SELECT * FROM symbols"
        results = execute(sql)
        return [r for r in results if re.fullmatch(pattern, r.qualified_name)]

    # Apply namespace filter if provided
    if namespace:
        sql += " AND (namespace = ? OR namespace LIKE ?)"
        params += [namespace, f'{namespace}::%']

    return execute(sql, params)
```

**Performance considerations:**
- `LIKE '%::pattern'` → Cannot use index (slow on large tables)
  - Solution: FTS5 for qualified_name, or specialized index
- Regex matching → O(n) in Python (slow)
  - Solution: Limit to FTS5 results first, then regex filter

---

#### Partial Qualification Semantics

**Rules:**

1. **Suffix matching:** `"ui::View"` matches any qualified name ending with `::ui::View`
   - `app::ui::View` ✅
   - `legacy::ui::View` ✅
   - `ui::View` ✅ (exact match is a suffix)
   - `app::ui::subns::View` ❌ (not a suffix)

2. **Exact matching:** `"::View"` (leading `::`) matches only global namespace
   - `::View` ✅
   - `ns::View` ❌

3. **Component boundaries:** Matching respects `::` delimiters
   - `"app::View"` does NOT match `myapp::View` (component mismatch)
   - Each `::` is a hard boundary

**Edge cases:**

- Empty namespace: `qualified_name = "View"` (no `::`)
  - Matches `"View"` pattern (exact)
  - Does NOT match `"::View"` (global namespace explicit)

- Nested classes: `"ns::Outer::Inner"`
  - Treated same as namespaces
  - `"Outer::Inner"` matches `ns::Outer::Inner`

---

### Performance Optimizations

#### 1. FTS5 Indexing Strategy

**Current:** FTS5 indexes only `name`
**Proposed:** FTS5 indexes both `name` and `qualified_name`

**Query patterns:**
```sql
-- Unqualified search (fast, uses FTS5):
SELECT * FROM symbols_fts WHERE name MATCH 'View';

-- Qualified search (fast, uses FTS5):
SELECT * FROM symbols_fts WHERE qualified_name MATCH 'ns1::ui::View';

-- Partial qualified (slower, uses LIKE):
SELECT * FROM symbols WHERE qualified_name LIKE '%::ui::View';
```

**Trade-off:** FTS5 index size increases ~50%, but queries remain fast

---

#### 2. Namespace Prefix Index

For efficient namespace filtering:
```sql
CREATE INDEX idx_namespace_prefix ON symbols(namespace);
```

**Enables fast queries:**
```sql
-- Exact namespace:
SELECT * FROM symbols WHERE namespace = 'app::core';

-- Namespace prefix (child namespaces):
SELECT * FROM symbols WHERE namespace LIKE 'app::core::%';
```

---

#### 3. Caching Qualified Name Components

**Optimization idea:** Store namespace components for faster partial matching

**Schema addition:**
```sql
-- Store namespace as JSON array for structured queries
ALTER TABLE symbols ADD COLUMN namespace_components TEXT;
-- Example: '["ns1", "ui"]' for ns1::ui
```

**Query:**
```sql
-- Find all symbols in any 'ui' namespace (any level):
SELECT * FROM symbols WHERE namespace_components LIKE '%"ui"%';
```

**Decision:** Defer to Phase 3 (not needed for v1)

---

## Implementation Plan

### Phase 1: Foundation (2-3 weeks)

**Goal:** Store and return qualified information without changing search behavior

#### Tasks

**1.1 Schema Update (3 days)**
- [ ] Add `qualified_name TEXT` column to symbols table
- [ ] Add `namespace TEXT` column to symbols table
- [ ] Update FTS5 virtual table to include qualified_name
- [ ] Create indexes: `idx_symbols_namespace`, `idx_symbols_qualified_name`
- [ ] Increment schema version (8.0 → 9.0)
- [ ] Test schema migration (auto-recreation)

**1.2 Symbol Extraction Enhancement (5 days)**
- [ ] Update `cpp_analyzer.py:_process_cursor()` to extract qualified names
  - Use `cursor.semantic_parent` to build namespace path
  - Use `cursor.spelling` for name
  - Combine for qualified_name
- [ ] Extract and store namespace separately
- [ ] Handle edge cases:
  - Global namespace (empty string)
  - Nested classes (qualified name includes parent class)
  - Anonymous namespaces
- [ ] Update `SymbolInfo` dataclass with new fields
- [ ] Test extraction on sample projects

**1.3 Template Argument Qualification (3 days)**
- [ ] Fix Issue #102: Use qualified types for template arguments
- [ ] Update base class name extraction in `_process_cursor()`
- [ ] Use `cursor.type.spelling` instead of `cursor.displayname`
- [ ] Test with template specializations

**1.4 Results Enhancement (2 days)**
- [ ] Update all tool result formatters to include `qualified_name`
- [ ] Update all tool result formatters to include `namespace`
- [ ] Ensure backward compatibility (add fields, don't remove)
- [ ] Update tool descriptions in `cpp_mcp_server.py`

**1.5 Testing (2 days)**
- [ ] Create test fixtures with qualified names
- [ ] Run existing tests (should pass without modification)
- [ ] Validate qualified_name in results
- [ ] Test on large production codebase (~5700 files)

**Deliverable:** All tools return `qualified_name` and `namespace` in results

**Success Criteria:**
- Schema v9.0 deployed
- All symbols have qualified_name and namespace
- Existing tests pass
- No changes to search behavior yet

---

### Phase 2: Qualified Search (1-2 weeks)

**Goal:** Accept qualified patterns in search tools

#### Tasks

**2.1 Pattern Detection (2 days)**
- [ ] Implement `detect_pattern_mode()` in `search_engine.py`
- [ ] Add tests for pattern detection logic
- [ ] Handle edge cases (empty pattern, special characters)

**2.2 Search Engine Update (4 days)**
- [ ] Modify `SearchEngine` class to support qualified mode
- [ ] Implement suffix matching for partial qualification
- [ ] Implement absolute matching for leading `::`
- [ ] Optimize queries (use FTS5 where possible)
- [ ] Fallback to LIKE for complex patterns

**2.3 Tool Integration (3 days)**
- [ ] Update `search_classes` tool
- [ ] Update `search_functions` tool
- [ ] Update `search_symbols` tool
- [ ] Update `find_in_file` tool
- [ ] Test each tool with qualified patterns

**2.4 Validation (2 days)**
- [ ] Execute TC1, TC2 from validation plan
- [ ] Verify qualified search works
- [ ] Verify unqualified search still works (backward compat)
- [ ] Performance testing (large codebase)

**Deliverable:** Tools accept qualified patterns: `search_classes({"pattern": "ns::View"})`

**Success Criteria:**
- Qualified patterns return correct results
- Unqualified patterns work as before
- Performance acceptable (< 50ms for 100K symbols)

---

### Phase 3: Advanced Features (2-3 weeks)

**Goal:** Namespace filtering, template support, edge cases

#### Tasks

**3.1 Namespace Parameter (4 days)**
- [ ] Add `namespace` parameter to search tools
- [ ] Implement prefix matching (e.g., "app" matches "app::core::X")
- [ ] Update tool schemas with new parameter
- [ ] Add validation for namespace format

**3.2 get_class_info / get_function_info Update (3 days)**
- [ ] Support qualified names in `class_name` / `function_name` parameters
- [ ] Handle ambiguity when unqualified name provided
- [ ] Return warning if multiple matches exist
- [ ] Add `prefer_namespace` parameter (optional)

**3.3 Call Graph Tools Update (3 days)**
- [ ] Update `find_callers` / `find_callees` to support qualified names
- [ ] Store qualified names for call sites (if not already)
- [ ] Test with overloaded functions

**3.4 Derived/Base Classes Tools (2 days)**
- [ ] Update `get_derived_classes` to support qualified names
- [ ] Update `get_base_classes` to support qualified names
- [ ] Test with template specializations

**3.5 Documentation and Examples (2 days)**
- [ ] Update tool descriptions in MCP schema
- [ ] Add examples of qualified vs unqualified usage
- [ ] Update README and CLAUDE.md
- [ ] Create user guide for qualified name patterns

**3.6 Edge Cases and Polish (2 days)**
- [ ] Anonymous namespaces handling
- [ ] Global namespace (`::`) edge cases
- [ ] Very long qualified names (>500 chars)
- [ ] Unicode in namespaces (if supported by libclang)

**Deliverable:** Full qualified name support across all tools

**Success Criteria:**
- All tools support qualified and unqualified modes
- Namespace filtering works
- Documentation complete
- Ready for production use

---

### Testing Strategy

#### Unit Tests
- Pattern detection logic
- Qualified name extraction from cursors
- Suffix matching algorithm
- Namespace prefix matching

#### Integration Tests
- End-to-end search with qualified names
- Backward compatibility (existing test suite)
- Performance benchmarks (large codebase)

#### Validation Tests
- Execute full validation plan (docs/VALIDATION_TEST_PLAN.md)
- Test on large production codebase (~5700 files)
- LLM testing (lightweight models)

---

## Open Questions

### Q1: Partial Qualification Matching Rules ⚠️ CRITICAL

**Question:** What should `"ui::View"` match?

**Option A: Suffix Matching (RECOMMENDED)**
- Matches: `app::ui::View`, `legacy::ui::View`
- Does NOT match: `app::ui::core::View` (not a suffix)
- Rationale: Most intuitive, similar to filesystem paths

**Option B: Anywhere Matching**
- Matches: `app::ui::View`, `app::ui::core::View`
- Rationale: More flexible, finds all occurrences

**Option C: Component-wise Matching**
- `"ui::View"` only matches if `ui` is immediate parent namespace
- Does NOT match: `app::nested::ui::View`
- Rationale: More precise, less surprising

**Decision needed before Phase 2 implementation.**

---

### Q2: Function Overload Identification

**Question:** How to identify specific overload when multiple exist?

```cpp
namespace ns {
  void foo(int);
  void foo(double);
}
```

**Option A: Return All Overloads (v1)**
- `get_function_info({"function_name": "ns::foo"})` returns both
- User inspects `signature` field to distinguish
- Simple, no signature parsing needed

**Option B: Signature Matching (v2)**
- `get_function_info({"function_name": "ns::foo(int)"})` returns specific overload
- Requires signature parsing and normalization
- Complex but more precise

**Recommendation:** Option A for v1, consider Option B for future

---

### Q3: Template Specialization Qualified Names

**Question:** How to represent template specializations?

```cpp
namespace ns1 { class Foo {}; }
template<typename T> class Container {};
```

**Current (Issue #102):**
- `Container<Foo>` (ambiguous)

**Option A: Qualified Template Args**
- `Container<ns1::Foo>` (precise)
- Fixes Issue #102
- Straightforward

**Option B: Template USR**
- Use libclang USR for templates
- USR is unique but not human-readable
- Good for internal use, bad for API

**Recommendation:** Option A (qualified template args)

**Follow-up:** Should generic template be searchable separately from specializations?
- `"Container"` → generic template only, or all specializations?
- See Issue #99 for full discussion

---

### Q4: Leading `::` Semantics

**Question:** What does `"::View"` mean?

**Option A: Global Namespace Only**
- `"::View"` matches only `View` in global namespace
- `"View"` matches View in any namespace
- C++-like semantics

**Option B: No Special Meaning**
- `"::View"` treated same as `"View"`
- Leading `::` stripped

**Recommendation:** Option A (global namespace explicit)
- Aligns with C++ syntax
- Provides way to disambiguate global vs namespaced

---

### Q5: Namespace Filtering Scope

**Question:** Should `namespace="app"` parameter match child namespaces?

**Option A: Prefix Matching (RECOMMENDED)**
- `namespace="app"` matches `app::X`, `app::core::Y`, `app::ui::View`
- Intuitive, useful for scoping searches

**Option B: Exact Matching**
- `namespace="app"` matches only `app::X`, not `app::core::Y`
- More precise but less useful

**Recommendation:** Option A with ability to opt-out
```json
{
  "namespace": "app",
  "namespace_exact": false  // Default: prefix matching
}
```

---

### Q6: Performance vs Precision Trade-offs

**Question:** Acceptable performance degradation for qualified name support?

**Scenarios:**
- Unqualified search: Currently ~2-5ms for 100K symbols (FTS5)
- Qualified suffix matching: Requires `LIKE '%::pattern'` (slower, no index)
- Regex matching: O(n) Python-side filtering

**Options:**
- **Option A: Accept slowdown** (10-50ms) for qualified searches
- **Option B: Optimize with specialized indexes** (complex)
- **Option C: Cache common qualified patterns** (memory overhead)

**Need input:** What is acceptable latency?

---

### Q7: Anonymous Namespace Handling

**Question:** How to represent anonymous namespaces?

```cpp
namespace { class Internal {}; }  // Anonymous namespace
```

**libclang representation:**
- `qualified_name` might be `"(anonymous namespace)::Internal"`
- Or use unique identifier per file

**Options:**
- **Option A:** Use libclang's representation as-is
- **Option B:** Custom representation: `"<anonymous>::Internal"`
- **Option C:** Include file path: `"file.cpp::<anonymous>::Internal"`

**Recommendation:** Option A (libclang as-is) for v1, evaluate if issues arise

---

### Q8: Nested Class Qualified Names

**Question:** How to handle nested classes?

```cpp
namespace ns {
  class Outer {
    class Inner {};
  };
}
```

**Qualified name:** `"ns::Outer::Inner"`

**Question:** Should this be treated like:
- Namespace + class name? (`namespace="ns::Outer", name="Inner"`)
- Or just qualified_name? (`qualified_name="ns::Outer::Inner"`)

**Current approach:** Just qualified_name (simpler)
**Issue:** Cannot easily query "all classes in Outer" (they're not in a namespace)

**Recommendation:** Keep simple for v1, add `parent_class` field in future if needed

---

### Q9: Backward Compatibility - Schema Migration

**Question:** How to handle existing caches when schema changes?

**Current behavior:**
- Schema version mismatch → auto-delete and recreate cache
- Works for development, but loses data

**Options:**
- **Option A: Continue auto-recreation** (acceptable for v1)
  - Pro: Simple
  - Con: Users lose cached data on upgrade
- **Option B: Implement migration**
  - Migrate old schema to new (add columns, populate)
  - Pro: Preserve data
  - Con: Complex, error-prone
- **Option C: Dual-cache approach**
  - Keep old cache, create new, migrate asynchronously
  - Pro: No downtime
  - Con: Very complex

**Recommendation:** Option A for initial release, consider B for stable version

---

### Q10: LLM Guidance - Tool Descriptions

**Question:** How much detail in tool descriptions vs documentation?

**Options:**
- **Option A: Detailed tool descriptions**
  - Each tool's description explains qualified vs unqualified
  - Examples in description
  - Pro: LLM sees info directly
  - Con: Verbose, token-heavy

- **Option B: Concise descriptions + external docs**
  - Brief mention in tool description
  - Link to documentation
  - Pro: Cleaner API
  - Con: LLM might not follow links

**Recommendation:** Option A (detailed) for critical tools, B for less common ones

---

## Risks and Mitigation

### Risk 1: Breaking Changes
**Severity:** 🔴 CRITICAL
**Probability:** MEDIUM (if not careful)

**Risk:** Existing clients/LLMs break due to API changes

**Mitigation:**
- Dual-mode operation (auto-detect qualified vs unqualified)
- All new parameters optional
- Existing tests must pass without modification
- Extensive backward compatibility testing

**Contingency:**
- API versioning (v1 vs v2) if breaking change unavoidable
- Clear migration guide for affected users

---

### Risk 2: Performance Degradation
**Severity:** 🟡 MEDIUM
**Probability:** MEDIUM

**Risk:** Qualified name matching slows down searches significantly

**Mitigation:**
- FTS5 index on qualified_name (fast for exact matches)
- Benchmarking on large production codebase (~5700 files)
- Set performance targets (< 50ms)
- Optimize critical paths

**Contingency:**
- Degrade to simpler matching if performance unacceptable
- Add caching layer for common queries
- Provide performance mode (less precision, faster)

---

### Risk 3: Implementation Complexity
**Severity:** 🟡 MEDIUM
**Probability:** HIGH

**Risk:** 6-8 week timeline underestimated due to edge cases

**Mitigation:**
- Phased approach (deliver incrementally)
- Focus on 80% use cases first
- Defer edge cases to later phases
- Regular testing and feedback loops

**Contingency:**
- Reduce scope (defer Phase 3 features)
- Extend timeline if necessary
- Prioritize critical fixes (Issues #100, #102) over nice-to-haves

---

### Risk 4: Ambiguity in Partial Qualification
**Severity:** 🟡 MEDIUM
**Probability:** MEDIUM

**Risk:** Users confused by partial qualification matching rules

**Mitigation:**
- Clear documentation with examples
- Consistent behavior across all tools
- Error messages explain matching behavior
- Provide hints when multiple matches found

**Contingency:**
- Add explicit mode flag for strict matching
- Provide diagnostic tool to show what pattern matches

---

### Risk 5: SQLite Schema Changes
**Severity:** 🟡 MEDIUM
**Probability:** HIGH (schema must change)

**Risk:** Cache invalidation on upgrade, data loss

**Mitigation:**
- Auto-recreation for development (current behavior)
- Clear messaging when cache is invalidated
- Fast re-indexing (parallel parsing already optimized)

**Contingency:**
- Implement migration for stable releases
- Provide upgrade script for manual migration
- Version schema explicitly (9.0)

---

### Risk 6: Interaction with Template Issues
**Severity:** 🟢 LOW
**Probability:** MEDIUM

**Risk:** Qualified name support doesn't fully solve template issues (#99, #101)

**Mitigation:**
- Clearly scope: this proposal focuses on name qualification
- Template specialization discovery is separate (Issue #99)
- Template-based inheritance is separate (Issue #101)
- This proposal is foundational for those issues

**Contingency:**
- If templates need more work, treat as follow-up issues
- Don't block qualified name support on full template solution

---

## Success Metrics

### Primary Metrics

**M1: Ambiguity Reduction**
- **Metric:** % of search results that are unique (not ambiguous)
- **Baseline:** ~30% on large codebase (many duplicate names)
- **Target:** > 90% when using qualified names

**M2: LLM Analysis Accuracy**
- **Metric:** % of test queries where LLM analyzes correct symbol
- **Baseline:** ~60% with lightweight models (guessing from ambiguous results)
- **Target:** > 95% when qualified names used in prompts

**M3: Backward Compatibility**
- **Metric:** % of existing tests passing without modification
- **Target:** 100%

### Secondary Metrics

**M4: Performance**
- **Metric:** P95 search latency
- **Baseline:** 5ms (unqualified search)
- **Target:** < 50ms (qualified search with 100K symbols)

**M5: Adoption**
- **Metric:** % of tool calls using qualified patterns (after rollout)
- **Target:** > 50% for large codebase analysis

**M6: User Satisfaction**
- **Metric:** Feedback from users/LLMs
- **Method:** Survey, issue reports, testing feedback

---

## Dependencies

### Upstream Dependencies
- **libclang:** Must provide qualified name APIs (✅ already available)
- **SQLite FTS5:** Must support multiple indexed columns (✅ supported)

### Downstream Dependencies
- **Issue #85 (Template Tracking):** Benefits from qualified names, but not blocked
- **Issue #99 (Template Search):** Requires qualified names for template args
- **Issue #101 (Template Inheritance):** Requires qualified names for specializations

### Internal Dependencies
- **Validation Plan:** Must execute TC1, TC2 before Phase 2
- **Schema Migration:** Must complete before data population

---

## Alternatives Considered

### Alternative 1: Do Nothing
**Description:** Keep unqualified name model, rely on system prompts for disambiguation

**Pros:**
- No implementation cost
- No breaking change risk

**Cons:**
- Issues #98, #100, #102 remain unsolved
- LLM errors continue
- Large codebase support poor
- Competitive disadvantage (other tools use qualified names)

**Verdict:** ❌ Not acceptable - problems are critical

---

### Alternative 2: External Disambiguation Tool
**Description:** Add separate tool `disambiguate_symbol()` instead of modifying existing tools

**Pros:**
- Minimal changes to existing tools
- LLM orchestrates disambiguation

**Cons:**
- Extra tool call overhead
- LLM must learn new workflow
- Doesn't solve search problem
- Awkward UX

**Verdict:** ❌ Doesn't fully solve the problem

---

### Alternative 3: USR-Based Identification
**Description:** Use libclang USR (Unified Symbol Resolution) instead of qualified names

**USR example:** `c:@N@ns1@C@View`

**Pros:**
- Truly unique (no ambiguity possible)
- Already computed by libclang

**Cons:**
- Not human-readable
- Ugly API: `get_class_info({"usr": "c:@N@ns1@C@View"})`
- Doesn't match user mental model
- Difficult for LLM to construct USRs

**Verdict:** ❌ Too low-level for user-facing API
- **Potential use:** Internal tracking, keep qualified names for API

---

### Alternative 4: Namespace-First Approach
**Description:** Require namespace parameter for all searches

```json
// Always specify namespace
search_classes({
  "pattern": "View",
  "namespace": "ns1"  // Required
})
```

**Pros:**
- Forces disambiguation
- Simple mental model

**Cons:**
- Breaking change (namespace required)
- Inconvenient for broad searches
- Doesn't help with templates

**Verdict:** ❌ Too restrictive, breaks backward compatibility

---

## Conclusion

### Recommendation: **APPROVE with Conditions**

**Rationale:**
1. ✅ **Problem is real and critical** - Manual testing demonstrates issues on real codebases
2. ✅ **Solution is sound** - Qualified names align with C++ semantics
3. ✅ **Technically feasible** - libclang provides necessary data
4. ✅ **High ROI** - Solves multiple high-priority issues simultaneously
5. ⚠️ **Risks manageable** - Phased approach mitigates implementation risk

**Conditions:**
1. **Resolve critical design questions** before Phase 2:
   - Q1: Partial qualification matching rules (suffix vs anywhere)
   - Q4: Leading `::` semantics
   - Q5: Namespace filtering scope
2. **Execute validation plan** (TC1, TC2) to confirm observations
3. **Commit to backward compatibility** - zero breaking changes
4. **Set performance targets** and benchmark against them

**Next Steps:**
1. **Discussion session:** Address open questions (Q1-Q10)
2. **Validation execution:** Run test cases from validation plan
3. **Design finalization:** Document decisions on all open questions
4. **Prototype Phase 1:** 1-week spike to validate approach
5. **Go/No-Go decision:** After prototype, decide on full implementation

---

## Appendices

### Appendix A: Related GitHub Issues

- [Issue #98: Support Qualified Names in Search Tools](https://github.com/andreymedv/clang_index_mcp/issues/98)
- [Issue #100: Namespace Filtering and Disambiguation](https://github.com/andreymedv/clang_index_mcp/issues/100) - HIGH priority
- [Issue #102: Template Arguments Use Unqualified Names](https://github.com/andreymedv/clang_index_mcp/issues/102) - Bug
- [Issue #85: Template Information Tracking](https://github.com/andreymedv/clang_index_mcp/issues/85) - Related
- [Issue #99: Template Class Search](https://github.com/andreymedv/clang_index_mcp/issues/99) - Depends on this
- [Issue #101: Template-Based Inheritance](https://github.com/andreymedv/clang_index_mcp/issues/101) - Depends on this

### Appendix B: Testing References

- [Manual Testing Observations](../MANUAL_TESTING_OBSERVATIONS.md) - Original discoveries
- [Validation Test Plan](../VALIDATION_TEST_PLAN.md) - Controlled test cases

### Appendix C: libclang API References

**Relevant libclang APIs for qualified names:**

```python
# Get qualified name
cursor.semantic_parent  # Parent namespace/class
cursor.spelling         # Unqualified name
cursor.displayname      # Display name (may include template args)

# Build qualified name
def get_qualified_name(cursor):
    parts = []
    current = cursor
    while current and current.kind != CursorKind.TRANSLATION_UNIT:
        if current.spelling:
            parts.append(current.spelling)
        current = current.semantic_parent
    return '::'.join(reversed(parts))

# Get namespace
def get_namespace(cursor):
    parts = []
    current = cursor.semantic_parent
    while current and current.kind != CursorKind.TRANSLATION_UNIT:
        if current.kind == CursorKind.NAMESPACE:
            parts.append(current.spelling)
        current = current.semantic_parent
    return '::'.join(reversed(parts)) if parts else ''
```

### Appendix D: SQL Query Examples

**Qualified name searches:**

```sql
-- Exact qualified name
SELECT * FROM symbols WHERE qualified_name = 'ns1::ui::View';

-- Suffix matching (partial qualification)
SELECT * FROM symbols WHERE qualified_name LIKE '%::ui::View';

-- Namespace prefix filtering
SELECT * FROM symbols
WHERE namespace = 'app::core' OR namespace LIKE 'app::core::%';

-- Unqualified search with FTS5
SELECT * FROM symbols_fts WHERE name MATCH 'View';

-- Qualified search with FTS5
SELECT * FROM symbols_fts WHERE qualified_name MATCH 'ns1::ui::View';
```

---

## Questions for Next Discussion

Based on this proposal, please provide feedback on:

1. **Partial qualification rules (Q1):** Suffix matching vs anywhere matching?
2. **Backward compatibility approach:** Dual mode vs explicit parameter vs versioning?
3. **Performance targets:** What search latency is acceptable?
4. **Scope for v1:** All three phases or just Phase 1 + 2?
5. **Function signature matching (Q2):** Defer to v2 or include in v1?
6. **Template semantics (Q3):** How should `"Container"` behave vs `"Container<int>"`?
7. **Namespace filtering (Q5):** Prefix matching default or exact matching?
8. **Timeline:** Is 6-8 weeks realistic given team capacity?

---

**Document Version:** 1.0
**Last Updated:** 2026-01-05
**Status:** Draft - Awaiting Discussion
**Next Review:** After user feedback and validation testing
