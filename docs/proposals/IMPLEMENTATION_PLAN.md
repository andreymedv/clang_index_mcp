# Qualified Name Support - Implementation Plan

**Status:** 📋 Ready for Implementation
**Created:** 2026-01-08
**Last Updated:** 2026-01-08
**Based on:** QUALIFIED_NAME_DISCUSSION_LOG.md (Prioritization section)
**Timeline:** 4-6 weeks total

---

## Document Purpose

This document provides a detailed task breakdown and execution plan for implementing qualified name support. It includes:
- Complete subtask decomposition for all phases (Phase 1-4)
- File-level change specifications
- Inter-task dependencies and optimized execution order
- Validation criteria for each subtask
- Parallel work opportunities identified

**Source documents:**
- Design decisions: `QUALIFIED_NAME_DISCUSSION_LOG.md`
- Proposal overview: `QUALIFIED_NAME_SUPPORT_PROPOSAL.md`

---

## Implementation Overview

### Phase Summary

| Phase | Scope | Duration | Deliverable |
|-------|-------|----------|-------------|
| **Phase 1** | F1+F5+F6+F7 | 2-3 weeks | Foundation complete, qualified names working |
| **Phase 2** | F2+F3 | 1-2 weeks | Search by qualified patterns working |
| **Phase 3** | F4 | 2-3 days | Overload metadata complete |
| **Phase 4** | Testing & Docs | 1 week | Production-ready, documented |

**Total:** 4-6 weeks

### Features Mapping

- **F1:** Базовая поддержка квалифицированных имен (store & return qualified names)
- **F2:** Гибкий поиск по паттернам (partial qualification, component-based suffix matching)
- **F3:** Семантика leading `::` (exact match for global namespace)
- **F4:** Различение function overloads (is_template_specialization metadata)
- **F5:** Квалифицированные template arguments (canonical types with qualification)
- **F6:** Anonymous namespaces (automatic with F1)
- **F7:** Nested classes (automatic with F1)

---

# Phase 1: Foundation & Template Support (2-3 weeks)

**Features:** F1 + F5 + F6 + F7
**Tasks:** T1.1, T1.2, T1.3, T3.2

## Overview

Phase 1 establishes the foundational infrastructure for qualified names:
- Extract and store fully qualified names during indexing
- Update SQLite schema to support qualified name fields
- Modify storage layer to persist qualified names
- Add canonical qualified template arguments to base classes
- Automatically support anonymous namespaces and nested classes

**Key principle:** F1 + F5 together = minimize rework (same extraction logic)

---

## Task T1.1: Qualified Name Extraction

**Goal:** Extract fully qualified names from libclang for all symbol types

**Effort:** 3-4 days
**Dependencies:** None (starting point)

### Subtasks

#### T1.1.1: Implement _get_qualified_name() helper

**Files to modify:**
- `mcp_server/cpp_analyzer.py` (new method, ~50 lines)

**Implementation approach:**
```python
def _get_qualified_name(self, cursor) -> str:
    """
    Build fully qualified name by walking up semantic parent chain.

    Returns:
        Qualified name like "ns1::ns2::ClassName::method"
        For global namespace: just the symbol name
    """
    parts = []
    current = cursor

    while current:
        if current.kind == CursorKind.TRANSLATION_UNIT:
            break

        # Add namespace/class name
        if current.kind in (CursorKind.NAMESPACE,
                           CursorKind.CLASS_DECL,
                           CursorKind.STRUCT_DECL,
                           CursorKind.CLASS_TEMPLATE):
            if current.spelling:  # Skip anonymous
                parts.append(current.spelling)

        current = current.semantic_parent

    parts.reverse()
    return "::".join(parts) if parts else cursor.spelling
```

**Validation:**
- Test nested namespaces: `ns1::ns2::ns3`
- Test nested classes: `Outer::Inner::Method`
- Test template classes: `Template<T>::method`
- Test anonymous namespaces: `(anonymous namespace)::Internal`
- Test global namespace: `GlobalClass`

**Edge cases:**
- Anonymous namespaces (should include "(anonymous namespace)")
- Operator overloads (include "operator" keyword)
- Template partial specializations

---

#### T1.1.2: Implement _extract_namespace() helper

**Files to modify:**
- `mcp_server/cpp_analyzer.py` (new method, ~20 lines)

**Implementation:**
```python
def _extract_namespace(self, qualified_name: str) -> str:
    """
    Extract namespace portion from qualified name.

    Examples:
        "ns1::ns2::Class" → "ns1::ns2"
        "ns1::Outer::Inner" → "ns1::Outer" (includes parent class)
        "GlobalClass" → ""
    """
    if "::" not in qualified_name:
        return ""

    parts = qualified_name.split("::")
    return "::".join(parts[:-1])
```

**Validation:**
- Test namespace extraction for all cases above
- Verify empty string for global namespace
- Verify includes parent classes (Q8 decision)

---

#### T1.1.3: Update SymbolInfo dataclass

**Files to modify:**
- `mcp_server/symbol_info.py` (add fields to dataclass)

**Changes:**
```python
@dataclass
class SymbolInfo:
    name: str
    qualified_name: str = ""      # NEW: Fully qualified name
    namespace: str = ""            # NEW: Namespace portion (for filtering)
    kind: str = ""
    file: str = ""
    line: int = 0
    # ... existing fields ...
```

**Migration note:** Fields have default values for backward compatibility

**Validation:**
- Verify dataclass still serializes/deserializes correctly
- Test with existing code that creates SymbolInfo

---

#### T1.1.4: Add qualified_name extraction to _process_cursor()

**Files to modify:**
- `mcp_server/cpp_analyzer.py` (line ~900-1100, `_process_cursor()` method)

**Changes:**
```python
def _process_cursor(self, cursor, file_path, ...):
    # ... existing code ...

    # NEW: Extract qualified name
    qualified_name = self._get_qualified_name(cursor)
    namespace = self._extract_namespace(qualified_name)

    # Store in symbol_info
    symbol_info = SymbolInfo(
        name=cursor.spelling,
        qualified_name=qualified_name,  # NEW
        namespace=namespace,             # NEW
        # ... existing fields ...
    )
```

**Validation:**
- Unit test: Extract qualified name for classes, functions, methods
- Verify namespace prefixes correct: `ns1::ns2::Class`
- Verify global namespace symbols have qualified_name = name

---

### Task Dependencies (T1.1)

```
T1.1.1 (_get_qualified_name)
  ↓
T1.1.2 (_extract_namespace)
  ↓
T1.1.3 (SymbolInfo update)
  ↓
T1.1.4 (integrate into _process_cursor)
```

**Execution order:** T1.1.1 → T1.1.2 → T1.1.3 → T1.1.4

**Rationale:** Build helpers first, then integrate into main flow

---

## Task T1.2: Schema Changes

**Goal:** Update SQLite schema to store qualified name fields

**Effort:** 1-2 days
**Dependencies:** T1.1.3 (SymbolInfo structure)

### Subtasks

#### T1.2.1: Update schema.sql

**Files to modify:**
- `mcp_server/schema.sql`

**Changes to symbols table:**
```sql
-- Add new columns
ALTER TABLE symbols ADD COLUMN qualified_name TEXT;
ALTER TABLE symbols ADD COLUMN namespace TEXT;

-- Add indexes for qualified name searches
CREATE INDEX IF NOT EXISTS idx_symbols_qualified_name
    ON symbols(qualified_name);
CREATE INDEX IF NOT EXISTS idx_symbols_namespace
    ON symbols(namespace);

-- Update FTS5 table to include qualified_name
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    name,
    qualified_name,  -- NEW
    file,
    content='symbols',
    content_rowid='id'
);
```

