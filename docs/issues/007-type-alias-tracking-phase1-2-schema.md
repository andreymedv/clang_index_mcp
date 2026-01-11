# Type Alias Tracking - Phase 1.2 Schema Design

**Related Issue**: [007-type-alias-tracking.md](007-type-alias-tracking.md)
**Requirements**: [007-type-alias-tracking-requirements.md](007-type-alias-tracking-requirements.md)
**Investigation**: [007-type-alias-tracking-phase1-investigation.md](007-type-alias-tracking-phase1-investigation.md)
**Beads Issue**: cplusplus_mcp-3pd
**Date**: 2026-01-11
**Status**: Schema design complete ✅

---

## Executive Summary

**Result**: ✅ **Database schema designed and validated**

**Schema version**: Updated from 10.1 → **11.0**
**New table**: `type_aliases` with 7 indexes
**Breaking change**: Yes (automatic recreation on version mismatch)

**Files modified**:
- `mcp_server/schema.sql` - added type_aliases table, updated version to 11.0
- `mcp_server/sqlite_cache_backend.py` - CURRENT_SCHEMA_VERSION = "11.0"

**Validation**: ✅ Schema syntax validated with SQLite
**Next step**: Phase 1.3 (Implementation)

---

## Schema Design

### Table: `type_aliases`

```sql
CREATE TABLE IF NOT EXISTS type_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias_name TEXT NOT NULL,           -- Short name (e.g., "WidgetAlias", "ErrorCallback")
    qualified_name TEXT NOT NULL,       -- Fully qualified (e.g., "foo::WidgetAlias", "bar::ErrorCallback")
    target_type TEXT NOT NULL,          -- Immediate target (e.g., "Widget", "AliasOne" in chains)
    canonical_type TEXT NOT NULL,       -- Final resolved type (e.g., "RealClass" for A→B→RealClass)
    file TEXT NOT NULL,                 -- File where alias is defined
    line INTEGER NOT NULL,              -- Line number
    column INTEGER NOT NULL,            -- Column number
    alias_kind TEXT NOT NULL,           -- 'using' or 'typedef'
    namespace TEXT DEFAULT '',          -- Namespace portion (e.g., "foo" from "foo::WidgetAlias")
    is_template_alias BOOLEAN NOT NULL DEFAULT 0,  -- True for template aliases (Phase 2, not v11.0)
    created_at REAL NOT NULL,           -- Unix timestamp

    -- Unique constraint: one alias declaration per location
    UNIQUE(file, line, column)
);
```

---

## Field Descriptions

| Field | Type | Purpose | Example |
|-------|------|---------|---------|
| `id` | INTEGER PK | Auto-incrementing unique ID | 1, 2, 3... |
| `alias_name` | TEXT | Short name as written in code | "WidgetAlias" |
| `qualified_name` | TEXT | Fully qualified name with namespace | "foo::WidgetAlias" |
| `target_type` | TEXT | Immediate target (for chain tracking) | "Widget" or "AliasOne" |
| `canonical_type` | TEXT | Final resolved type (for search unification) | "Widget" or "RealClass" |
| `file` | TEXT | Absolute path to definition file | "/path/to/file.h" |
| `line` | INTEGER | Line number | 42 |
| `column` | INTEGER | Column number | 10 |
| `alias_kind` | TEXT | Type of alias declaration | "using" or "typedef" |
| `namespace` | TEXT | Namespace portion (extracted from qualified_name) | "foo" from "foo::Bar" |
| `is_template_alias` | BOOLEAN | Template alias flag (Phase 2, always 0 in v11.0) | 0 (false) |
| `created_at` | REAL | Unix timestamp when indexed | julianday('now') |

---

## Key Design Decisions

### Decision 1: Separate Table vs Extending symbols

**Chosen**: New `type_aliases` table (not extending `symbols`)

**Rationale**:
1. ✅ **Clean separation of concerns**: Aliases are conceptually different from symbols
   - Symbols = actual entities (classes, functions, methods)
   - Aliases = alternate names for types
2. ✅ **Schema clarity**: Dedicated fields without NULL pollution
   - `symbols` table has 20+ fields, most irrelevant for aliases
   - Dedicated table is self-documenting
3. ✅ **Query performance**: Dedicated indexes for alias-specific queries
   - No need to filter `symbols.kind IN ('using', 'typedef')`
   - Smaller table = faster scans
