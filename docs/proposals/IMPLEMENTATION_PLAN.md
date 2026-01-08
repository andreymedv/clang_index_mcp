# Qualified Name Support - Implementation Plan

**Status:** 📋 Planning - Ready for Review
**Created:** 2026-01-08
**Based on:** QUALIFIED_NAME_DISCUSSION_LOG.md (Prioritization section)
**Timeline:** 4-6 weeks total

---

## Document Purpose

This document provides a detailed task breakdown and execution plan for implementing qualified name support. It includes:
- Subtask decomposition for all tasks (T1.1 - T4.3)
- File-level change specifications
- Inter-task dependencies and execution order
- Validation criteria for each subtask

**Source documents:**
- Design decisions: `QUALIFIED_NAME_DISCUSSION_LOG.md`
- Proposal overview: `QUALIFIED_NAME_SUPPORT_PROPOSAL.md`

---

## Phase 1: Foundation & Template Support (2-3 weeks)

**Features:** F1 + F5 + F6 + F7
**Tasks:** T1.1, T1.2, T1.3, T3.2

### Overview

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

#### T1.1.1: Add qualified_name extraction to _process_cursor()

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

#### T1.1.2: Implement _get_qualified_name() helper

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
- Template instantiations (qualified name includes template args? NO - see T3.2)
- Operator overloads (include "operator" keyword)

---

#### T1.1.3: Implement _extract_namespace() helper

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

#### T1.1.4: Update SymbolInfo dataclass

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

### Task Dependencies (T1.1)

```
T1.1.2 (_get_qualified_name)
  ↓
T1.1.3 (_extract_namespace)
  ↓
T1.1.4 (SymbolInfo update)
  ↓
T1.1.1 (integrate into _process_cursor)
```

**Execution order:** T1.1.2 → T1.1.3 → T1.1.4 → T1.1.1

**Rationale:** Build helpers first, then integrate into main flow

---

## Task T1.2: Schema Changes

**Goal:** Update SQLite schema to store qualified name fields

**Effort:** 1-2 days
**Dependencies:** T1.1.4 (SymbolInfo structure)

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

#### T1.2.3: Add schema migration (optional, for production)

**Decision:** NOT required for Phase 1 (Q9: auto-recreation acceptable)

**Future consideration:** If migration becomes necessary:
```sql
-- migrations/008_to_009_add_qualified_names.sql
ALTER TABLE symbols ADD COLUMN qualified_name TEXT;
ALTER TABLE symbols ADD COLUMN namespace TEXT;
-- ... update qualified names from name field (best-effort) ...
```

**For Phase 1:** Skip migration, rely on auto-recreation

---

### Task Dependencies (T1.2)

```
T1.2.1 (schema.sql update)
  ↓
T1.2.2 (version bump)
```

**Execution order:** T1.2.1 → T1.2.2

**Note:** Can be done in parallel with T1.1.2-T1.1.3 (independent)

---

## Task T1.3: Storage Updates

**Goal:** Update storage layer to persist qualified name fields

**Effort:** 2-3 days
**Dependencies:** T1.1 (extraction), T1.2 (schema)

### Subtasks

#### T1.3.1: Update SQLiteCacheBackend.store_symbols()

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

#### T1.3.2: Update query methods to return qualified_name

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

#### T1.3.3: Update _extract_symbol_info() in cpp_analyzer.py

**Files to modify:**
- `mcp_server/cpp_analyzer.py` (line ~1200-1300)

**Changes:**
```python
def _extract_symbol_info(self, cursor, file_path) -> SymbolInfo:
    qualified_name = self._get_qualified_name(cursor)  # NEW (from T1.1.2)
    namespace = self._extract_namespace(qualified_name)  # NEW (from T1.1.3)

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

### Task Dependencies (T1.3)

```
T1.1 (extraction helpers) + T1.2 (schema)
  ↓
T1.3.3 (_extract_symbol_info update)
  ↓
T1.3.1 (storage)
  ↓
T1.3.2 (queries)
```

**Execution order:** T1.3.3 → T1.3.1 → T1.3.2

**Critical path:** T1.1 → T1.2 → T1.3

---

## Task T3.2: Template Args Qualification

**Goal:** Store canonical qualified types for template arguments in base classes

**Effort:** 2-3 days
**Dependencies:** T1.1 (qualified name extraction infrastructure)

**Note:** Bundled with Phase 1 to minimize rework (same extraction logic)

### Subtasks

#### T3.2.1: Extract canonical base class types

**Files to modify:**
- `mcp_server/cpp_analyzer.py` (base class extraction in `_process_cursor()`)

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
T1.1.2 (_get_qualified_name helper)
  ↓
T3.2.1 (canonical base class extraction)
  ↓
T3.2.2 (field handling update)
  ↓
T3.2.3 (get_class_info update)
```