**Schema version bump:**
```sql
-- Update version from 8.0 to 9.0
PRAGMA user_version = 9;
```

**Validation:**
- Verify schema applies cleanly on fresh database
- Verify indexes created successfully
- Test FTS5 queries with qualified_name field

---

#### T1.2.2: Update CURRENT_SCHEMA_VERSION constant

**Files to modify:**
- `mcp_server/sqlite_cache_backend.py` (line ~30-40)

**Changes:**
```python
CURRENT_SCHEMA_VERSION = 9  # Updated from 8
```

**Effect:** Triggers auto-recreation of cache on schema mismatch (Q9 decision)

**Validation:**
- Verify old cache detected as outdated
- Verify new cache created with version 9

---

### Task Dependencies (T1.2)

```
T1.2.1 (schema.sql update)
  ↓
T1.2.2 (version bump)
```

**Execution order:** T1.2.1 → T1.2.2

**Note:** **CAN START IN PARALLEL** with T1.1.1-T1.1.2 (independent of extraction helpers)

---

## Task T1.3: Storage Updates

**Goal:** Update storage layer to persist qualified name fields

**Effort:** 2-3 days
**Dependencies:** T1.1 (extraction), T1.2 (schema)

### Subtasks

#### T1.3.1: Update _extract_symbol_info() in cpp_analyzer.py

**Files to modify:**
- `mcp_server/cpp_analyzer.py` (line ~1200-1300)

**Changes:**
```python
def _extract_symbol_info(self, cursor, file_path) -> SymbolInfo:
    qualified_name = self._get_qualified_name(cursor)  # NEW (from T1.1.1)
    namespace = self._extract_namespace(qualified_name)  # NEW (from T1.1.2)

    return SymbolInfo(
        name=cursor.spelling,
        qualified_name=qualified_name,  # NEW
        namespace=namespace,            # NEW
        kind=self._get_symbol_kind(cursor),
        file=file_path,
        line=cursor.location.line,
        # ... existing fields ...
    )
```

**Validation:**
- Test symbol extraction includes qualified names
- Verify integration with existing extraction flow
- Check performance impact (should be minimal)

---

#### T1.3.2: Update SQLiteCacheBackend.store_symbols()

**Files to modify:**
- `mcp_server/sqlite_cache_backend.py` (line ~200-300, `store_symbols()`)

**Changes:**
```python
def store_symbols(self, symbols: List[SymbolInfo]) -> None:
    # Update INSERT statement
    cursor.executemany("""
        INSERT OR REPLACE INTO symbols
        (name, qualified_name, namespace, kind, file, line, ...)
        VALUES (?, ?, ?, ?, ?, ?, ...)
    """, [
        (s.name, s.qualified_name, s.namespace, s.kind, s.file, s.line, ...)
        for s in symbols
    ])

    # Update FTS5 sync
    cursor.executemany("""
        INSERT INTO symbols_fts(rowid, name, qualified_name, file)
        SELECT id, name, qualified_name, file FROM symbols WHERE id = ?
    """, [(s.id,) for s in symbols])
```

**Validation:**
- Test storing symbols with qualified names
- Verify FTS5 index updated correctly
- Check NULL handling for empty qualified_name

---

#### T1.3.3: Update query methods to return qualified_name

**Files to modify:**
- `mcp_server/sqlite_cache_backend.py` (all query methods)

**Methods to update:**
- `search_classes()`
- `search_functions()`
- `search_symbols()`
- `get_symbols_by_file()`
- `get_class_by_name()`
- `get_function_by_name()`

**Changes pattern:**
```python
def search_classes(self, pattern: str) -> List[Dict]:
    cursor.execute("""
        SELECT
            name,
            qualified_name,  -- NEW
            namespace,       -- NEW
            kind,
            file,
            line,
            ...
        FROM symbols
        WHERE kind = 'class' AND ...
    """)

    return [
        {
            "name": row[0],
            "qualified_name": row[1],  # NEW
            "namespace": row[2],       # NEW
            "kind": row[3],
            ...
        }
        for row in cursor.fetchall()
    ]
```

**Validation:**
- Test each query method returns qualified_name
- Verify backward compatibility (qualified_name may be empty for old cache)
- Check JSON serialization works correctly

---

### Task Dependencies (T1.3)

```
T1.1 (extraction helpers) + T1.2 (schema)
  ↓
T1.3.1 (_extract_symbol_info update)
  ↓
T1.3.2 (storage)
  ↓
T1.3.3 (queries)
```

**Execution order:** T1.3.1 → T1.3.2 → T1.3.3

**Critical path:** T1.1 → T1.2 → T1.3

---

## Task T3.2: Template Args Qualification

**Goal:** Store canonical qualified types for template arguments in base classes

**Effort:** 2-3 days
**Dependencies:** T1.1.1 (qualified name extraction helper), T1.1.4 (_process_cursor modified)

**Note:** Bundled with Phase 1 to minimize rework (same extraction logic)

### Subtasks

#### T3.2.1: Extract canonical base class types

**Files to modify:**
- `mcp_server/cpp_analyzer.py` (base class extraction in `_process_cursor()`)

**⚠️ IMPORTANT:** This task should be done **immediately after T1.1.4** while extraction logic is fresh

**Current code (approximate location line ~950-1000):**
```python
# Existing: Extract base classes
for base in cursor.get_children():
    if base.kind == CursorKind.CXX_BASE_SPECIFIER:
        base_type = base.type
        base_name = base_type.spelling
        symbol_info.base_classes.append(base_name)
```

**Updated code:**
```python
# NEW: Extract canonical qualified base classes
for base in cursor.get_children():
    if base.kind == CursorKind.CXX_BASE_SPECIFIER:
        base_type = base.type

        # Use canonical type for template args expansion + qualification
        canonical_type = base_type.get_canonical()
        base_name_qualified = canonical_type.spelling

        # Store canonical qualified name
        symbol_info.base_classes.append(base_name_qualified)
```

**What this does:**
- `base_type.get_canonical()` expands type aliases and adds qualification
- Example: `Container<FooPtr>` → `Container<std::unique_ptr<ns1::Foo>>`
- Validated by TC4 experiment ✅

**Validation:**
- Test with type aliases in template args: `Container<FooPtr>` → canonical form
- Test with qualified types: `Container<ns1::Foo>` → preserved
- Test with nested templates: `Container<vector<Foo>>` → fully qualified
- Verify template class names also qualified: `ns1::Container<...>`

---

#### T3.2.2: Update base_classes field handling

**Files to modify:**
- `mcp_server/symbol_info.py` (if base_classes field needs type update)
- `mcp_server/sqlite_cache_backend.py` (storage of base_classes JSON)

**Current:** `base_classes: List[str]` stores unqualified names

**After T3.2.1:** Stores canonical qualified names

**Changes needed:**
- No SymbolInfo structure change (still `List[str]`)
- Storage format unchanged (JSON array)
- Only content changes (qualified canonical vs unqualified)

**Validation:**
- Verify JSON serialization works with longer names
- Check deserialization from cache
- Test backward compatibility (old cache with unqualified names)

---

#### T3.2.3: Update get_class_info() to return qualified base classes

**Files to modify:**
- `mcp_server/cpp_analyzer.py` (line ~1500-1600, `get_class_info()`)
- `mcp_server/cpp_mcp_server.py` (MCP tool handler, if formatting needed)

