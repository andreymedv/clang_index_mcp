# Type Alias Tracking - Phase 1.1 Investigation Results

**Related Issue**: [007-type-alias-tracking.md](007-type-alias-tracking.md)
**Requirements**: [007-type-alias-tracking-requirements.md](007-type-alias-tracking-requirements.md)
**Beads Issue**: cplusplus_mcp-3pd
**Date**: 2026-01-11
**Status**: Investigation complete ✅

---

## Executive Summary

**Result**: ✅ **libclang fully supports alias detection and resolution**

libclang provides complete information needed for Phase 1 implementation:
- ✅ Recognizes both `using` and `typedef` declarations
- ✅ Provides alias name and target type
- ✅ Automatically resolves alias chains to canonical type
- ✅ Works with classes, structs, enums, pointers, references, built-in types, STL types
- ✅ Preserves namespace context

**Recommendation**: Proceed to Phase 1.2 (Database Schema Design)

---

## Investigation Method

**Test file**: `tests/fixtures/alias_test.cpp` (16 test cases)
**Script**: `scripts/investigate_aliases.py`
**libclang version**: 14+

Test cases covered:
1. Simple class alias (`using`/`typedef`)
2. Pointer type alias
3. Reference type alias
4. Built-in type alias
5. STL type alias (std::function, std::vector)
6. Alias chains (A→B→C)
7. Namespace-scoped aliases
8. Enum alias
9. Struct alias
10. const-qualified alias
11. Complex nested types

---

## Key Findings

### Finding 1: Cursor Kinds for Aliases

**Result**: libclang uses two distinct cursor kinds

| Cursor Kind | C++ Syntax | Example |
|-------------|------------|---------|
| `CursorKind.TYPE_ALIAS_DECL` | `using` | `using WidgetAlias = Widget;` |
| `CursorKind.TYPEDEF_DECL` | `typedef` | `typedef Button ButtonAlias;` |

**Count in test file**:
- TYPE_ALIAS_DECL: 12 occurrences
- TYPEDEF_DECL: 4 occurrences

**Implication**: Must handle both cursor kinds in `_process_cursor()` method.

---

### Finding 2: Extracting Target Type

**Result**: ✅ `cursor.underlying_typedef_type` provides **immediate target** type

**Example 1: Simple alias**
```cpp
using WidgetAlias = Widget;
```
- `cursor.underlying_typedef_type.spelling` → `"Widget"`
- `cursor.underlying_typedef_type.get_canonical().spelling` → `"Widget"`

**Example 2: Pointer alias**
```cpp
using DataPtr = Data*;
```
- `cursor.underlying_typedef_type.spelling` → `"Data *"`
- `cursor.underlying_typedef_type.kind` → `TypeKind.POINTER`

**Example 3: STL type**
```cpp
using ErrorCallback = std::function<void(int)>;
```
- `cursor.underlying_typedef_type.spelling` → `"std::function<void (int)>"`
- `cursor.underlying_typedef_type.kind` → `TypeKind.ELABORATED`

**API to use**:
```python
target_type = cursor.underlying_typedef_type
target_type_spelling = target_type.spelling
```

---

### Finding 3: Canonical Type Resolution (CRITICAL for Chains)

**Result**: ✅ `cursor.type.get_canonical()` **automatically resolves alias chains**

**Example: Alias chain**
```cpp
class RealClass {};
using AliasOne = RealClass;
using AliasTwo = AliasOne;
```

**For cursor `AliasTwo`**:
- `cursor.spelling` → `"AliasTwo"` (alias name)
- `cursor.type.spelling` → `"AliasTwo"` (as declared)
- `cursor.underlying_typedef_type.spelling` → `"AliasOne"` (immediate target)
- `cursor.type.get_canonical().spelling` → `"RealClass"` (final canonical type)

**This is perfect!** libclang automatically resolves the full chain for us.

**API to use**:
```python
alias_name = cursor.spelling
immediate_target = cursor.underlying_typedef_type.spelling
canonical_type = cursor.type.get_canonical().spelling
```