4. ✅ **Future extensibility**: Easy to add alias-specific features
   - Template aliases metadata (Phase 2)
   - Alias usage tracking
   - Cross-reference to symbols using this alias

**Alternative rejected**: Extending `symbols` table with `is_alias`, `alias_target` columns
- Would bloat symbols table
- Most fields (parent_class, base_classes, calls, etc.) irrelevant for aliases
- Harder to maintain

---

### Decision 2: target_type vs canonical_type

**Chosen**: Store **both** `target_type` and `canonical_type`

**Rationale**:

**Example: Alias chain**
```cpp
class RealClass {};
using AliasOne = RealClass;   // target=RealClass, canonical=RealClass
using AliasTwo = AliasOne;    // target=AliasOne, canonical=RealClass
```

**target_type** (immediate):
- Represents the direct alias target as written in code
- Useful for Phase 2: exposing full chain (AliasTwo → AliasOne → RealClass)
- Debugging and diagnostics

**canonical_type** (final):
- libclang resolves chains automatically via `cursor.type.get_canonical()`
- **Critical for Phase 1**: search unification
- All aliases with same canonical type are equivalent for search

**Storage cost**: ~50 bytes per alias (negligible)
**Benefit**: Enables both immediate chain tracking and fast search unification

**Alternative rejected**: Store only canonical_type
- Would work for Phase 1 search unification
- But Phase 2 (exposing chains) would require re-parsing to reconstruct chain
- Cheaper to store now than recompute later

---

### Decision 3: Indexing Strategy

**Chosen**: 7 indexes (6 explicit + 1 automatic)

```sql
-- 1. Automatic index for UNIQUE constraint
UNIQUE(file, line, column)  → sqlite_autoindex_type_aliases_1

-- 2. Lookup by short name
CREATE INDEX idx_type_aliases_name ON type_aliases(alias_name);

-- 3. Lookup by qualified name
CREATE INDEX idx_type_aliases_qualified ON type_aliases(qualified_name);

-- 4. Reverse lookup: canonical → aliases (CRITICAL for search unification)
CREATE INDEX idx_type_aliases_canonical ON type_aliases(canonical_type);

-- 5. File-based queries (incremental analysis)
CREATE INDEX idx_type_aliases_file ON type_aliases(file);

-- 6. Namespace filtering
CREATE INDEX idx_type_aliases_namespace ON type_aliases(namespace);

-- 7. Composite index for common query pattern
CREATE INDEX idx_canonical_name ON type_aliases(canonical_type, alias_name);
```

**Justification**:

**Most critical**: `idx_type_aliases_canonical`
- Powers search unification: "find all aliases for canonical type X"
- Used on every search with type filter
- Expected query: `SELECT alias_name FROM type_aliases WHERE canonical_type = ?`

**Second priority**: `idx_type_aliases_name`, `idx_type_aliases_qualified`
- Direct lookup: "is this name an alias?"
- Used in search expansion logic

**Composite index** `idx_canonical_name`:
- Covers query: "find all alias names for canonical type X"
- Avoids table lookup (covering index)
- Minor optimization, but common query pattern

**Performance overhead**:
- Indexes increase write time slightly (~5-10% for alias insertions)
- But aliases are rare (<1% of symbols), so negligible impact on indexing
- Read performance gains >> write overhead

---

### Decision 4: Namespace Handling

**Chosen**: Store both `alias_name` (short) and `qualified_name` (full)

**Example**:
```cpp
namespace foo {
    using WidgetAlias = Widget;
}
```

**Storage**:
- `alias_name` = "WidgetAlias"
- `qualified_name` = "foo::WidgetAlias"
- `namespace` = "foo"

**Rationale**:
1. **Flexibility**: Can search by short name OR qualified name
2. **Namespace filtering**: Future feature (search within namespace)
3. **Disambiguation**: Multiple namespaces may have same short name
   ```cpp
   namespace foo { using Widget = A; }
   namespace bar { using Widget = B; }  // different aliases, same short name
   ```

**libclang provides**:
- `cursor.spelling` → short name ("WidgetAlias")
- `cursor.type.spelling` → qualified name ("foo::WidgetAlias")
- Trivial to extract namespace from qualified name

**Cost**: ~20 extra bytes per alias (negligible)

---

### Decision 5: Unique Constraint

