# Manual Testing Observations - LM Studio + qwen3 Models

**Date:** 2026-01-05
**Test Setup:** LM Studio with qwen3-4b and qwen3-30b-a3b, gpt-oss-20b
**Test Project:** Large production codebase (~5700+ files, complex template usage)

## Summary

Manual testing with lightweight LLM models revealed several UX and functionality issues with MCP server tools, particularly around:
1. Qualified name handling
2. Template class analysis
3. Namespace disambiguation

Server stability: ✅ **Excellent** - no crashes, correct tool execution
API clarity: ⚠️ **Needs improvement** - unintuitive behaviors, silent failures

---

## Observations

### ✅ Observation #1: Server Stability (POSITIVE)
**Status:** Working as expected
**Description:** MCP server operates stably and correctly executes tool requests. No crashes or protocol errors observed during extended testing session.

---

### ✅ Observation #2: Qualified Names Don't Work - **REFUTED**
**Status:** ~~UX Issue~~ **WORKING** (as of 2026-01-10 validation testing)
**Severity:** ~~Medium~~ N/A
**Tools affected:** `search_classes`, possibly `search_functions`

**Original Behavior (LM Studio testing):**
```json
// This returns empty list:
search_classes({"pattern": "myapp::View"})

// This works:
search_classes({"pattern": "View"})
```

**VALIDATION RESULTS (2026-01-10):**
✅ **Qualified names ARE SUPPORTED** - Feature was implemented in Phase 2

**Evidence:**
- Implementation: `mcp_server/search_engine.py:107-182` (`matches_qualified_pattern()`)
- Supports 4 matching modes:
  1. Leading `::` → exact match in global namespace
  2. No `::` → match unqualified name only
  3. `::` in pattern → component-based suffix match (e.g., `"ui::View"` matches `"app::ui::View"`)
  4. Regex metacharacters → regex fullmatch
- Tested and working in validation test case TC1

**Pattern Examples:**
```python
# These all work correctly:
search_classes({"pattern": "View"})           # Matches all View classes (any namespace)
search_classes({"pattern": "ui::View"})       # Matches app::ui::View, legacy::ui::View (suffix)
search_classes({"pattern": "::View"})         # Matches only global namespace View
search_classes({"pattern": "app::.*::View"})  # Regex match
```

**Root Cause of Original Observation:**
- Original testing likely predates Phase 2 implementation
- OR testing methodology didn't account for suffix matching behavior
- Qualified names fully functional as of current codebase

**Recommendation:**
- ✅ No action needed - feature already implemented
- 📝 Update MCP tool descriptions to showcase qualified name pattern examples

---

### ✅ Observation #3: No Namespace Filtering → Ambiguous Results - **REFUTED**
**Status:** ~~Feature Gap~~ **WORKING** (as of 2026-01-10 validation testing)
**Severity:** ~~High~~ N/A
**Related to:** Observation #2 (both refuted)