**Changes:**
```python
def get_class_info(self, class_name: str) -> Dict:
    # ... existing code ...

    return {
        "name": symbol.name,
        "qualified_name": symbol.qualified_name,  # From T1.1
        "base_classes": symbol.base_classes,  # Now canonical qualified
        # ... existing fields ...
    }
```

**Validation:**
- Test `get_class_info()` returns canonical qualified base classes
- Verify inheritance hierarchy analysis works with qualified names
- Check LLM can parse qualified template args

---

### Task Dependencies (T3.2)

```
T1.1.1 (_get_qualified_name helper) + T1.1.4 (_process_cursor integration)
  ↓
T3.2.1 (canonical base class extraction) ← DO IMMEDIATELY AFTER T1.1.4
  ↓
T3.2.2 (field handling update)
  ↓
T3.2.3 (get_class_info update)
```

**Execution order:** After T1.1.4 complete → **T3.2.1 immediately** → T3.2.2 → T3.2.3

**Rationale (OPTIMIZATION):**
- T1.1.4 modifies `_process_cursor()` for qualified names
- T3.2.1 also modifies `_process_cursor()` for base classes
- Doing T3.2.1 immediately after T1.1.4 = code fresh, minimize context switching
- Avoids reopening file later

---

## Phase 1 Complete Execution Plan (OPTIMIZED)

### Week 1: Parallel Tracks

**Track A (Extraction Helpers):**
```
T1.1.1 (_get_qualified_name) → 1 day
  ↓
T1.1.2 (_extract_namespace) → 0.5 day
  ↓
T1.1.3 (SymbolInfo update) → 0.5 day
```

**Track B (Schema - PARALLEL):**
```
T1.2.1 (schema.sql update) → 1 day (can start immediately)
  ↓
T1.2.2 (version bump) → 0.5 day
```

**Total Week 1:** 2 days (with parallelization)

---

### Week 2: Extraction Integration (Sequential in cpp_analyzer.py)

**⚠️ CRITICAL: Do these sequentially to minimize file reopening**

```
T1.1.4 (_process_cursor + qualified_name) → 1 day
  ↓ IMMEDIATELY (while code fresh)
T3.2.1 (base class canonical types) → 1 day
  ↓
T1.3.1 (_extract_symbol_info) → 1 day
```

**Total Week 2:** 3 days

---

### Week 2-3: Storage & Finalization

```
T1.3.2 (storage) → 1 day
  ↓
T1.3.3 (queries) → 1.5 days
  ↓
T3.2.2 (field handling) → 0.5 day
  ↓
T3.2.3 (get_class_info) → 0.5 day
  ↓
Integration Testing → 2 days
```

**Total Week 2-3:** 5.5 days

---

### Phase 1 Timeline Summary

**Total effort:** 10-11 days (2-2.5 weeks)
**Critical path:** T1.1 → T1.1.4 → T3.2.1 → T1.3 → Testing

**Parallel work savings:** ~1 day (T1.2 starts with T1.1)
**Optimization savings:** ~1 day (T3.2.1 right after T1.1.4, no context switching)

---

## Phase 1 Integration & Validation

### Phase 1 Complete Deliverables

After completing all Phase 1 tasks:

1. ✅ Qualified names extracted and stored for all symbols
2. ✅ SQLite schema updated (version 9) with qualified_name, namespace fields
3. ✅ All query methods return qualified names in results
4. ✅ Template base classes store canonical qualified types
5. ✅ Anonymous namespaces automatically represented as "(anonymous namespace)::"
6. ✅ Nested classes automatically have full qualified names (ns::Outer::Inner)
7. ✅ Backward compatibility maintained (unqualified search still works)

### Phase 1 Validation Tests

**Integration test checklist:**

```python
# Test T1.1: Qualified name extraction
def test_qualified_name_extraction():
    # Namespace qualification
    assert class_info.qualified_name == "ns1::ns2::MyClass"

    # Nested classes
    assert inner_class.qualified_name == "Outer::Inner"

    # Anonymous namespace
    assert anon_class.qualified_name == "(anonymous namespace)::Internal"

    # Global namespace
    assert global_class.qualified_name == "GlobalClass"

# Test T1.2 + T1.3: Storage and retrieval
def test_qualified_name_storage():
    # Store symbols
    analyzer.cache_manager.store_symbols([symbol_with_qualified_name])

    # Retrieve and verify
    result = analyzer.search_classes("MyClass")
    assert result[0]["qualified_name"] == "ns1::MyClass"
    assert result[0]["namespace"] == "ns1"

# Test T3.2: Template base classes
def test_canonical_base_classes():
    # Type alias in template arg
    class_info = analyzer.get_class_info("Derived")
    assert "Container<std::unique_ptr<ns1::Foo>>" in class_info["base_classes"]
    # NOT "Container<FooPtr>"

# Test backward compatibility
def test_backward_compatibility():
    # Old-style unqualified search still works
    results = analyzer.search_classes("View")
    assert len(results) > 0
    # But now results include qualified_name for disambiguation
```

### Known Limitations After Phase 1

**Documented in Phase 1 release:**

1. ❌ **Qualified pattern search NOT yet working**
   - `search_classes("ns2::View")` returns empty (needs Phase 2)
   - Workaround: Use unqualified `"View"`, filter by qualified_name in results

2. ❌ **Leading `::` semantics NOT implemented**
   - `search_classes("::View")` not special (needs Phase 2)

3. ❌ **Overload metadata NOT available**
   - `is_template_specialization` field missing (needs Phase 3)

4. ✅ **What DOES work:**
   - Results include qualified names → reduces ambiguity
   - Template inheritance analysis → enables template analysis
   - Anonymous namespaces → represented correctly
   - Nested classes → full qualified names

---

# Phase 2: Search Capabilities (1-2 weeks)

**Features:** F2 + F3
**Tasks:** T2.1, T2.2, T2.3

## Overview

Phase 2 implements qualified pattern matching on top of Phase 1 infrastructure:
- Component-based suffix matching algorithm
- Leading `::` detection for exact match
- Dual-mode support (qualified + unqualified patterns)
- Update all search tools to use new pattern matching

**Dependency:** Requires Phase 1 complete (qualified names in database)

---

## Task T2.1: Pattern Matching Engine

**Goal:** Implement component-based pattern matching with regex support

**Effort:** 3-4 days
**Dependencies:** Phase 1 complete

### Subtasks

#### T2.1.1: Implement matches_qualified_pattern() in search_engine.py

**Files to modify:**
- `mcp_server/search_engine.py` (new method, ~100 lines)

**Implementation:**
```python
def matches_qualified_pattern(self, qualified_name: str, pattern: str) -> bool:
    """
    Match qualified name against pattern using component-based suffix matching.

    Rules (from Q1 decision):
    1. Leading "::" → exact match (global namespace)
    2. No "::" in pattern → match unqualified name only
    3. "::" in pattern → component-based suffix match
    4. Regex metacharacters → regex match

    Examples:
        matches_qualified_pattern("app::ui::View", "ui::View") → True
        matches_qualified_pattern("app::ui::View", "::View") → False (not global)
        matches_qualified_pattern("app::ui::View", "View") → True (unqualified)
        matches_qualified_pattern("app::ui::View", ".*::View") → True (regex)
    """
    # 1. Leading :: → exact match
    if pattern.startswith("::"):
        return qualified_name == pattern[2:]

    # 2. Detect regex metacharacters
    regex_chars = set(".*+?[]{}()|\\^$")
    is_regex = any(c in pattern for c in regex_chars)

    if is_regex:
        # Regex mode: anchored full match
        try:
            return bool(re.fullmatch(pattern, qualified_name))
        except re.error:
            return False

    # 3. No :: in pattern → match unqualified name
    if "::" not in pattern:
        # Extract unqualified name from qualified_name
        unqualified = qualified_name.split("::")[-1]
        return unqualified == pattern

    # 4. Component-based suffix matching
    q_parts = qualified_name.split("::")
    p_parts = pattern.split("::")

    if len(p_parts) > len(q_parts):
        return False

    # Check that last N components match
    return q_parts[-len(p_parts):] == p_parts
```