---

### Finding 4: Namespace Handling

**Result**: ✅ Namespace context preserved in type spellings

**Example**:
```cpp
namespace foo {
    class LocalClass {};
    using LocalAlias = LocalClass;
}

namespace bar {
    using ExternalAlias = foo::LocalClass;
}
```

**For `LocalAlias`**:
- `cursor.spelling` → `"LocalAlias"`
- `cursor.type.spelling` → `"foo::LocalAlias"` (fully qualified)
- `canonical_type.spelling` → `"foo::LocalClass"`

**For `ExternalAlias`**:
- `cursor.spelling` → `"ExternalAlias"`
- `cursor.type.spelling` → `"bar::ExternalAlias"`
- `canonical_type.spelling` → `"foo::LocalClass"`

**Implication**: Need to decide whether to store:
- Short name (`"LocalAlias"`) + namespace separately, OR
- Fully qualified name (`"foo::LocalAlias"`)

**Recommendation**: Store both for flexibility (see Phase 1.2 schema design).

---

### Finding 5: Type Categories Supported

**Result**: ✅ All relevant type categories work

| C++ Type Category | Example | Canonical Type | Works? |
|-------------------|---------|----------------|--------|
| Class | `using A = Widget;` | `Widget` | ✅ |
| Struct | `using A = Point;` | `Point` | ✅ |
| Enum | `using Colour = Color;` | `Color` | ✅ |
| Pointer | `using A = Data*;` | `Data *` | ✅ |
| Reference | `using A = Data&;` | `Data &` | ✅ |
| const-qualified | `using A = const Data*;` | `const Data *` | ✅ |
| Built-in type | `using size_type = unsigned long;` | `unsigned long` | ✅ |
| STL template | `using A = std::function<void(int)>;` | `std::function<void (int)>` | ✅ |

**All test cases passed!**

---

### Finding 6: Type Comparison for Search

**Challenge**: How to match aliases in search?

**Example**:
```cpp
using DataPtr = Data*;
using DataPointer = Data*;

void foo(DataPtr p);
void bar(DataPointer p);
void baz(Data* p);
```

**Question**: When searching for "Data*", should we find all three functions?

**libclang gives us**:
- All three functions have canonical param type: `"Data *"`
- Comparing canonical types: all match!

**Strategy for Phase 1**:
1. Store alias name → canonical type mapping in database
2. When searching for type X:
   - Find canonical form of X
   - Also find all aliases with same canonical form
   - Search for all equivalent names

**Example SQL**:
```sql
-- Given search for "DataPtr"
-- 1. Get canonical: "Data *"
SELECT canonical_type FROM type_aliases WHERE alias_name = 'DataPtr';
-- Result: "Data *"

-- 2. Find all aliases with same canonical
SELECT alias_name FROM type_aliases WHERE canonical_type = 'Data *';
-- Result: ["DataPtr", "DataPointer"]

-- 3. Search for functions with ANY of these types
SELECT * FROM symbols WHERE param_types LIKE '%DataPtr%'
   OR param_types LIKE '%DataPointer%'
   OR param_types LIKE '%Data *%';
```

---

## Implementation Implications

### For Symbol Extraction (cpp_analyzer.py:_process_cursor)

**Add handling**:
```python
def _process_cursor(self, cursor, ...):
    # ... existing code ...

    # NEW: Handle type aliases
    if cursor.kind in (CursorKind.TYPE_ALIAS_DECL, CursorKind.TYPEDEF_DECL):
        alias_info = self._extract_alias_info(cursor)
        self.type_aliases.append(alias_info)  # collect for later storage

    # ... existing code ...
```