**Chosen**: `UNIQUE(file, line, column)`

**Rationale**:
- Prevents duplicate alias entries from same location
- Handles incremental re-indexing (re-processing same file)
- libclang guarantees unique location per cursor

**Alternative rejected**: `UNIQUE(qualified_name)`
- Would fail for redeclarations in different files (valid C++)
- File+line+column is more robust

**Behavior on conflict**: `INSERT OR IGNORE` (during indexing)
- Silently skip duplicates (idempotent indexing)

---

### Decision 6: Template Alias Support (Deferred)

**Chosen**: Include `is_template_alias` field, but always 0 in Phase 1

**Rationale**:
- **Phase 1**: Only simple aliases (is_template_alias = 0)
- **Phase 2** (separate task cplusplus_mcp-2h1): Template aliases
- Including field now avoids schema change later

**Example of future use**:
```cpp
template<typename T>
using Ptr = std::shared_ptr<T>;  // is_template_alias = 1
```

Phase 1 implementation will **skip** template aliases (cursor kind check).
Field reserved for future.

---

## Schema Version Management

**Previous version**: 10.1
**New version**: 11.0

**Changes applied**:
1. `mcp_server/schema.sql`:
   - Version comment: `-- Version: 11.0`
   - Changelog entry: `-- Changelog v11.0: Added type_aliases table...`
   - cache_metadata: `('version', '"11.0"', ...)`
   - Added type_aliases table + indexes

2. `mcp_server/sqlite_cache_backend.py`:
   - `CURRENT_SCHEMA_VERSION = "11.0"`

**Automatic recreation**:
- On first run with v11.0, existing v10.1 database will be detected
- `SqliteCacheBackend` will delete old database
- New database created with v11.0 schema
- Project re-indexed automatically

**No migration needed** - development mode auto-recreation pattern.

---

## Validation Results

**Test 1: Schema syntax**
```bash
sqlite3 test.db < schema.sql
Result: ✅ No errors
```

**Test 2: Table structure**
```bash
SELECT sql FROM sqlite_master WHERE type='table' AND name='type_aliases';
Result: ✅ Table created with all fields
```

**Test 3: Indexes created**
```bash
SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='type_aliases';
Result: ✅ All 7 indexes present
```

---

## Integration Points

### For Symbol Extraction (cpp_analyzer.py)

**New method needed**:
```python
def _extract_alias_info(self, cursor) -> dict:
    """Extract type alias information from cursor."""
    # See Phase 1.1 investigation for details
    return {
        'alias_name': cursor.spelling,
        'qualified_name': cursor.type.spelling,
        'target_type': cursor.underlying_typedef_type.spelling,
        'canonical_type': cursor.type.get_canonical().spelling,
        # ... location fields
    }
```

**Collection during indexing**:
```python
# In _process_cursor()
if cursor.kind in (CursorKind.TYPE_ALIAS_DECL, CursorKind.TYPEDEF_DECL):
    if not cursor.is_template_alias():  # Phase 1: skip templates
        alias_info = self._extract_alias_info(cursor)
        self.type_aliases.append(alias_info)
```

---

### For Storage (sqlite_cache_backend.py)

**New methods needed**:
```python
def store_type_aliases(self, aliases: List[dict]):
    """Store type aliases in database."""
    # Batch insert with INSERT OR IGNORE
    pass

def get_aliases_for_canonical(self, canonical_type: str) -> List[str]:
    """Get all alias names that resolve to canonical_type."""
    # SELECT alias_name FROM type_aliases WHERE canonical_type = ?
    pass

def get_canonical_for_alias(self, alias_name: str) -> Optional[str]:
    """Get canonical type for an alias name."""
    # SELECT canonical_type FROM type_aliases WHERE alias_name = ?
    pass
```

---

### For Search Engine (search_engine.py)

**Type expansion logic**:
```python
def _expand_type_query(self, type_name: str) -> List[str]:
    """Expand type to include all equivalent names (aliases and canonical)."""
    # 1. Check if type_name is an alias → get canonical
    canonical = self.cache.get_canonical_for_alias(type_name) or type_name

    # 2. Find all aliases with same canonical
    aliases = self.cache.get_aliases_for_canonical(canonical)

    # 3. Return unique list: [type_name, canonical, *aliases]
    return list(set([type_name, canonical] + aliases))
```