**Validation:**
- Test exact match: `"::View"` matches only `"View"`
- Test suffix: `"ui::View"` matches `"app::ui::View"`, `"legacy::ui::View"`
- Test unqualified: `"View"` matches all `View` classes
- Test regex: `"app::.*::View"` matches `"app::core::View"`, `"app::ui::View"`
- Test component boundary: `"app::View"` does NOT match `"myapp::View"`

---

#### T2.1.2: Add pattern type detection helper

**Files to modify:**
- `mcp_server/search_engine.py` (new helper method)

**Implementation:**
```python
def _detect_pattern_type(self, pattern: str) -> str:
    """
    Detect pattern type for optimization.

    Returns: "exact", "unqualified", "suffix", or "regex"
    """
    if pattern.startswith("::"):
        return "exact"

    regex_chars = set(".*+?[]{}()|\\^$")
    if any(c in pattern for c in regex_chars):
        return "regex"

    if "::" not in pattern:
        return "unqualified"

    return "suffix"
```

**Purpose:** Optimize search queries based on pattern type

---

#### T2.1.3: Implement optimized SQL query generation

**Files to modify:**
- `mcp_server/search_engine.py` (new method for query optimization)

**Implementation:**
```python
def build_search_query(self, pattern: str, kind: str = None) -> tuple:
    """
    Build optimized SQL query based on pattern type.

    Optimization strategy (from Q6 decision):
    - exact: WHERE qualified_name = ?
    - unqualified: WHERE name = ?
    - suffix: WHERE qualified_name LIKE ?
    - regex: Fetch all, filter in Python
    """
    pattern_type = self._detect_pattern_type(pattern)

    base_query = "SELECT * FROM symbols"
    params = []

    # Kind filter
    if kind:
        base_query += " WHERE kind = ?"
        params.append(kind)
    else:
        base_query += " WHERE 1=1"

    # Pattern filter
    if pattern_type == "exact":
        # ::Name → exact match on qualified_name
        exact_name = pattern[2:]
        base_query += " AND qualified_name = ?"
        params.append(exact_name)

    elif pattern_type == "unqualified":
        # Name → match on name field
        base_query += " AND name = ?"
        params.append(pattern)

    elif pattern_type == "suffix":
        # ns::Name → LIKE %ns::Name
        base_query += " AND qualified_name LIKE ?"
        params.append(f"%{pattern}")

    elif pattern_type == "regex":
        # .*::Name → fetch all, filter in Python
        pass

    return base_query, params, pattern_type
```

**Validation:**
- Test query optimization for each pattern type
- Verify LIKE queries use indexes
- Check regex patterns fetch efficiently

---

### Task Dependencies (T2.1)

```
T2.1.2 (_detect_pattern_type)
  ↓
T2.1.1 (matches_qualified_pattern) + T2.1.3 (optimized queries)
```

**Execution order:** T2.1.2 → T2.1.1 + T2.1.3 (parallel)

---

## Task T2.2: Update Search Tools

**Goal:** Integrate pattern matching into all MCP search tools

**Effort:** 2-3 days
**Dependencies:** T2.1 (pattern matching engine)

### Subtasks

#### T2.2.1: Update search_classes() in cpp_analyzer.py

**Files to modify:**
- `mcp_server/cpp_analyzer.py` (line ~800-900, `search_classes()`)

**Changes:**
```python
def search_classes(self, pattern: str = "", **filters) -> List[Dict]:
    """
    Search for classes by qualified or unqualified pattern.

    Args:
        pattern: Qualified pattern (e.g., "ns::Class"), unqualified ("Class"),
                 or regex (".*::Class")
    """
    # Build optimized query
    query, params, pattern_type = self.search_engine.build_search_query(
        pattern, kind="class"
    )

    # Execute query
    results = self.cache_manager.execute_query(query, params)

    # For regex patterns, filter in Python
    if pattern_type == "regex":
        results = [
            r for r in results
            if self.search_engine.matches_qualified_pattern(
                r["qualified_name"], pattern
            )
        ]

    return results
```

**Validation:**
- Test qualified pattern search works
- Verify backward compatibility (unqualified still works)
- Check performance acceptable (<100ms per Q6)

---

#### T2.2.2: Update search_functions() in cpp_analyzer.py

**Files to modify:**
- `mcp_server/cpp_analyzer.py` (similar to search_classes)

**Changes:** Same pattern as T2.2.1, but for functions

**Validation:**
- Test qualified function search: `"ns::foo"`
- Test member functions: `"Class::method"`
- Test namespace functions: `"ns1::ns2::helper"`

---

#### T2.2.3: Update search_symbols() in cpp_analyzer.py

**Files to modify:**
- `mcp_server/cpp_analyzer.py` (unified symbol search)

**Changes:** Same pattern matching integration

**Validation:**
- Test mixed symbol type search
- Verify filtering by kind works with qualified patterns

---

#### T2.2.4: Update find_in_file() for qualified filtering

**Files to modify:**
- `mcp_server/cpp_analyzer.py` (`find_in_file()`)

**Changes:**
```python
def find_in_file(self, file_path: str, pattern: str = "") -> List[Dict]:
    """
    Find symbols in file, optionally filtered by qualified pattern.
    """
    # Get all symbols in file
    symbols = self.cache_manager.get_symbols_by_file(file_path)

    # Filter by pattern if provided
    if pattern:
        symbols = [
            s for s in symbols
            if self.search_engine.matches_qualified_pattern(
                s["qualified_name"], pattern
            )
        ]

    return symbols
```

**Validation:**
- Test file + qualified pattern: `find_in_file("foo.cpp", "ns::Class")`
- Verify empty pattern returns all symbols

---

### Task Dependencies (T2.2)

```
T2.1 (pattern matching engine)
  ↓
T2.2.1 (search_classes) ← Can be done in parallel with below
T2.2.2 (search_functions)
T2.2.3 (search_symbols)
T2.2.4 (find_in_file)
```

**Execution order:** After T2.1 → All T2.2.x **in parallel** (independent)

**Time savings:** 1 day (parallel vs sequential)

---

## Task T2.3: Dual-Mode Support

**Goal:** Ensure backward compatibility with unqualified patterns

**Effort:** 1 day
**Dependencies:** T2.2 (search tools updated)

### Subtasks

#### T2.3.1: Add backward compatibility tests

**Files to create:**
- `tests/test_qualified_search.py` (new integration test file)

**Test cases:**
```python
def test_unqualified_pattern_still_works():
    """Old-style unqualified search must work"""
    results = analyzer.search_classes("View")
    assert len(results) > 0

def test_qualified_pattern_narrows_results():
    """Qualified pattern should reduce ambiguity"""
    all_views = analyzer.search_classes("View")
    ns1_views = analyzer.search_classes("ns1::View")
    assert len(ns1_views) <= len(all_views)

def test_leading_colon_exact_match():
    """Leading :: means exact match"""
    results = analyzer.search_classes("::GlobalClass")
    assert len(results) == 1
    assert results[0]["namespace"] == ""

def test_regex_patterns():
    """Regex patterns work"""
    results = analyzer.search_classes("app::.*::Config")
    for r in results:
        assert r["qualified_name"].startswith("app::")
        assert r["qualified_name"].endswith("::Config")
```