**Execution order:** After T1.1.2 complete → T3.2.1 → T3.2.2 → T3.2.3

**Can overlap with:** T1.2 (schema changes, independent)

---

## Phase 1 Integration & Validation

### Phase 1 Complete Deliverables

After completing T1.1, T1.2, T1.3, T3.2:

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

## Phase 1 Task Execution Summary

### Critical Path

```
START
  ↓
T1.1.2 (_get_qualified_name)
  ↓
T1.1.3 (_extract_namespace)
  ↓
T1.1.4 (SymbolInfo update)
  ↓
T1.1.1 (integrate _process_cursor)
  ↓
T1.2.1 (schema.sql) ← CAN START IN PARALLEL with T1.1.2
  ↓
T1.2.2 (version bump)
  ↓
T1.3.3 (_extract_symbol_info)
  ↓
T1.3.1 (storage)
  ↓
T1.3.2 (queries)
  ↓
T3.2.1 (canonical base classes) ← DEPENDS ON T1.1.2
  ↓
T3.2.2 (field handling)
  ↓
T3.2.3 (get_class_info)
  ↓
Phase 1 Integration Testing
  ↓
Phase 1 COMPLETE
```

### Parallel Work Opportunities

**Week 1:**
- **Track A:** T1.1.2 → T1.1.3 → T1.1.4 (extraction helpers)
- **Track B:** T1.2.1 → T1.2.2 (schema changes) **← CAN START IMMEDIATELY**

**Week 2:**
- **Track A:** T1.1.1 (integrate) → T1.3.3 (_extract_symbol_info)
- **Track B:** T3.2.1 (after T1.1.2 done) → T3.2.2

**Week 2-3:**
- T1.3.1 → T1.3.2 (storage + queries)
- T3.2.3 (get_class_info)
- Integration testing

**Estimated effort:** 2-3 weeks (as planned)

---

## Phase 2: Search Capabilities (1-2 weeks)

**Features:** F2 + F3
**Tasks:** T2.1, T2.2, T2.3

### Overview

Phase 2 implements qualified pattern matching on top of Phase 1 infrastructure:
- Component-based suffix matching algorithm
- Leading `::` detection for exact match
- Dual-mode support (qualified + unqualified patterns)
- Update all search tools to use new pattern matching

**Dependency:** Requires Phase 1 complete (qualified names in database)

### Task Breakdown

*(Detailed subtask breakdown to be added after Phase 1 planning review)*

**High-level tasks:**
- T2.1: Pattern Matching Engine (search_engine.py)
- T2.2: Update Search Tools (cpp_mcp_server.py, cpp_analyzer.py)
- T2.3: Dual-Mode Support (backward compatibility)

---

## Phase 3: Overload Metadata (2-3 days)

**Features:** F4
**Tasks:** T3.3

### Overview

Phase 3 adds metadata to distinguish function overloads:
- `is_template_specialization: bool` field
- Detection via `cursor.kind` + displayname analysis (validated by TC5)
- `total_overloads` metadata
- Independent from Phase 1/2 (can be done in parallel with Phase 2)

### Task Breakdown

*(Detailed subtask breakdown to be added after Phase 1 planning review)*

**High-level task:**
- T3.3: Function Overload Metadata (cpp_analyzer.py, symbol_info.py)

---

## Phase 4: Testing & Documentation (1 week)

**Tasks:** T4.1, T4.2, T4.3

### Overview

Phase 4 completes the feature with comprehensive testing and documentation:
- Integration tests for all features
- Update MCP tool descriptions for lightweight LLMs
- Migration documentation and breaking changes guide

### Task Breakdown

*(Detailed subtask breakdown to be added after Phase 1-3 complete)*

---

## Next Steps

1. **Review Phase 1 task breakdown** (this document)
2. **Validate subtask dependencies and execution order**
3. **Identify optimization opportunities** (parallel work, task reordering)
4. **Begin Phase 1 implementation** according to plan

---

**Document Version:** 1.0
**Last Updated:** 2026-01-08
**Status:** Phase 1 detailed, Phase 2-4 high-level (to be expanded)
