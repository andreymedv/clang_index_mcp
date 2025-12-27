# [007] Type Alias Tracking and Resolution

**Category:** Feature
**Priority:** Medium
**Status:** Proposed
**Date Identified:** 2025-12-27
**Estimated Effort:** Requires investigation (2-4 weeks estimate)
**Complexity:** Complex

---

## Problem Statement

The MCP server cannot distinguish between actual type definitions (classes, structs, enums) and type aliases created via `using` or `typedef`. This prevents LLMs from accurately understanding code structure and providing correct analysis.

### Current Behavior

When querying for a type name (e.g., "MyClass"), the system:
- Returns symbol information if it's an actual class/struct definition
- May return nothing or misleading information if it's an alias
- Cannot indicate whether a name is an alias vs. actual definition
- Cannot resolve alias chains to find the ultimate type
- Cannot distinguish between `class Foo` and `using Foo = Bar`

### Expected/Desired Behavior

The system should:
1. **Identify aliases**: Recognize `using` and `typedef` declarations
2. **Store alias information**: Persist in database with relationship to target types
3. **Expose via MCP tools**: Allow querying for alias information
4. **Resolve alias chains**: Follow chains of re-aliasing (e.g., `using A = B; using B = C; class C {};`)
5. **Support all type categories**: Track aliases for classes, structs, enums, built-in types, and template instantiations

---

## Impact Assessment

**User Impact:**
- **High**: Discovered in real-world codebase (ProjectName, 14,430 files) with extensive use of type aliases
- LLMs cannot provide accurate analysis when aliases are involved
- Users get confused between alias names and actual type names
- Code navigation and understanding is impaired

**Development Impact:**
- Requires database schema changes (breaking change)
- Core symbol extraction logic needs modification
- New MCP tools or extension of existing tools needed
- Comprehensive testing required for alias resolution

**Business Impact:**
- Adoption blocker for C++ codebases that heavily use modern C++ idioms (type aliases, template aliases)
- Competitive disadvantage vs. IDEs that properly handle aliases
- Essential for proper semantic analysis of modern C++ code

---

## Real-World Examples

```cpp
// Example 1: Basic alias
class RealClass {};
using AliasOne = RealClass;  // User queries "AliasOne" - should know it's an alias

// Example 2: Alias chain
using AliasTwo = AliasOne;   // Should resolve: AliasTwo -> AliasOne -> RealClass

// Example 3: Namespace context
namespace foo {
    using LocalAlias = ::RealClass;  // Context-dependent aliasing
}

// Example 4: Template alias
template<typename T>
using Vector = std::vector<T>;  // Template alias (advanced case)

// Example 5: Built-in type alias
using size_type = unsigned long;  // Not a class, but still needs tracking

// Example 6: Enum alias
enum class Color { Red, Green, Blue };
using Colour = Color;  // British spelling alias
```

**Current problem**: When LLM queries for "AliasTwo", it gets no indication that:
- It's an alias (not a real class)
- It points to "AliasOne"
- The ultimate type is "RealClass"

---

## Proposed Solutions

### Investigation Required First

⚠️ **Before proposing detailed solutions, we need to investigate:**

1. **libclang Capabilities**
   - Which cursor kinds handle aliases? (`CXCursor_TypeAliasDecl`, `CXCursor_TypedefDecl`)
   - How to extract target type from alias declarations?
   - Can libclang resolve template aliases?
   - How to handle namespace-qualified lookups?

2. **Requirements Clarification**
   - What information do LLMs need about aliases?
   - Should we auto-resolve aliases or expose the chain?
   - How to represent alias chains in responses?
   - Should template aliases be handled differently?

3. **Schema Design**
   - New table `type_aliases`? Or extend `symbols` table?
   - How to represent one-to-many relationships (alias can point to multiple targets in different contexts)?
   - How to store alias chains efficiently?
   - Indexing strategy for fast alias lookup?

4. **Performance Impact**
   - Additional parsing overhead for alias declarations
   - Database size impact (how many aliases in typical projects?)
   - Query performance with alias resolution

### Placeholder Solution Sketch (Pending Investigation)

**Option 1: New `type_aliases` Table**

**Concept**: Create dedicated table for tracking type aliases

**Potential Schema**:
```sql
CREATE TABLE type_aliases (
    alias_name TEXT NOT NULL,
    target_type TEXT NOT NULL,
    file TEXT NOT NULL,
    line INTEGER NOT NULL,
    namespace TEXT DEFAULT '',
    is_template_alias BOOLEAN DEFAULT 0,
    template_params TEXT DEFAULT NULL,  -- JSON array
    alias_kind TEXT NOT NULL,  -- 'using' or 'typedef'
    created_at REAL NOT NULL
);
```

**Pros:**
- Clean separation from symbol table
- Dedicated indexes for alias lookup
- Easy to extend with alias-specific metadata