**Validation:** All tests pass

---

#### T2.3.2: Update MCP tool parameter descriptions

**Files to modify:**
- `mcp_server/cpp_mcp_server.py` (tool definitions)

**Changes:**
```python
{
    "name": "search_classes",
    "description": """
    Search for C++ classes by name pattern.

    Supports multiple pattern types:
    - Unqualified: "View" - matches View in any namespace
    - Qualified: "ui::View" - matches View in ui namespace (any parent)
    - Exact: "::View" - matches View in global namespace only
    - Regex: ".*::View" - matches View with any prefix

    Pattern matching uses component-based suffix matching.
    Example: "ui::View" matches "app::ui::View", "legacy::ui::View"
    """,
    "inputSchema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Name pattern (qualified, unqualified, or regex)"
            },
            ...
        }
    }
}
```

**Validation:**
- Tool descriptions clear and accurate
- Examples help LLM understand usage

---

### Task Dependencies (T2.3)

```
T2.2 (search tools updated)
  ↓
T2.3.1 (backward compat tests) ← Can be parallel with T2.3.2
T2.3.2 (tool descriptions)
```

**Execution order:** After T2.2 → T2.3.1 + T2.3.2 (parallel)

---

## Phase 2 Complete Execution Plan

### Week 1: Pattern Matching Engine

```
T2.1.2 (_detect_pattern_type) → 0.5 day
  ↓
T2.1.1 (matches_qualified_pattern) → 2 days (parallel with T2.1.3)
T2.1.3 (optimized queries) → 1.5 days
```

**Total:** 2.5 days

---

### Week 1-2: Search Tool Updates (PARALLEL)

```
T2.2.1 (search_classes) → 1 day ← PARALLEL
T2.2.2 (search_functions) → 1 day ← PARALLEL
T2.2.3 (search_symbols) → 0.5 day ← PARALLEL
T2.2.4 (find_in_file) → 0.5 day ← PARALLEL
```

**Total:** 1 day (with parallelization, vs 3 days sequential)

---

### Week 2: Dual-Mode & Testing

```
T2.3.1 (backward compat tests) → 1 day (parallel with T2.3.2)
T2.3.2 (tool descriptions) → 0.5 day
  ↓
Integration Testing → 1 day
```

**Total:** 1.5 days

---

### Phase 2 Timeline Summary

**Total effort:** 5-6 days (1-1.5 weeks)
**Critical path:** T2.1 → T2.2 → T2.3 → Testing

**Parallel work savings:** ~2 days (T2.2.x in parallel)

---

## Phase 2 Integration & Validation

### Phase 2 Complete Deliverables

After completing Phase 2:

1. ✅ Component-based suffix matching works
2. ✅ Leading `::` exact match works
3. ✅ Regex patterns supported
4. ✅ All search tools accept qualified patterns
5. ✅ Backward compatibility maintained (unqualified search works)
6. ✅ Performance acceptable (<100ms per query)

### Phase 2 Validation Tests

```python
# Test component-based suffix matching
def test_suffix_matching():
    results = analyzer.search_classes("ui::View")
    for r in results:
        assert r["qualified_name"].endswith("ui::View")

# Test exact match
def test_exact_match():
    results = analyzer.search_classes("::GlobalClass")
    assert all(r["namespace"] == "" for r in results)

# Test regex patterns
def test_regex():
    results = analyzer.search_classes("app::core::.*")
    for r in results:
        assert r["qualified_name"].startswith("app::core::")

# Test performance
def test_performance():
    import time
    start = time.time()
    results = analyzer.search_classes(".*::Config")
    elapsed = time.time() - start
    assert elapsed < 0.2  # 200ms acceptable (Q6 decision)
```

### Problems Solved After Phase 2

- ✅ **P1: Namespace Ambiguity** - 100% solved
- ✅ **P2: Search Pattern Failures** - 100% solved
- ✅ **P3: Incorrect LLM Analysis Chains** - 100% solved
- ✅ **P4: System Prompt Workarounds** - 80-90% solved
- ✅ **P5: Template Specialization** - 100% solved (from Phase 1)

**Phase 2 = Core functionality complete, production-ready**

---

# Phase 3: Overload Metadata (2-3 days)

**Features:** F4
**Tasks:** T3.3

## Overview

Phase 3 adds metadata to distinguish function overloads:
- `is_template_specialization: bool` field
- Detection via `cursor.kind` + displayname analysis (validated by TC5)
- `total_overloads` metadata in responses
- Independent from Phase 1/2 (can be done in parallel with Phase 2)

---

## Task T3.3: Function Overload Metadata

**Goal:** Add metadata fields to distinguish templates, specializations, and regular overloads

**Effort:** 2-3 days
**Dependencies:** Phase 1 complete (schema, extraction)
**Can overlap:** Phase 2 (independent work)

### Subtasks

#### T3.3.1: Add is_template_specialization to SymbolInfo

**Files to modify:**
- `mcp_server/symbol_info.py`

**Changes:**
```python
@dataclass
class SymbolInfo:
    name: str
    qualified_name: str = ""
    namespace: str = ""
    kind: str = ""
    is_template_specialization: bool = False  # NEW
    # ... existing fields ...
```

**Validation:**
- Verify field serializes/deserializes correctly
- Test backward compatibility (defaults to False)

---

#### T3.3.2: Implement template detection in _process_cursor()

**Files to modify:**
- `mcp_server/cpp_analyzer.py` (`_process_cursor()`, function handling)

**Implementation (based on TC5 validation):**
```python
def _detect_template_specialization(self, cursor) -> bool:
    """
    Detect if cursor is a template specialization.

    Uses cursor.kind + displayname analysis (TC5 approach).

    Returns:
        False for generic templates (FUNCTION_TEMPLATE)
        True for explicit specializations (displayname contains '<>')
        False for regular overloads
    """
    if cursor.kind == CursorKind.FUNCTION_TEMPLATE:
        return False  # Generic template, not specialization

    if cursor.kind == CursorKind.FUNCTION_DECL:
        # Check displayname for template arguments
        displayname = cursor.displayname
        return '<' in displayname and '>' in displayname

    return False

# In _process_cursor():
if cursor.kind in (CursorKind.FUNCTION_DECL, CursorKind.FUNCTION_TEMPLATE, ...):
    is_template_spec = self._detect_template_specialization(cursor)
    symbol_info = SymbolInfo(
        # ... other fields ...
        is_template_specialization=is_template_spec,
    )
```

**Validation:**
- Test generic templates: `template<T> void foo(T)` → False
- Test specializations: `template<> void foo<int>(int)` → True
- Test regular overloads: `void foo(double)` → False
- Test class methods: handle correctly

---

#### T3.3.3: Update schema for is_template_specialization

**Files to modify:**
- `mcp_server/schema.sql`

**Changes:**
```sql
-- Add column
ALTER TABLE symbols ADD COLUMN is_template_specialization INTEGER DEFAULT 0;

-- Schema version bump
PRAGMA user_version = 10;  -- 9 → 10
```

**Also update:**
- `mcp_server/sqlite_cache_backend.py`: `CURRENT_SCHEMA_VERSION = 10`

**Validation:**
- Schema applies cleanly
- Column stores boolean as INTEGER (SQLite convention)

---

#### T3.3.4: Update storage and queries for new field