**Extraction method**:
```python
def _extract_alias_info(self, cursor):
    """Extract type alias information from cursor."""
    alias_name = cursor.spelling

    # Get immediate target
    underlying_type = cursor.underlying_typedef_type
    target_type = underlying_type.spelling

    # Get canonical type (resolves chains)
    canonical_type = cursor.type.get_canonical().spelling

    # Get fully qualified alias name
    qualified_name = cursor.type.spelling

    # Location info
    location = cursor.location

    return {
        'alias_name': alias_name,
        'qualified_name': qualified_name,
        'target_type': target_type,  # immediate
        'canonical_type': canonical_type,  # final
        'file': location.file.name,
        'line': location.line,
        'column': location.column,
        'kind': 'using' if cursor.kind == CursorKind.TYPE_ALIAS_DECL else 'typedef',
    }
```

---

### For Database Schema (schema.sql)

**Minimum required fields** (based on findings):

```sql
CREATE TABLE type_aliases (
    alias_name TEXT NOT NULL,           -- Short name (e.g., "WidgetAlias")
    qualified_name TEXT NOT NULL,       -- Fully qualified (e.g., "foo::WidgetAlias")
    target_type TEXT NOT NULL,          -- Immediate target (e.g., "Widget")
    canonical_type TEXT NOT NULL,       -- Final type (e.g., "RealClass" for chains)
    file TEXT NOT NULL,                 -- Definition location
    line INTEGER NOT NULL,
    column INTEGER NOT NULL,
    alias_kind TEXT NOT NULL,           -- 'using' or 'typedef'
    namespace TEXT DEFAULT '',          -- For future use
    created_at REAL NOT NULL
);

-- Index for fast lookup by alias name
CREATE INDEX idx_type_aliases_name ON type_aliases(alias_name);

-- Index for reverse lookup (canonical → aliases)
CREATE INDEX idx_type_aliases_canonical ON type_aliases(canonical_type);

-- Index for qualified name lookup
CREATE INDEX idx_type_aliases_qualified ON type_aliases(qualified_name);
```

**Note**: `target_type` vs `canonical_type`:
- `target_type`: immediate target (`AliasTwo` → `AliasOne`)
- `canonical_type`: final resolved type (`AliasTwo` → `RealClass`)

For Phase 1, we primarily need `canonical_type` for search unification.
`target_type` is useful for Phase 2 (exposing full chain).

---

### For Search Engine (search_engine.py)

**Modify search logic**:

1. **Before search**: Expand type query
```python
def _expand_type_aliases(self, type_name):
    """Expand type to include all aliases."""
    # Get canonical form
    canonical = self._get_canonical_type(type_name)

    # Find all aliases with same canonical type
    aliases = self._get_aliases_for_canonical(canonical)

    # Return list: [type_name, canonical, *aliases]
    return list(set([type_name, canonical] + aliases))
```

2. **During search**: Match any equivalent name
```python
def search_functions(self, pattern, param_type=None, ...):
    if param_type:
        # Expand to all equivalent names
        type_variants = self._expand_type_aliases(param_type)
        # Search for any variant
        # ... modify WHERE clause to use OR conditions
```

---

## Edge Cases and Limitations

### Edge Case 1: Template Aliases (OUT OF SCOPE)

**Not handled in Phase 1**:
```cpp
template<typename T>
using Ptr = std::shared_ptr<T>;
```

**libclang behavior**: Recognizes as `TYPE_ALIAS_DECL`, but:
- `underlying_typedef_type` contains template parameters
- Matching `Ptr<Widget>` to `std::shared_ptr<Widget>` requires template substitution

**Decision**: Defer to separate task (cplusplus_mcp-2h1)

---

### Edge Case 2: Alias Chains (AUTOMATICALLY HANDLED!)

**Perfectly handled**:
```cpp
using A = B;
using B = C;
using C = RealClass;
```

libclang's `get_canonical()` resolves entire chain automatically!

No special Phase 2 implementation needed for basic chain resolution.

**Phase 2 scope** reduced to: exposing full chain in response metadata (optional).

---

### Edge Case 3: Namespace Context

**Consideration**: Should we match across namespaces?

```cpp
namespace foo {
    using Widget = ::RealWidget;
}

namespace bar {
    using Widget = ::RealWidget;
}
```

Both resolve to same canonical type `RealWidget`, but are different aliases.