**Cons:**
- Need to join with symbols table for full information
- More complex queries
- Potential duplication if alias is also indexed as symbol

**Estimated Effort:** TBD after investigation
**Risk Level:** Medium

---

**Option 2: Extend `symbols` Table**

**Concept**: Add alias-specific fields to existing symbols table

**Potential Schema Changes**:
```sql
ALTER TABLE symbols ADD COLUMN is_alias BOOLEAN DEFAULT 0;
ALTER TABLE symbols ADD COLUMN alias_target TEXT DEFAULT NULL;
ALTER TABLE symbols ADD COLUMN alias_kind TEXT DEFAULT NULL;
```

**Pros:**
- Single table for all symbol information
- Simpler queries
- Reuse existing indexes

**Cons:**
- Table bloat with mostly NULL values for non-alias symbols
- Less flexibility for alias-specific features
- Harder to represent complex alias chains

**Estimated Effort:** TBD after investigation
**Risk Level:** Low-Medium

---

## Recommended Approach

**Status**: Requires investigation before recommendation can be made.

**Investigation Plan:**
1. **Phase 1** (1 week): libclang capability analysis
   - Test alias detection with various C++ constructs
   - Determine what information is extractable
   - Identify limitations

2. **Phase 2** (1 week): Requirements gathering
   - Survey common alias patterns in target codebases
   - Define MCP tool API for alias queries
   - Determine LLM information needs

3. **Phase 3** (1 week): Schema design and prototyping
   - Design database schema
   - Prototype alias extraction
   - Performance testing

4. **Phase 4** (1 week): Implementation planning
   - Detailed implementation plan
   - Breaking change migration strategy
   - Testing strategy

---

## Decision Log

**2025-12-27**: Initial identification
- **Decision**: Record as feature request, defer implementation pending investigation
- **Rationale**: Discovered during manual testing on ProjectName codebase; significant architectural impact requires careful planning
- **Next Steps**:
  1. Create detailed investigation plan
  2. Analyze libclang capabilities for alias detection
  3. Gather requirements from real-world use cases

---

## Implementation Notes

### Dependencies

**Technical Dependencies:**
- libclang alias detection capabilities (to be investigated)
- Database schema version bump (breaking change)
- MCP protocol additions for alias information

**Logical Dependencies:**
- None identified yet

### Risks

1. **Risk: Template aliases may be complex to handle**
   - **Mitigation**: Start with simple aliases, add template support in later phase

2. **Risk: Namespace-qualified lookups may require significant indexing changes**
   - **Mitigation**: Investigate early, may need to scope down initial implementation

3. **Risk: Performance impact on large codebases**
   - **Mitigation**: Benchmark during investigation phase

4. **Risk: Breaking schema change requires user cache rebuild**
   - **Mitigation**: Clear migration guide, version bump, auto-recreation

### Testing Requirements

- Unit tests for alias extraction from AST
- Integration tests for alias resolution chains
- Performance tests with codebases heavy on aliases
- Test cases for:
  - Simple using/typedef
  - Alias chains
  - Template aliases
  - Namespace-scoped aliases
  - Built-in type aliases
  - Enum aliases

### Migration/Compatibility

- **Breaking Change**: Database schema version bump required
- **Migration Strategy**: Cache auto-recreation on version mismatch (existing pattern)
- **Backward Compatibility**: Not applicable (internal database structure)

---

## References

**Related Documentation:**
- [CLAUDE.md](../../CLAUDE.md) - Development guide
- [ANALYSIS_STORAGE_ARCHITECTURE.md](../ANALYSIS_STORAGE_ARCHITECTURE.md) - Database architecture

**Code References:**
- `mcp_server/cpp_analyzer.py:_process_cursor()` - Symbol extraction (will need alias handling)
- `mcp_server/schema.sql` - Database schema (will need new table or columns)
- `mcp_server/search_engine.py` - Search implementation (may need alias resolution)

**External Resources:**
- [libclang documentation](https://clang.llvm.org/doxygen/group__CINDEX.html)
- C++ standard: using declarations and type aliases

**Related Issues:**
- [008] Template information tracking (separate but related feature)

---

## Next Steps

1. **Immediate**: Create investigation task for libclang alias capabilities
2. **Short-term** (before implementation):
   - Complete investigation phases 1-4
   - Update this document with findings
   - Create detailed implementation plan
3. **Long-term**: Implementation only after investigation and design approval

**Trigger Conditions** (when to revisit):
- User reports additional cases where alias tracking is critical
- Investigation phase completes with positive findings
- Schema v9.0 planning begins (opportunity to bundle breaking changes)

**Owner** (if assigned): TBD

---

## Notes

- Identified during manual testing on ProjectName codebase (14,430 files)
- Real-world problem affecting large-scale C++ projects
- Modern C++ codebases use aliases extensively (especially with templates)
- This is a **quality-of-life** improvement, not a critical bug