**Files to modify:**
- `mcp_server/sqlite_cache_backend.py` (store_symbols, all queries)

**Changes:**
```python
# In store_symbols():
cursor.executemany("""
    INSERT OR REPLACE INTO symbols
    (..., is_template_specialization, ...)
    VALUES (..., ?, ...)
""", [
    (..., s.is_template_specialization, ...)
    for s in symbols
])

# In all query methods:
def search_functions(...):
    cursor.execute("""
        SELECT ..., is_template_specialization, ...
        FROM symbols
        WHERE ...
    """)

    return [
        {
            ...,
            "is_template_specialization": bool(row[X]),
            ...
        }
        for row in cursor.fetchall()
    ]
```

**Validation:**
- Field stored and retrieved correctly
- Boolean conversion works (INTEGER → bool)

---

#### T3.3.5: Add total_overloads metadata to get_function_info()

**Files to modify:**
- `mcp_server/cpp_analyzer.py` (`get_function_info()`)

**Implementation:**
```python
def get_function_info(self, function_name: str) -> Dict:
    """
    Get all overloads of a function.

    Returns metadata including total count (Q2 decision).
    """
    # Find all overloads (qualified or unqualified)
    overloads = self.search_functions(function_name)

    return {
        "data": overloads,
        "metadata": {
            "total_overloads": len(overloads),
            "query_pattern": function_name,
        }
    }
```

**Validation:**
- Test with multiple overloads
- Verify total_overloads count correct
- Check template specializations counted

---

### Task Dependencies (T3.3)

```
T3.3.1 (SymbolInfo update)
  ↓
T3.3.2 (template detection) + T3.3.3 (schema update) ← PARALLEL
  ↓
T3.3.4 (storage/queries)
  ↓
T3.3.5 (metadata in get_function_info)
```

**Execution order:** T3.3.1 → (T3.3.2 + T3.3.3) → T3.3.4 → T3.3.5

**Parallel opportunity:** T3.3.2 and T3.3.3 independent

---

## Phase 3 Execution Plan

```
T3.3.1 (SymbolInfo) → 0.5 day
  ↓
T3.3.2 (detection logic) → 1 day (parallel with T3.3.3)
T3.3.3 (schema update) → 0.5 day
  ↓
T3.3.4 (storage/queries) → 1 day
  ↓
T3.3.5 (metadata) → 0.5 day
  ↓
Testing → 0.5 day
```

**Total:** 3 days

---

## Phase 3 Integration & Validation

### Phase 3 Complete Deliverables

1. ✅ `is_template_specialization` field available in all function results
2. ✅ Clear distinction: generic templates vs specializations vs overloads
3. ✅ `total_overloads` metadata in `get_function_info()` responses
4. ✅ Schema version 10

### Phase 3 Validation Tests

```python
def test_template_specialization_detection():
    # Generic template
    results = analyzer.search_functions("func")
    generic = [r for r in results if not r["is_template_specialization"]]
    assert any("FUNCTION_TEMPLATE" in str(r) for r in generic)

    # Explicit specialization
    specializations = [r for r in results if r["is_template_specialization"]]
    assert all('<' in r["name"] for r in specializations)

def test_overload_metadata():
    info = analyzer.get_function_info("foo")
    assert "metadata" in info
    assert info["metadata"]["total_overloads"] >= 1
```

### Problems Solved After Phase 3

- ✅ **P8: Missing Overload Context** - 100% solved

**Phase 3 = Feature-complete qualified name support**

---

# Phase 4: Testing & Documentation (1 week)

**Tasks:** T4.1, T4.2, T4.3

## Overview

Phase 4 completes the feature with comprehensive testing and documentation:
- Integration tests for all features
- Update MCP tool descriptions for lightweight LLMs
- Migration documentation and breaking changes guide

---

## Task T4.1: Integration Tests

**Goal:** Comprehensive integration tests covering all features

**Effort:** 2-3 days
**Dependencies:** Phase 1-3 complete

### Subtasks

#### T4.1.1: Create integration test suite

**Files to create:**
- `tests/test_qualified_name_integration.py`

**Test coverage:**
```python
class TestQualifiedNameIntegration:
    """Integration tests for qualified name support (F1-F7)"""

    def test_f1_basic_support(self):
        """F1: Store and return qualified names"""
        # Test extraction, storage, retrieval

    def test_f2_pattern_matching(self):
        """F2: Component-based suffix matching"""
        # Test partial qualification

    def test_f3_leading_colon(self):
        """F3: Exact match with leading ::"""
        # Test global namespace

    def test_f4_overload_metadata(self):
        """F4: Overload distinction"""
        # Test is_template_specialization

    def test_f5_template_args(self):
        """F5: Canonical qualified template args"""
        # Test base classes

    def test_f6_anonymous_namespace(self):
        """F6: Anonymous namespace handling"""
        # Test "(anonymous namespace)::"

    def test_f7_nested_classes(self):
        """F7: Nested class qualified names"""
        # Test Outer::Inner
```

**Validation:** All tests pass, >90% code coverage

---

#### T4.1.2: Create performance benchmarks

**Files to create:**
- `tests/test_qualified_name_performance.py`

**Benchmarks:**
```python
def test_search_performance():
    """Verify <100ms per query (Q6 requirement)"""
    import time

    patterns = [
        "View",
        "ui::View",
        "app::.*::Config",
        "::GlobalClass",
    ]

    for pattern in patterns:
        start = time.time()
        results = analyzer.search_classes(pattern)
        elapsed = time.time() - start
        assert elapsed < 0.1, f"Query too slow: {elapsed:.3f}s for {pattern}"
```

**Validation:** All queries <100ms (per Q6 decision)

---

#### T4.1.3: Add edge case tests

**Files to modify:**
- `tests/test_qualified_name_integration.py`

**Edge cases:**
```python
def test_empty_pattern():
    """Empty pattern returns all symbols"""
    results = analyzer.search_classes("")
    assert len(results) > 0

def test_invalid_regex():
    """Invalid regex gracefully handled"""
    results = analyzer.search_classes("[invalid")
    assert results == []  # No crash

def test_unicode_names():
    """Unicode in symbol names handled"""
    # Test with unicode in namespace/class names

def test_very_long_qualified_names():
    """Handle deeply nested namespaces"""
    # Test ns1::ns2::ns3::...::ns10::Class
```

**Validation:** All edge cases handled correctly

---

### Task Dependencies (T4.1)

```
T4.1.1 (integration tests) → 2 days
  ↓ (parallel with below)
T4.1.2 (performance benchmarks) → 0.5 day
T4.1.3 (edge cases) → 0.5 day
```

**Execution order:** T4.1.1 → (T4.1.2 + T4.1.3) parallel

**Total:** 2.5 days

---

## Task T4.2: Tool Description Updates

**Goal:** Update MCP tool descriptions for lightweight LLM comprehension

**Effort:** 1-2 days
**Dependencies:** Phase 2 complete (pattern matching defined)

### Subtasks

#### T4.2.1: Update search tool descriptions

**Files to modify:**
- `mcp_server/cpp_mcp_server.py` (all search tool definitions)

**Approach (from Q10 decision):**
- Use explicit, simple language (not technical jargon)
- Provide clear examples in descriptions
- Avoid assumptions about C++ knowledge
- Test descriptions with target LLMs (qwen3-4b, qwen3-30b)