**Usage in search**:
```python
def search_functions(self, pattern, param_type=None, ...):
    if param_type:
        type_variants = self._expand_type_query(param_type)
        # Modify WHERE clause: param_types LIKE any of type_variants
```

---

## Performance Estimates

### Storage Overhead

**Per alias**: ~150-200 bytes
- alias_name: ~20 bytes
- qualified_name: ~40 bytes
- target_type: ~30 bytes
- canonical_type: ~30 bytes
- file: ~50 bytes
- Other fields: ~20 bytes
- Index overhead: ~50 bytes

**Typical project** (5000 files):
- Estimated aliases: 200-500
- Storage: ~100 KB (negligible vs. 50+ MB total cache)

**Large project** (50,000 files):
- Estimated aliases: 2000-5000
- Storage: ~1 MB

**Conclusion**: Negligible storage impact.

---

### Query Performance

**Critical query**: Find aliases for canonical type
```sql
SELECT alias_name FROM type_aliases WHERE canonical_type = ?;
```

**Expected performance** (with idx_type_aliases_canonical):
- 500 aliases: < 1ms (index lookup)
- 5000 aliases: < 5ms

**Search expansion overhead**:
- Lookup canonical: ~0.5ms
- Find aliases: ~1ms
- Total: ~1.5ms per type-filtered search

**Conclusion**: < 2ms overhead per search (acceptable).

---

### Indexing Overhead

**Alias extraction** (per file):
- Process alias cursors: ~0.1ms each
- Typical file: 1-3 aliases
- Overhead: ~0.3ms per file

**Database insertion** (batch):
- 500 aliases in batch: ~10-20ms total
- Amortized: negligible

**Total indexing impact**: < 1% (as predicted in Phase 1.1).

---

## Testing Strategy (Phase 1.4)

### Unit Tests

1. **Schema creation**: Verify table exists with correct fields
2. **Alias insertion**: Test INSERT with valid data
3. **Unique constraint**: Test duplicate prevention
4. **Index usage**: EXPLAIN QUERY PLAN for critical queries

### Integration Tests

1. **Alias extraction**: Parse alias_test.cpp, verify 16 aliases extracted
2. **Storage**: Store aliases, verify counts and data integrity
3. **Lookup queries**: Test get_aliases_for_canonical(), get_canonical_for_alias()
4. **Search unification**: Search for type, verify both alias and canonical found

### Performance Tests

1. **Large dataset**: 5000 aliases, measure query time
2. **Indexing overhead**: Compare indexing time with/without alias extraction

---

## Phase 1.2 Deliverables ✅

- ✅ Database schema designed (`type_aliases` table)
- ✅ Schema updated to v11.0 in schema.sql
- ✅ CURRENT_SCHEMA_VERSION updated in sqlite_cache_backend.py
- ✅ Schema validated (syntax, structure, indexes)
- ✅ Design decisions documented with rationale
- ✅ Integration points identified for Phase 1.3
- ✅ Performance estimates provided

---

## Next Steps

1. ✅ **Phase 1.1 Complete**: libclang investigation
2. ✅ **Phase 1.2 Complete**: Database schema design
3. 🔄 **Phase 1.3**: Implementation
   - Add `_extract_alias_info()` method to CppAnalyzer
   - Implement alias extraction in `_process_cursor()`
   - Add `store_type_aliases()` to SqliteCacheBackend
   - Add lookup methods (`get_aliases_for_canonical()`, etc.)
   - Modify search engine for type expansion
   - Add hybrid response format (`param_types_canonical`)
4. ⏳ **Phase 1.4**: Testing and validation
   - Unit tests for each component
   - Integration tests for end-to-end flow
   - Performance validation

---

## Conclusion

**Phase 1.2 schema design is complete and validated.**

Schema v11.0 provides:
- ✅ Dedicated `type_aliases` table with optimal structure
- ✅ Efficient indexing for search unification
- ✅ Support for both simple aliases (Phase 1) and template aliases (Phase 2)
- ✅ Automatic recreation on version mismatch (no migration code needed)
- ✅ Negligible performance impact (<1% indexing, <2ms search overhead)

**Risk level**: LOW - straightforward schema, validated with SQLite
**Confidence level**: HIGH - all integration points identified

**Ready to proceed to Phase 1.3** (Implementation).

---

**Document version**: 1.0
**Date**: 2026-01-11
**Author**: Claude Code + andrey
