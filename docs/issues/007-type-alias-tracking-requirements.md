# Type Alias Tracking - Requirements (Phase 0)

**Related Issue**: [007-type-alias-tracking.md](007-type-alias-tracking.md)
**Beads Issue**: cplusplus_mcp-3pd
**Date**: 2026-01-11
**Status**: Requirements defined, ready for implementation

---

## Core Functional Goals

### Goal 1: Transparent Automatic Unification
**Problem**: LLM searches for functions with type `Foo`, but misses functions using alias `Bar` where `using Bar = Foo`.

**Solution**: Automatic search unification
- When searching for type `Foo`, automatically include results with all equivalent type names (aliases)
- Works in both directions: search by alias finds canonical type, search by canonical finds aliases
- Applies to: `search_functions`, `search_classes`, `search_symbols`, and any MCP tool filtering by types

**Example**:
```cpp
class Widget {};
using WidgetPtr = Widget*;

void process(Widget* w);
void handle(WidgetPtr w);
```

**Search**: `search_functions("", param_type="Widget*")`
**Result**: Returns BOTH `process` and `handle` functions

---

### Goal 2: Hybrid Response Format (Original + Canonical)
**Problem**: Users and LLMs think in terms of code as written, but need canonical types for comparison and analysis.

**Solution**: Return both forms in responses
```json
{
  "name": "handleError",
  "param_types": ["ErrorCallback"],  // as written in source code
  "param_types_canonical": ["std::function<void(const Error&)>"]  // only if alias exists
}
```

**Rationale**:
- Preserves code semantics (shows `ErrorCallback` as in source)
- Enables type comparison (LLM can use canonical form)
- Compact (canonical field only when needed)
- Follows compiler/debugger convention (show canonical on demand)

---

### Goal 3: Alias Chain Resolution
**Problem**: Multi-level aliases are opaque
```cpp
using A = B;
using B = C;
class C {};
```

**Solution**: Resolve chains to ultimate type
- `A` → `B` → `C` (chain)
- Canonical type for `A` is `C` (final resolution)

**Note**: Full chain exposure in responses deferred to Phase 2

---

## Out of Scope (Deferred Features)

### Template Aliases (Separate Task)
**Deferred to**: cplusplus_mcp-2h1 (Template Alias Tracking and Resolution)

```cpp
template<typename T>
using Ptr = std::shared_ptr<T>;

void foo(Ptr<Widget> p);  // matches std::shared_ptr<Widget>?
```

**Complexity**: Requires template substitution, significantly more complex than simple aliases
**Decision**: Implement basic aliases first, add template support later

---

### Dedicated Alias Query Tool
**Decision**: NOT implementing separate MCP tool for alias queries

**Rationale**:
- Automatic unification makes it unnecessary for most cases
- Hybrid response format provides enough information
- Can add later if user feedback indicates need

---

## Implementation Strategy: Phased Approach (Variant C)

### Phase 1: Simple Aliases (CURRENT SCOPE)
**Target cases**:
```cpp
class RealClass {};
using Alias = RealClass;  // simple using
typedef RealClass Alias2;  // simple typedef
```

**Deliverables**:
1. Recognize `using X = Y` and `typedef Y X` declarations (where Y is class/struct/enum)
2. Store alias → canonical mapping in database
3. Implement automatic unification in search
4. Add hybrid response format (`param_types_canonical` field)

**Excluded from Phase 1**:
- ❌ Alias chains (defer to Phase 2)
- ❌ Template aliases (separate task cplusplus_mcp-2h1)
- ❌ Complex namespace-qualified resolution (if complexity arises, defer)

**Estimated effort**: 2-4 days

---

### Phase 2: Alias Chains (FUTURE)
**Target cases**:
```cpp
using A = B;
using B = C;
using C = RealClass;
```

**Deliverables**:
1. Transitive resolution (A → B → C → RealClass)
2. Optional: expose full chain in response metadata

**Estimated effort**: 1-2 days (after Phase 1 complete)

---

### Phase 3: Template Aliases (SEPARATE TASK)
**See**: cplusplus_mcp-2h1

---

## Key Design Decisions

### Decision 1: Hybrid Format Over "Always Canonical"
**Alternatives considered**:
- **Always Canonical**: Always return canonical type instead of alias
- **Query-Driven**: Normalize to type used in query
- **Hybrid**: Return both original and canonical

**Chosen**: Hybrid

**Rationale**:
| Criterion | Always Canonical | Query-Driven | Hybrid (CHOSEN) |
|-----------|-----------------|--------------|-----------------|
| Code truthfulness | ❌ Loses semantics | ❌ Can lie about code | ✅ Preserves original |
| LLM analysis capability | ✅ Simple comparison | ⚠️ Context-dependent | ✅ Flexible (both available) |
| User experience | ⚠️ Technical, not code terms | ✅ Matches query | ✅ Shows code + meaning |
| Implementation complexity | ✅ Simple | ❌ Complex (many edge cases) | ⚠️ Moderate |
| API stability | ✅ Stable | ❌ Varies by query | ✅ Stable |