**Example for search_classes:**
```python
{
    "name": "search_classes",
    "description": """
    Find C++ classes by name. Returns information about matching classes.

    **Pattern types:**

    1. Simple name: "View"
       - Finds View class in ANY location
       - Use when you don't know or don't care about location

    2. With location: "ui::View"
       - Finds View class inside ui location (namespace or parent class)
       - The location can be anywhere: "app::ui::View", "legacy::ui::View"
       - Use when you want View from specific location

    3. Exact location: "::View"
       - Finds View ONLY at top level (global namespace)
       - The :: at start means "exactly at top level"

    4. Pattern matching: "app::.*::Config"
       - Finds Config inside app, with anything in between
       - .* means "anything", * means "any letters"

    **Examples:**
    - search_classes("Config") → all Config classes everywhere
    - search_classes("app::Config") → Config in app (any parent)
    - search_classes("::Config") → Config at top level only

    **Results include:**
    - qualified_name: Full location of class (e.g., "app::ui::View")
    - name: Simple name without location (e.g., "View")
    - namespace: Location prefix (e.g., "app::ui")
    """,
    "inputSchema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Class name or pattern to search for"
            }
        }
    }
}
```

**Validation:**
- Test with qwen3-4b: Can LLM understand and use patterns correctly?
- Iterate based on observed LLM behavior

---

#### T4.2.2: Update get_class_info and get_function_info descriptions

**Files to modify:**
- `mcp_server/cpp_mcp_server.py`

**Focus:**
- Explain qualified_name vs name distinction
- Clarify base_classes now include template arguments
- Explain is_template_specialization for functions

**Validation:**
- Clear explanation of template specialization concept
- Examples help LLM distinguish templates vs specializations

---

#### T4.2.3: Add system prompt guidance (if needed)

**Files to create:**
- `docs/SYSTEM_PROMPT_GUIDANCE.md` (optional)

**Content:**
- Recommended system prompt additions for using qualified names
- Examples of how to handle ambiguous results
- Guidance on when to use qualified vs unqualified patterns

**Note:** May not be needed if tool descriptions sufficient (Q10 iterative approach)

---

### Task Dependencies (T4.2)

```
T4.2.1 (search tool descriptions) → 1 day
  ↓ (parallel with T4.2.3)
T4.2.2 (info tool descriptions) → 0.5 day
T4.2.3 (system prompt guidance) → 0.5 day (optional)
```

**Execution order:** T4.2.1 → (T4.2.2 + T4.2.3) parallel

**Total:** 1.5 days

---

## Task T4.3: Migration Documentation

**Goal:** Document migration path and breaking changes

**Effort:** 1-2 days
**Dependencies:** All phases complete

### Subtasks

#### T4.3.1: Create migration guide

**Files to create:**
- `docs/QUALIFIED_NAME_MIGRATION.md`

**Content:**
```markdown
# Migration Guide: Qualified Name Support

## Overview

Qualified name support (schema v9-10) adds namespace information to all
search results. This guide helps users migrate from unqualified names.

## Breaking Changes

### 1. Cache Invalidation (Auto-handled)

**What happens:**
- Schema version changed: 8 → 10
- Old cache automatically deleted and recreated
- Re-indexing required (one-time)

**What you need to do:**
- Nothing (automatic)
- First startup after upgrade will re-index project

**Time estimate:**
- Small projects (<1000 files): 1-2 minutes
- Medium projects (1000-5000 files): 5-10 minutes
- Large projects (>5000 files): 15-30 minutes

### 2. Result Format Changes

**Before (schema v8):**
```json
{
  "name": "View",
  "kind": "class",
  "file": "view.cpp"
}
```

**After (schema v10):**
```json
{
  "name": "View",
  "qualified_name": "app::ui::View",  // NEW
  "namespace": "app::ui",              // NEW
  "kind": "class",
  "file": "view.cpp"
}
```

**Impact:**
- Existing code reading results may need updates
- New fields optional (backward compatible)

### 3. Search Behavior Enhancement

**No breaking changes**, only additions:

**Before:**
```python
# Only unqualified search worked
results = search_classes("View")  # All View classes
```

**After:**
```python
# Both unqualified AND qualified work
results = search_classes("View")      # All View classes (same as before)
results = search_classes("ui::View")  # Only View in ui (NEW)
results = search_classes("::View")    # Only global View (NEW)
```

## Migration Steps

### For End Users

1. **Update clang_index_mcp:**
   ```bash
   pip install --upgrade clang_index_mcp
   ```

2. **Restart MCP server:**
   - Server will detect schema change
   - Automatically re-index project
   - Wait for completion

3. **Verify:**
   ```python
   results = search_classes("YourClass")
   print(results[0]["qualified_name"])  # Should show full path
   ```

### For Developers

1. **Update code reading search results:**
   ```python
   # Before:
   name = result["name"]

   # After (backward compatible):
   qualified_name = result.get("qualified_name", result["name"])
   namespace = result.get("namespace", "")
   ```

2. **Use qualified patterns for precision:**
   ```python
   # More precise queries
   ui_config = search_classes("ui::Config")
   core_config = search_classes("core::Config")
   ```

3. **Update tests:**
   - Add assertions for qualified_name
   - Test pattern matching behavior

## Rollback (if needed)

**Not supported.** Schema v10 is not backward compatible with v8.

If you need to rollback:
1. Downgrade clang_index_mcp version
2. Delete .mcp_cache/ directory
3. Restart (will recreate v8 cache)

## FAQ

**Q: Will my old queries break?**
A: No. Unqualified patterns still work exactly as before.

**Q: Do I have to use qualified names?**
A: No. Qualified patterns are optional for more precise queries.

**Q: How long does re-indexing take?**
A: Depends on project size. See estimates in "Breaking Changes" section.

**Q: Can I skip re-indexing?**
A: No. Schema change requires cache recreation.
```

**Validation:**
- Clear migration steps
- All breaking changes documented
- Rollback procedure explained

---

#### T4.3.2: Update CHANGELOG.md

**Files to modify:**
- `CHANGELOG.md`

**Content:**
```markdown
## [Unreleased] - Qualified Name Support

### Added

- **Qualified name support across all MCP tools** (Issues #98, #100, #102, #85)
  - Store and return fully qualified names (e.g., "ns1::ns2::Class")
  - Component-based suffix matching for search patterns
  - Leading `::` for exact global namespace match
  - Regex pattern support for advanced queries
  - Template arguments preserve namespace qualification
  - Anonymous namespace representation
  - Nested class qualified names

- **Function overload metadata** (F4)
  - `is_template_specialization: bool` field
  - `total_overloads` metadata in responses
  - Clear distinction between templates, specializations, and overloads

- **Performance optimizations**
  - Optimized SQL queries based on pattern type
  - FTS5 indexes for qualified name search
  - <100ms query latency (tested on 500K+ symbols)

### Changed

- **Schema version: 8 → 10** (auto-recreation on upgrade)
- **Result format:** Added `qualified_name` and `namespace` fields
- **MCP tool descriptions:** Updated for lightweight LLM comprehension

### Fixed

- Namespace ambiguity (Issues #98, #100, #102) - 100% resolved
- Search pattern failures with qualified names - 100% resolved
- Template specialization ambiguity (Issue #85) - 100% resolved

### Migration

See `docs/QUALIFIED_NAME_MIGRATION.md` for upgrade guide.

**Breaking changes:**
- Cache invalidation required (automatic)
- Schema v10 not backward compatible with v8

**Timeline:** 4-6 weeks development
**Test coverage:** >90%
```

**Validation:**
- All features documented
- Breaking changes highlighted
- Migration guide referenced

---

#### T4.3.3: Update README.md examples

**Files to modify:**
- `README.md`

**Changes:**
- Update search examples to show qualified patterns
- Add examples of qualified_name in results
- Reference new features

