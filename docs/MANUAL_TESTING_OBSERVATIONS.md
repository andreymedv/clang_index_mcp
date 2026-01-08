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

### ⚠️ Observation #2: Qualified Names Don't Work
**Status:** UX Issue
**Severity:** Medium
**Tools affected:** `search_classes`, possibly `search_functions`

**Behavior:**
```json
// This returns empty list:
search_classes({"pattern": "myapp::View"})

// This works:
search_classes({"pattern": "View"})
```

**Workaround:** Added to system prompt: "Always use unqualified names (no namespace prefix)"

**Root cause hypothesis:** Pattern matching operates on `symbol_info.name` field which contains only unqualified names. The `::` in pattern simply doesn't match anything.

**User impact:**
- Unintuitive - users naturally want to specify fully qualified names
- LLM models don't understand this requirement without explicit prompting
- Silent failure (empty results, no error message)

---

### ⚠️ Observation #3: No Namespace Filtering → Ambiguous Results
**Status:** Feature Gap
**Severity:** High (causes incorrect analysis chains)
**Related to:** Observation #2

**Scenario:**
1. User asks: "Find information about `ns2::View`"
2. LLM tries: `search_classes({"pattern": "ns2::View"})` → empty results (Obs #2)
3. LLM retries: `search_classes({"pattern": "View"})` → returns `[ns1::View, ns2::View]`
4. LLM picks first result (`ns1::View`) → **wrong class analyzed**

**Root cause:** No API mechanism to filter by namespace or qualified name

**User impact:**
- In large codebases with common class names across namespaces, results are ambiguous
- LLM makes wrong assumptions about which class user meant
- Requires additional system prompt instructions for LLM to verify qualified names

**Workaround (added to system prompt):**
```
After getting search results, ALWAYS verify the qualified name
matches user's request before proceeding with analysis.
```

---

### ⚠️ Observation #4: Template-Based Inheritance Not Detected
**Status:** Functional Gap
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

**Root cause hypothesis:**
- libclang reports `Concrete`'s direct base class as `TemplateBase<IInterface>` (the specialization)
- System doesn't "unwrap" template specializations to discover transitive inheritance through template parameters
- Requires deep template analysis: `TemplateBase<IInterface>` → `TemplateBase` inherits from `T` → `T=IInterface`

**User impact:**
- Common pattern in tested codebase: interfaces passed as template params to CRTP-like base classes
- Inheritance chains invisible to tools
- Manual code inspection required

---

### ⚠️ Observation #5: Template Classes Not Found by Name
**Status:** Functional Gap
**Severity:** High
**Tools affected:** `get_class_info`, likely all class lookup tools

**Example:**
```cpp
template<typename T>
class WithParaBaseProps { /* ... */ };

class ConcreteA : public WithParaBaseProps<int> { };
class ConcreteB : public WithParaBaseProps<std::string> { };
```

**Behavior:**
```json
get_class_info({"class_name": "WithParaBaseProps"})
// Returns: {"data": null, "metadata": {...}}

// This works:
get_class_info({"class_name": "WithParaBaseProps<int>"})
// Returns: actual class info for the specialization
```

**Pattern matching attempts:**
```json
// Doesn't work (returns empty or no matches):
search_classes({"pattern": "WithParaBaseProps"})

// Doesn't work:
search_classes({"pattern": "WithParaBaseProps.*"})

// Works (but requires knowing exact specialization):
search_classes({"pattern": "WithParaBaseProps<ConcreteType>"})
```

**Root cause hypothesis:**
- libclang stores specializations with full names: `WithParaBaseProps<int>`, `WithParaBaseProps<std::string>`
- Generic template definition `WithParaBaseProps` either not stored, or stored separately without linkage
- Pattern matching on `"WithParaBaseProps"` doesn't match `"WithParaBaseProps<int>"`
- Regex `"WithParaBaseProps.*"` anchored match doesn't work because `<>` characters?

**User impact - CRITICAL:**
- Users think in terms of template classes as logical entities
- Natural user request: "Show me derived classes of `WithParaBaseProps`"
- Natural expectation: system shows `ConcreteA`, `ConcreteB` (all classes derived from any specialization)
- Current behavior: must know and query each specialization individually
- LLM models don't understand they need to search for specializations

**Two perspectives:**
1. **User perspective:** Template class is a logical unit; derived classes from specializations ARE derived from the template
2. **LLM perspective:** Needs to discover specializations exist, then query each separately (token-expensive)

**Ideal behavior suggestion:**
- Query `get_class_info("WithParaBaseProps")` should:
  - Detect it's a template (or try template-aware search)
  - Return info about template + list of known specializations
  - For `get_derived_classes("WithParaBaseProps")`: return derived classes from ALL specializations
- Encapsulate template→specialization logic inside tools (saves LLM tokens)

---

### ⚠️ Observation #6: Template Argument Names Are Unqualified (Ambiguous)
**Status:** Data Quality Issue
**Severity:** Medium
**Related to:** Observation #2

**Example:**
```cpp
namespace ns1 { class FooClass { }; }
namespace ns2 { class FooClass { }; }

template<typename T> class BarClass : public T { };

// Somewhere in code:
class X : public BarClass<ns1::FooClass> { };
```

**Behavior:**
```json
get_derived_classes({"class_name": "BarClass<ns1::FooClass>"})
// Returns info, but base class shown as: "BarClass<FooClass>"
//                                                    ^^^^^^^^^ unqualified!
```

**Root cause:** libclang returns unqualified names for template arguments in some contexts (displayname vs qualified name)

**User impact:**
- Ambiguous when multiple classes have same unqualified name
- Can't definitively determine which `FooClass` is used in the specialization
- Affects understanding of dependencies and inheritance chains

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