**Key insight**: MCP tools should honestly represent source code, not transform it. Canonical type is supplementary information, not replacement.

---

### Decision 2: Phased Implementation (Simple First)
**Rationale**:
- ✅ Fast time-to-value (days vs weeks)
- ✅ Covers 80% of real-world cases (chains are rare)
- ✅ Early feedback from real usage
- ✅ Lower risk (can stop after Phase 1 if sufficient)

---

### Decision 3: No Separate Alias Query Tool
**Rationale**:
- Automatic unification "hides" aliases under the hood (user doesn't need to know)
- Hybrid response provides enough metadata
- Keep MCP API surface small
- Can add later if needed (non-breaking addition)

---

## Use Cases (Validation)

### Use Case 1: Find All Functions Working With Type
**User request**: "Show me all functions that accept `ErrorCallback`"

**Current behavior**: Misses functions declared with canonical type
```cpp
void handleError(ErrorCallback cb);      // found
void processError(std::function<...> cb); // MISSED!
```

**After Phase 1**: Both functions found automatically
```json
[
  {"name": "handleError", "param_types": ["ErrorCallback"],
   "param_types_canonical": ["std::function<void(const Error&)>"]},
  {"name": "processError", "param_types": ["std::function<void(const Error&)>"]}
]
```

**LLM explanation**: "Found 2 functions: `handleError` uses ErrorCallback alias, `processError` uses the full type."

---

### Use Case 2: Explain Function Signature
**Code**:
```cpp
using DataPtr = std::shared_ptr<Data>;
void process(DataPtr data);
```

**User request**: "What does `process` function do?"

**Current behavior**:
```json
{"name": "process", "param_types": ["DataPtr"]}
```
LLM: "Function accepts DataPtr" (no info what DataPtr is)

**After Phase 1**:
```json
{"name": "process", "param_types": ["DataPtr"],
 "param_types_canonical": ["std::shared_ptr<Data>"]}
```
LLM: "Function accepts DataPtr (which is std::shared_ptr<Data>), a smart pointer to Data object."

---

### Use Case 3: Type Comparison Across Files
**File 1**:
```cpp
void legacy(ErrorCallback cb);
```

**File 2**:
```cpp
void modern(std::function<void(const Error&)> cb);
```

**User request**: "Are these functions similar?"

**Current behavior**: No indication of type equivalence

**After Phase 1**: LLM can compare canonical types and see they're identical

---

## Technical Requirements

### Database Schema Changes
**New table or extend symbols table**: TBD in Phase 1 investigation

**Minimum required fields**:
- `alias_name` (TEXT): The alias identifier (e.g., "ErrorCallback")
- `canonical_type` (TEXT): The ultimate type (e.g., "std::function<void(const Error&)>")
- `file` (TEXT): Where alias is defined
- `line` (INTEGER): Line number
- `namespace` (TEXT): Namespace context (optional, for Phase 2+)
- `alias_kind` (TEXT): 'using' or 'typedef'

**Schema version**: Will require bump (breaking change, auto-recreation)

---

### libclang Capabilities (Phase 1 Investigation)
**Must investigate**:
1. Which cursor kinds handle aliases? (`CXCursor_TypeAliasDecl`, `CXCursor_TypedefDecl`)
2. How to extract target type from alias declaration?
3. How to get canonical type spelling?
4. Handling of simple class/struct/enum aliases (non-template)

---

### Search Engine Modifications
**Affected tools**:
- `search_functions` - param type matching
- `search_classes` - base class matching
- `search_symbols` - type filtering
- Any tool with type-based filters

**Required changes**:
- Expand type filter to include all equivalent names
- Add `*_canonical` fields to response format
- Update tests for new behavior

---

## Success Criteria (Phase 1)

### Functional
- ✅ Recognizes simple `using` and `typedef` declarations
- ✅ Stores alias mappings in database
- ✅ Search by alias finds canonical type usages
- ✅ Search by canonical finds alias usages
- ✅ Responses include canonical type when alias is used

### Non-Functional
- ✅ No performance degradation on indexing (<5% overhead)
- ✅ No breaking changes to existing MCP tool APIs (additive only)
- ✅ Comprehensive test coverage (unit + integration)

### Quality
- ✅ Tested on real codebase (small test project + large production codebase)
- ✅ Documentation updated (CLAUDE.md, tool descriptions)
- ✅ Clear error handling for malformed aliases

---

## Related Work

**Related Issues**:
- cplusplus_mcp-2an: Template Information Tracking (may overlap with template aliases)
- cplusplus_mcp-2h1: Template Alias Tracking (deferred complex case)

**Blocking**:
- cplusplus_mcp-8fk: EPIC: Template Support Enhancements

---

## Next Steps

1. ✅ **Phase 0 Complete**: Requirements defined (this document)
2. 🔄 **Phase 1.1**: libclang investigation (test alias detection capabilities)
3. ⏳ **Phase 1.2**: Database schema design
4. ⏳ **Phase 1.3**: Implementation (extraction + storage + search)
5. ⏳ **Phase 1.4**: Testing and validation

**Owner**: Claude Code + andrey
**Target completion**: Phase 1 within 1 week