**Original Scenario (LM Studio testing):**
1. User asks: "Find information about `ns2::View`"
2. LLM tries: `search_classes({"pattern": "ns2::View"})` → empty results (Obs #2)
3. LLM retries: `search_classes({"pattern": "View"})` → returns `[ns1::View, ns2::View]`
4. LLM picks first result (`ns1::View`) → **wrong class analyzed**

**VALIDATION RESULTS (2026-01-10):**
✅ **Namespace filtering IS AVAILABLE** - `namespace` parameter exists

**Evidence:**
- Parameter: `search_classes(..., namespace="ns2")` filters by exact namespace
- Implementation: `mcp_server/search_engine.py:240-244`
- Tested and working in validation test case TC2

**Function Signature:**
```python
def search_classes(
    self,
    pattern: str,
    project_only: bool = True,
    file_name: Optional[str] = None,
    namespace: Optional[str] = None,  # <-- Namespace filter parameter
) -> List[Dict[str, Any]]:
```

**Correct Usage (now possible):**
```python
# Filter by exact namespace:
search_classes({"pattern": "View", "namespace": "ns2"})  # Returns only ns2::View

# Use qualified pattern (suffix match):
search_classes({"pattern": "ns2::View"})  # Matches ns2::View, app::ns2::View, etc.

# Get all results and inspect qualified_name:
results = search_classes({"pattern": "View"})
# Each result includes 'qualified_name' and 'namespace' fields
```

**Root Cause of Original Observation:**
- Original testing predates Phase 2 implementation
- `namespace` parameter was not documented or known to testers
- Feature already exists and works correctly

**Recommendation:**
- ✅ No action needed - feature already implemented
- 📝 Add examples to MCP tool descriptions showing `namespace` parameter usage
- 📝 Consider case-insensitive namespace matching for better UX

---

### ❌ Observation #4: Template-Based Inheritance Not Detected - **CONFIRMED**
**Status:** Functional Gap (validated 2026-01-10)
**Severity:** Medium-High
**Tool affected:** `get_derived_classes`

**Example Code:**
```cpp
class IInterface { };

template<typename T>
class TemplateBase : public T { };

class Concrete : public TemplateBase<IInterface> { };
```

**Behavior:**
```json
get_derived_classes({"class_name": "IInterface"})
// Returns: [] (empty)
// Expected: [{"name": "Concrete", ...}] (through TemplateBase<IInterface>)
```

**VALIDATION RESULTS (2026-01-10 - TC4):**
❌ **CONFIRMED** - Transitive inheritance through template parameters NOT detected

**Evidence from SQLite:**
```sql
SELECT name, base_classes FROM symbols
WHERE name IN ('IInterface', 'ImplementationBase', 'ConcreteImpl');
-- IInterface        | []
-- ImplementationBase | ["type-parameter-0-0"]  # Template parameter, not IInterface
-- ConcreteImpl      | ["ImplementationBase<IInterface>"]
```

**Observations:**
- Template base class shows `"type-parameter-0-0"` (libclang's template parameter representation)
- Direct inheritance (`ConcreteImpl` → `ImplementationBase<IInterface>`) stored correctly
- Transitive link missing: no connection between `IInterface` and `ConcreteImpl`

**Root Cause (validated):**
- **Location:** `mcp_server/cpp_analyzer.py` (inheritance tracking)
- **Issue:** To detect transitive inheritance, analyzer would need to:
  1. Parse template specializations (`ImplementationBase<IInterface>`)
  2. Match template parameter `Interface` with substituted type `IInterface`
  3. Build transitive inheritance graph through template instantiation
- **Complexity:** HIGH - requires template-aware AST analysis

**User Impact:**
- Common pattern in modern C++ (CRTP, mixin-based inheritance)
- Inheritance chains invisible to tools
- `get_derived_classes()` returns incomplete results for interface-based architectures
- Manual code inspection required

**Recommendations:**
- 🔧 **Prerequisite:** Issue #85 (Template Information Tracking) - P2
- 🔧 **New Issue:** "Template-Based Transitive Inheritance Detection" - P2 priority
  - Effort: 2-3 weeks
  - Depends on Issue #85
  - Implement template parameter substitution analysis
- 📝 **Documentation:** Document limitation in MCP tool descriptions

---

### ⚠️ Observation #5: Template Classes Not Found by Name - **PARTIALLY CONFIRMED**
**Status:** Functional Gap (validated 2026-01-10 - TC3)
**Severity:** Medium (not as severe as originally thought)
**Tools affected:** `get_class_info`, class lookup tools

**Example:**
```cpp
template<typename T>
class WithParaBaseProps { /* ... */ };

class ConcreteA : public WithParaBaseProps<int> { };
class ConcreteB : public WithParaBaseProps<std::string> { };
```

**Original Behavior:**
```json
get_class_info({"class_name": "WithParaBaseProps"})
// Returns: {"data": null, "metadata": {...}}

// This works:
get_class_info({"class_name": "WithParaBaseProps<int>"})
// Returns: actual class info for the specialization
```

**VALIDATION RESULTS (2026-01-10 - TC3):**
⚠️ **PARTIAL** - Templates ARE indexed but naming limitations exist

**Evidence from SQLite:**
```sql
SELECT name, qualified_name, kind, line FROM symbols WHERE name = 'Container';
-- Container | Container | class_template          | 3   # Template definition
-- Container | Container | class                   | 11  # Explicit specialization <int>
-- Container | Container | partial_specialization  | 20  # Partial specialization <T*>
```

**Observations:**
1. **Template Base:** Stored with `kind='class_template'` ✅
2. **Explicit Specializations:** Stored with `kind='class'` (e.g., `Container<int>`) ✅
3. **Partial Specializations:** Stored with `kind='partial_specialization'` ✅
4. **Name Limitation:** All have same `qualified_name` - no template arguments in name ⚠️
5. **Derived Classes:** Store full template args in base_classes (e.g., `["Container<int>"]`) ✅

**Root Cause (validated):**
- **Location:** `mcp_server/cpp_analyzer.py` (symbol extraction)
- **Issue:** libclang's `cursor.spelling` returns unqualified template name without arguments
- **Impact:** Cannot search for specific specializations like "Container<int>" by qualified_name
- **Workaround:** Search by `kind` field or query derived classes

**Implications:**
1. `get_class_info("Container")` returns first match (arbitrary - likely template base)
2. `get_class_info("Container<int>")` might not work if specialized name not stored
3. LLMs cannot distinguish between template base and specializations from search results
4. `get_derived_classes("Container")` returns classes derived from ANY Container variant

**User Impact - MODERATE:**
- Templates ARE indexed (better than originally thought)
- But cannot distinguish template base from specializations by name alone
- Requires template metadata tracking (Issue #85)

**Recommendations:**
- 🔧 **Issue #85:** Implement template metadata tracking (P2 priority):
  - `is_template` flag
  - `template_parameters` field (e.g., `["T"]`, `["typename T", "int N"]`)
  - Store specialized names with arguments (e.g., `"Container<int>"`)
- 🔧 **Short-term:** Document `kind` field in tool responses for LLM disambiguation
- 🔧 **Consider:** Add `template_info` field to search results with template metadata

---

### ✅ Observation #6: Template Argument Names Are Unqualified (Ambiguous) - **REFUTED**
**Status:** ~~Data Quality Issue~~ **WORKING** (validated 2026-01-11 with TC5)
**Severity:** ~~Medium~~ N/A
**Related to:** Observations #2 (refuted), #5 (validated)

**Original Behavior (LM Studio testing):**
```json
get_derived_classes({"class_name": "BarClass<ns1::FooClass>"})
// Returns info, but base class shown as: "BarClass<FooClass>"
//                                                    ^^^^^^^^^ unqualified!
```

**VALIDATION RESULTS (2026-01-11 - TC5):**
✅ **Namespace qualification IS PRESERVED** - Original observation was incorrect

**Evidence from TC5 Dedicated Test:**
```cpp
// Test file: examples/template_test/template_args.h
namespace ns1 { class FooClass { }; }
namespace ns2 { class FooClass { }; }
template<typename T> class BarClass : public T { };
class Example1 : public BarClass<ns1::FooClass> { };
class Example2 : public BarClass<ns2::FooClass> { };
```

**SQLite Results:**
```sql
SELECT name, base_classes FROM symbols WHERE name IN ('Example1', 'Example2');
-- Example1 | ["BarClass<ns1::FooClass>"]  ✅ Namespace preserved!
-- Example2 | ["BarClass<ns2::FooClass>"]  ✅ Namespace preserved!
```

**Additional Evidence from TC3/TC4:**
```sql
-- TC3: Builtin types preserved
SELECT name, base_classes FROM symbols WHERE name LIKE '%Container';
-- IntContainer | ["Container<int>"]        ✅
-- PtrContainer | ["Container<void *>"]     ✅

-- TC4: Global namespace classes preserved
SELECT name, base_classes FROM symbols WHERE name LIKE '%Impl';
-- ConcreteImpl | ["ImplementationBase<IInterface>"] ✅
```

**Root Cause of Original Observation:**
- **Original observation was incorrect** - likely based on misinterpretation or outdated testing
- libclang DOES provide qualified names for template arguments
- Current implementation in `mcp_server/cpp_analyzer.py` correctly preserves qualification
- Works for builtin types, pointers, global namespace, and nested namespace classes

**Impact:** **POSITIVE** - No ambiguity, full qualification preserved

**User Impact:**
- ✅ CAN distinguish `BarClass<ns1::FooClass>` from `BarClass<ns2::FooClass>`
- ✅ Dependencies and inheritance chains are clear and unambiguous
- ✅ Template instantiations show complete type information

**Recommendation:**
- ✅ No action needed - feature already working correctly
- 📝 Update documentation to clarify template argument qualification works

---

### ⚠️ Observation #7: Silent Failures vs Clear Errors
**Status:** UX Issue
**Severity:** Low-Medium

**Positive example (regex validation):**
```json
search_classes({"pattern": ".*WithParaBaseProps.*"})
// Returns clear error:
{
  "type": "text",
  "text": "Error: Unsafe regex pattern: Dangerous pattern detected: Multiple consecutive quantifiers"
}
```

**Negative examples (silent failures):**
- Qualified name search: empty results, no explanation
- Template class search: `"data": null`, no hint that specializations exist
- Missing class: same `"data": null` (indistinguishable from template issue)

**Suggestion:** Distinguish between:
- Not found: "Class 'X' not found in index"
- Found but is template: "Class 'X' is a template. Known specializations: [...]"
- Pattern didn't match: "Pattern 'ns::X' matched 0 symbols. Try unqualified name 'X'?"

---

## Interconnections Between Observations

```
Root Issue A: Name Qualification Handling
├─ Obs #2: Qualified names don't work in search
├─ Obs #3: No namespace filtering → ambiguous results
└─ Obs #6: Template args shown unqualified → ambiguous specializations

Root Issue B: Template Analysis Limitations
├─ Obs #4: Template-based inheritance not detected (IInterface ← TemplateBase<IInterface> ← Concrete)
├─ Obs #5: Template classes not searchable by base name
└─ Obs #6: Template arg names lose qualification

Root Issue C: Error Reporting
└─ Obs #7: Silent failures vs clear errors (inconsistent UX)
```

---

## Proposed Issues for Discussion

### High Priority

**Issue #1: Support qualified names in search tools**
- **Category:** API Enhancement
- **Observations:** #2, #3
- **Proposal:**
  - Accept both `"View"` and `"ns::View"` in pattern matching
  - Auto-extract unqualified name for matching, then filter results by namespace
  - OR: Add separate `namespace` parameter for filtering

**Issue #2: Template class search and specialization discovery**
- **Category:** Feature Request
- **Observations:** #5
- **Proposal:**
  - Detect template classes during indexing
  - Link specializations to generic template definition
  - `get_class_info("TemplateClass")` returns template info + list of specializations
  - Pattern `"TemplateClass"` matches all specializations
  - `get_derived_classes("TemplateClass")` aggregates results from all specializations

**Issue #3: Namespace disambiguation in results**
- **Category:** API Enhancement
- **Observations:** #3
- **Proposal:**
  - Return qualified names prominently in results
  - Add filtering/ranking by namespace match
  - Consider: `prefer_namespace` parameter to prioritize certain namespaces

### Medium Priority

**Issue #4: Template-based transitive inheritance detection**
- **Category:** Feature Request (Complex)
- **Observations:** #4
- **Proposal:**
  - Analyze template parameter inheritance: `template<T> class Base : public T`
  - Track transitive inheritance through template specializations
  - `get_derived_classes("IInterface")` finds classes derived via `Base<IInterface>`
- **Complexity:** High - requires deep template AST analysis

**Issue #5: Qualified names for template arguments**
- **Category:** Data Quality
- **Observations:** #6
- **Proposal:**
  - Use libclang's qualified name APIs for template arguments
  - Store and display `"BarClass<ns1::FooClass>"` not `"BarClass<FooClass>"`
- **Complexity:** Medium - requires AST traversal changes

### Low Priority (UX)

**Issue #6: Improve error messages and failure clarity**
- **Category:** UX Improvement
- **Observations:** #7
- **Proposal:**
  - Distinguish "not found" vs "is template" vs "pattern mismatch"
  - Suggest corrections: "Did you mean unqualified 'View' instead of 'ns::View'?"
  - When template found: "This is a template. Known specializations: [...]"

**Issue #7: Documentation - Template search patterns**
- **Category:** Documentation
- **Observations:** #5
- **Proposal:**
  - Document current behavior with templates
  - Provide examples of searching for template specializations
  - Update tool descriptions in MCP schema

---

## Testing Notes

**Model Behavior Observations:**
- Lightweight models (qwen3-4b, qwen3-30b) struggle with:
  - Understanding unqualified name requirement (required system prompt addition)
  - Verifying qualified names match after ambiguous search (required system prompt addition)
  - Template specialization search strategies (no workaround found - API limitation)

**System Prompt Additions Required:**
1. "Always pass unqualified names to MCP tools (e.g., 'View' not 'ns::View')"
2. "After searching with unqualified name, verify qualified name matches user's request"
3. (No effective workaround for template issues - would need API changes)

**Recommended Validation:**
- Test qualified name handling in fresh session (verify Obs #2)
- Create minimal repro case for template inheritance (Obs #4)
- Check libclang APIs for template argument qualified names (Obs #6)

---

## Next Steps

1. **Validate observations** in controlled test session (SSE mode + curl)
2. **Prioritize issues** based on:
   - User impact (Issue #2, #3 are high impact)
   - Implementation complexity
   - Workaround availability
3. **Create GitHub issues** from this document
4. **Plan implementation** for high-priority items

---

## Appendix: Example Test Commands

```bash
# Start server
MCP_DEBUG=1 python -m mcp_server.cpp_mcp_server --transport sse --port 8000

# Test Obs #2: Qualified names
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
    "params": {
      "name": "search_classes",
      "arguments": {"pattern": "myapp::View"}
    }
  }' | jq -r '.result.content[0].text'

# Test Obs #5: Template class search
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
    "params": {
      "name": "get_class_info",
      "arguments": {"class_name": "WithParaBaseProps"}
    }
  }' | jq '.'
```