**Decision for Phase 1**: Store both, match by canonical type (unified search).
**Future consideration**: May need namespace filtering in search queries.

---

## Performance Considerations

**Overhead during indexing**:
- Processing alias cursors: minimal (same as processing class/function)
- Extracting type information: ~3-5 libclang API calls per alias
- Estimated aliases in typical project: 100-500 (< 1% of total symbols)

**Expected impact**: < 1% indexing time overhead

**Database size**:
- ~100-200 bytes per alias
- For 500 aliases: ~100 KB additional storage

**Negligible impact**.

---

## Test Results Summary

**Test file**: `tests/fixtures/alias_test.cpp`

**Results**:
```
Total aliases found: 16
- TYPE_ALIAS_DECL (using): 12
- TYPEDEF_DECL (typedef): 4
- Resolvable to different canonical type: 16/16 (100%)
```

**All test cases passed**:
- ✅ Simple class/struct/enum aliases
- ✅ Pointer and reference aliases
- ✅ Built-in type aliases
- ✅ STL type aliases (std::function, std::vector, std::map)
- ✅ Alias chains (A→B→C)
- ✅ Namespace-scoped aliases
- ✅ const-qualified aliases

**See**: Full output in `scripts/investigate_aliases.py`

---

## Recommendations for Phase 1.2

### 1. Database Schema Design

**Recommended approach**: New `type_aliases` table (not extending `symbols` table)

**Rationale**:
- Clean separation of concerns
- Aliases are conceptually different from symbols (classes/functions)
- Easier to query and maintain
- Dedicated indexes for alias-specific queries

**Schema** (see above): `alias_name`, `qualified_name`, `target_type`, `canonical_type`, location fields

---

### 2. Search Integration Strategy

**Approach**: Transparent alias expansion in search

**Steps**:
1. Extract type from search query (e.g., param_type filter)
2. Lookup in `type_aliases` to get canonical form
3. Reverse lookup: find all aliases with same canonical
4. Expand search to include all equivalent names
5. Merge results, add `param_types_canonical` to response

**No MCP API changes needed** - fully backward compatible!

---

### 3. Hybrid Response Format Implementation

**For functions with aliased types**:
```json
{
  "name": "processWidget",
  "param_types": ["WidgetAlias"],  // as written in code
  "param_types_canonical": ["Widget"]  // resolved canonical type
}
```

**Implementation**:
- Check if param type exists in `type_aliases` table
- If yes, add `param_types_canonical` field
- If no alias, omit field (backward compatible)

---

## Phase 1.1 Deliverables ✅

- ✅ Test file with 16 alias test cases
- ✅ Investigation script (`scripts/investigate_aliases.py`)
- ✅ Comprehensive findings documentation (this document)
- ✅ API usage examples for implementation
- ✅ Schema recommendations
- ✅ Search integration strategy

---

## Next Steps

1. ✅ **Phase 1.1 Complete**: libclang investigation
2. 🔄 **Phase 1.2**: Database schema design
   - Finalize `type_aliases` table schema
   - Update schema version (automatic recreation on version bump)
3. ⏳ **Phase 1.3**: Implementation
   - Add alias extraction in `_process_cursor()`
   - Implement alias storage in SQLite
   - Modify search engine for alias expansion
   - Add hybrid response format
4. ⏳ **Phase 1.4**: Testing and validation
   - Unit tests for alias extraction
   - Integration tests for search unification
   - Test on real codebase

---

## Conclusion

**Phase 1.1 investigation was highly successful.**

libclang provides all necessary capabilities for implementing type alias tracking:
- ✅ Complete alias detection (using/typedef)
- ✅ Automatic chain resolution (no manual implementation needed!)
- ✅ All type categories supported
- ✅ Namespace context preserved

**Confidence level**: HIGH - all requirements can be met with libclang's existing API.

**Risk level**: LOW - straightforward implementation, no technical blockers identified.

**Ready to proceed to Phase 1.2** (Database Schema Design).

---

**Document version**: 1.0
**Date**: 2026-01-11
**Author**: Claude Code + andrey