**Example:**
```markdown
### Search Examples

**Find classes by name:**
```python
# Unqualified search
results = search_classes("Config")
# Returns: [{"name": "Config", "qualified_name": "app::Config", ...}, ...]

# Qualified search (more precise)
ui_config = search_classes("ui::Config")
core_config = search_classes("core::Config")

# Exact global namespace match
global_config = search_classes("::Config")
```
```

**Validation:**
- Examples accurate
- New features showcased
- Easy to understand

---

### Task Dependencies (T4.3)

```
T4.3.1 (migration guide) → 1 day
  ↓ (parallel with below)
T4.3.2 (CHANGELOG) → 0.5 day
T4.3.3 (README update) → 0.5 day
```

**Execution order:** T4.3.1 → (T4.3.2 + T4.3.3) parallel

**Total:** 1.5 days

---

## Phase 4 Execution Plan

```
T4.1 (Integration Tests) → 2.5 days
  ↓ (can overlap with below)
T4.2 (Tool Descriptions) → 1.5 days
  ↓
T4.3 (Migration Docs) → 1.5 days
  ↓
Final Review & Polish → 1 day
```

**Total:** 5-6 days (1 week)

**Overlap opportunity:** T4.2 can start while T4.1 in progress

---

# Complete Implementation Timeline

## Overall Schedule

| Week | Phase | Tasks | Status |
|------|-------|-------|--------|
| 1-2 | Phase 1 | T1.1, T1.2, T1.3, T3.2 | Foundation complete |
| 3-4 | Phase 2 | T2.1, T2.2, T2.3 | Search working |
| 4 | Phase 3 | T3.3 | Overload metadata (can overlap Phase 2) |
| 5-6 | Phase 4 | T4.1, T4.2, T4.3 | Production-ready |

**Total:** 4-6 weeks

## Critical Path

```
START
  ↓
Phase 1 (2-3 weeks)
  ↓
Phase 2 (1-2 weeks) ← Phase 3 can run in parallel
  ↓
Phase 4 (1 week)
  ↓
DONE
```

## Parallelization Opportunities

### Within Phase 1:
- **T1.2** (schema) starts in parallel with **T1.1.1-T1.1.2** (extraction helpers)
- **Saves:** ~1 day

### Within Phase 1 (OPTIMIZATION):
- **T3.2.1** immediately after **T1.1.4** (code locality)
- **Saves:** ~1 day (context switching)

### Within Phase 2:
- **T2.2.1-T2.2.4** (search tools) all in parallel
- **Saves:** ~2 days

### Between Phases:
- **Phase 3** can start after Phase 1, run parallel with Phase 2
- **Saves:** ~2-3 days

### Within Phase 4:
- **T4.1.2, T4.1.3** parallel with T4.1.1
- **T4.2.2, T4.2.3** parallel with T4.2.1
- **T4.3.2, T4.3.3** parallel with T4.3.1
- **Saves:** ~1 day

**Total parallelization savings:** ~6-8 days
**Original estimate:** 6-8 weeks
**Optimized timeline:** 4-6 weeks

---

# Risk Analysis & Mitigation

## Technical Risks

### Risk 1: Performance degradation from qualified name matching

**Likelihood:** Low
**Impact:** Medium

**Mitigation:**
- Optimized SQL queries based on pattern type (T2.1.3)
- FTS5 indexes on qualified_name field
- Performance benchmarks in Phase 4 (T4.1.2)
- Target: <100ms per query (Q6 decision)

### Risk 2: libclang qualified name extraction edge cases

**Likelihood:** Medium
**Impact:** Low

**Mitigation:**
- Extensive edge case testing (T4.1.3)
- Validated core assumptions with experiments (TC4, TC5)
- Fallback to cursor.spelling if qualified name fails

### Risk 3: Schema migration issues

**Likelihood:** Low
**Impact:** High

**Mitigation:**
- Auto-recreation strategy (Q9 decision)
- Clear migration documentation (T4.3.1)
- Test schema upgrade path
- Rollback procedure documented

## Schedule Risks

### Risk 4: Underestimated complexity in pattern matching

**Likelihood:** Medium
**Impact:** Medium

**Mitigation:**
- Detailed task breakdown (T2.1.1-T2.1.3)
- Start with simple cases, iterate
- Performance benchmarks catch issues early
- Buffer time in Phase 2 estimate (1-2 weeks)

### Risk 5: Scope creep from Q11, Q12

**Likelihood:** Low
**Impact:** High

**Mitigation:**
- Q11, Q12 explicitly out of scope
- Separate research tracks documented
- Focus on F1-F7 only
- Defer template function search and type alias support

---

# Success Criteria

## Phase 1 Success Criteria

- [ ] Qualified names extracted for all symbol types
- [ ] Schema version 9 applied successfully
- [ ] All query methods return qualified_name and namespace fields
- [ ] Template base classes store canonical qualified types
- [ ] Anonymous namespaces represented correctly
- [ ] Nested classes have full qualified names
- [ ] Backward compatibility maintained
- [ ] Integration tests pass

## Phase 2 Success Criteria

- [ ] Component-based suffix matching works correctly
- [ ] Leading `::` exact match implemented
- [ ] Regex patterns supported
- [ ] All search tools accept qualified patterns
- [ ] Backward compatibility maintained
- [ ] Query performance <100ms
- [ ] Integration tests pass

## Phase 3 Success Criteria

- [ ] `is_template_specialization` field available
- [ ] Template detection logic accurate (validated by tests)
- [ ] `total_overloads` metadata in responses
- [ ] Schema version 10 applied successfully
- [ ] Integration tests pass

## Phase 4 Success Criteria

- [ ] Integration tests: >90% code coverage
- [ ] Performance benchmarks: all queries <100ms
- [ ] Edge case tests pass
- [ ] Tool descriptions updated and tested with lightweight LLMs
- [ ] Migration guide complete and accurate
- [ ] CHANGELOG and README updated
- [ ] No critical bugs

## Overall Success Criteria

- [ ] All 6 in-scope problems (P1-P5, P8) solved
- [ ] Features F1-F7 complete and working
- [ ] Production-ready (tests, docs, migration guide)
- [ ] Performance acceptable (<100ms queries)
- [ ] Lightweight LLM compatibility validated
- [ ] Timeline: 4-6 weeks achieved

---

# Appendix: File Change Summary

## Files to Create

- `tests/test_qualified_name_integration.py`
- `tests/test_qualified_name_performance.py`
- `docs/QUALIFIED_NAME_MIGRATION.md`
- `docs/SYSTEM_PROMPT_GUIDANCE.md` (optional)

## Files to Modify

### Core Logic
- `mcp_server/cpp_analyzer.py` (major: extraction, search)
- `mcp_server/search_engine.py` (major: pattern matching)
- `mcp_server/symbol_info.py` (minor: fields)

### Storage
- `mcp_server/schema.sql` (major: schema v9-10)
- `mcp_server/sqlite_cache_backend.py` (major: storage, queries)

### API
- `mcp_server/cpp_mcp_server.py` (minor: tool descriptions)

### Documentation
- `README.md` (minor: examples)
- `CHANGELOG.md` (major: new section)

## Schema Versions

- **v8 → v9:** Add qualified_name, namespace fields (Phase 1)
- **v9 → v10:** Add is_template_specialization field (Phase 3)

---

**Document Version:** 2.0
**Last Updated:** 2026-01-08
**Status:** Complete - All phases detailed, optimized, ready for implementation
**Next Step:** Review plan, begin Phase 1 execution
