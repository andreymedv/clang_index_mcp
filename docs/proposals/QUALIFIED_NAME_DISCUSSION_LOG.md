# Qualified Name Support - Discussion Log

**Status:** 🟡 In Progress
**Started:** 2026-01-06
**Participants:** Domain Expert (Andrey), System Analyst (Claude Code)

---

## Discussion Progress

### Completed Questions ✅

- **Q1: Partial Qualification Matching Rules** ✅ RESOLVED
- **Q2: Function Overload Identification** ✅ RESOLVED
- **Q4: Leading `::` Semantics** ✅ RESOLVED (discussed alongside Q1)
- **Q5: Namespace Filtering Scope** ✅ RESOLVED (discussed alongside Q1)

### Next Question to Discuss ⏭️

**Q3: Template Specialization Qualified Names** - Resume discussion from here

### Pending Questions

- Q6: Performance vs Precision Trade-offs
- Q7: Anonymous Namespace Handling
- Q8: Nested Class Qualified Names
- Q9: Backward Compatibility - Schema Migration
- Q10: LLM Guidance - Tool Descriptions
- Q11: Template Function Search Logic (NEW - separate research track)

---

## Resolved Decisions

### Q1: Partial Qualification Matching Rules ✅

**Decision Date:** 2026-01-06
**Decision:** Option A (Strict Suffix Matching) with component-based implementation

#### Final Specification

**1. Component-Based Suffix Matching**

Pattern matches if qualified_name ends with the same sequence of components.

**Implementation:**
```python
def matches_suffix(qualified_name: str, pattern: str) -> bool:
    if pattern.startswith("::"):
        # Absolute name - exact match (see Q4)
        return qualified_name == pattern[2:]  # Remove leading ::

    # Suffix by components
    q_parts = qualified_name.split("::")
    p_parts = pattern.split("::")

    if len(p_parts) > len(q_parts):
        return False

    # Check that last N components match
    return q_parts[-len(p_parts):] == p_parts
```

**Examples:**
- Pattern `"ui::View"`:
  - ✅ Matches: `app::ui::View`, `legacy::ui::View`, `ui::View`
  - ❌ Does NOT match: `app::ui::internal::View`, `myapp::View` (if `myapp` is single component)

**2. Component Boundaries (Hard Boundaries)**

Each `::` is a hard boundary. Pattern component `"app"` does NOT match qualified name component `"myapp"`.

**Examples:**
- Pattern `"app::View"`:
  - ✅ Matches: `legacy::app::View`
  - ❌ Does NOT match: `myapp::View` (component mismatch)

**3. Empty Result on No Matches**

No suggestions, no partial matches. If no exact suffix matches found, return empty list.

**Rationale:**
- Trains users to specify names accurately
- Returning "close matches" could lead LLM down incorrect reasoning paths
- Avoids cognitive overhead of explaining fuzzy matching behavior

**4. No Separate `namespace` Parameter**

Decision: **Do NOT add** a separate `namespace` parameter to search tools.

**Rationale:**
- Would require users to distinguish between namespace and parent class in qualified names (cognitive load)
- Would require LLM to determine component types (wasted tokens)
- Regex patterns already solve namespace filtering: `"app::core::.*"`
- Following principle: **"Each time system prompt needs explanation of tool behavior = indicator of API ambiguity"**

**Alternative approach:** Use qualified patterns and regex for namespace filtering.

**Examples:**
```json
// Find all classes in app::core namespace
search_classes({"pattern": "app::core::.*"})

// Find specific class
search_classes({"pattern": "app::core::Config"})
```

---

### Q4: Leading `::` Semantics ✅

**Decision Date:** 2026-01-06
**Decision:** Option A (Global Namespace Only)

#### Final Specification

**Leading `::` = Absolute Name (Exact Match)**

In C++, `::Name` means absolute path from global namespace root.

**Behavior:**
- Pattern `"::View"` matches **only** `View` in global namespace
- Equivalent to regex `^View$` (exact match)
- Pattern `"View"` (no leading `::`) matches `View` in any namespace (suffix matching)

**Examples:**
- Pattern `"::View"`:
  - ✅ Matches: `View` (global namespace)
  - ❌ Does NOT match: `app::View`, `ui::View`
- Pattern `"::app::ui::View"`:
  - ✅ Matches: `app::ui::View` (exact match, if app is in global namespace)
  - ❌ Does NOT match: `legacy::app::ui::View`

**Rationale:**
- Aligns with C++ syntax semantics
- Provides mechanism to disambiguate global vs namespaced symbols
- Consistent with developer expectations

---

### Q5: Namespace Filtering Scope ✅

**Decision Date:** 2026-01-06
**Decision:** No separate `namespace` parameter - use qualified patterns instead

#### Final Specification

**No `namespace` parameter will be added to search tools.**

**Rationale:**
- Separate parameter creates ambiguity (namespace vs parent class)
- Increases cognitive load on users
- Requires additional tokens for LLM to parse qualified names
- Regex patterns already provide this functionality

**Alternative solution:**
Use qualified name patterns with regex for namespace filtering.

**Examples:**
```json
// All symbols in ui namespace (any level)
search_classes({"pattern": "ui::.*"})

// All symbols in app::core and child namespaces
search_classes({"pattern": "app::core::.*"})

// Specific symbol in namespace
search_classes({"pattern": "app::core::Config"})
```

**Impact on Implementation Plan:**
- **Remove from Phase 3:** Task 3.1 "Namespace Parameter"
- **Remove from proposal:** All examples with `"namespace": "..."` parameter
- **Add to documentation:** Explain regex pattern usage for namespace filtering

---

### Q2: Function Overload Identification ✅

**Decision Date:** 2026-01-06
**Decision:** Option A (Simple Return All) for v1

#### Final Specification

**For v1 Implementation:**

1. **Return all non-template overloads** without limits
   - When `get_function_info("ns::foo")` finds multiple overloads, return all
   - No artificial cap on number of results

2. **Metadata for context:**
   ```json
   {
     "data": [
       {"signature": "void foo(int)", "is_template_specialization": false, ...},
       {"signature": "void foo(double)", "is_template_specialization": false, ...}
     ],
     "metadata": {
       "total_overloads": 2
     }
   }
   ```

3. **Template distinction:**
   - Add `is_template_specialization: bool` field to distinguish from template instantiations
   - Helps LLM understand what type of overload they're seeing

4. **NO file-based filtering parameter (deferred):**
   - Don't add `file_path` filtering to function lookup tools yet
   - Add only if/when large result sets become problematic
   - LLM already uses file context naturally in some queries

#### Deferred to Later Phase

**Full Signature Matching:**
- Syntax: `get_function_info({"function_name": "foo(int, std::string)"})`
- Requires signature parsing, normalization, qualified type resolution
- Complexity estimate: 10-14 days (>10% of Phase 1-3 timeline)
- Will be discussed during overall planning after Q3-Q10

**Rationale for deferral:**
- No blocking scenarios identified
- Qualified names (Q1) + metadata solve 80%+ cases
- Can collect v1 feedback to inform v2 design

#### Separate Research Track: Q11

**NEW QUESTION: Template Function Search Logic**

**Scope:** Separate investigation, not part of Q2

**Problem identified during Q2 discussion:**
- Template functions are fundamentally different from simple overloads
- Three distinct cases:
  1. **Non-template overloads:** 2-10+ variants (typical: 2-5)
  2. **Implicit template instantiations:** Hundreds of compiler-generated variants
  3. **Explicit template specializations:** Dozens of hand-written variants

**Real-world scale from testing project (~5700 files):**
- Intensively used template functions: **hundreds** of instantiations
- Explicit specializations: **dozens** per function (for a few critical functions)
- Overloaded operators: 10+ overloads common
- Token economy: **critical** for lightweight LLMs

**Why separate track:**
- Related to Issues #85 (Template Information Tracking), #99, #101
- Requires user scenario collection and analysis
- Search behavior must be intuitive: `foo`, `foo<int>`, `foo<T>(args)` - different expectations
- Goal: Remove cognitive load from both users and LLMs
- Likely Phase 3+ or parallel feature development

**Key insights from discussion:**
- Users think of template functions as logical entities
- Natural query: "Show derived classes of `TemplateBase`" → expect ALL specializations
- Current model (explicit per-specialization queries) doesn't match mental model
- Solution should encapsulate template→specialization logic inside tools (save LLM tokens)

#### Context from Real Project

**Project characteristics:**
- ~5700 files, complex C++ codebase
- Heavy use of templates, CRTP patterns
- Overloaded operators widespread (10+ overloads)
- Lightweight LLMs: qwen3-4b, qwen3-30b, gpt-oss-20b

**LLM behavior observations:**
- Ignore tool parameter descriptions
- Copy name form from user request directly
- Require explicit system prompt instructions
- High reasoning token cost when results ambiguous

**Token economy critical:**
- Returning hundreds of template instantiations = token catastrophe
- Must be prevented at API level, not expected from LLM filtering

---

## Key Insights from Discussion

### 1. System Prompt Complexity as API Design Signal

**Principle identified by domain expert:**

> "Each time we need to add system prompt explanation of how to work with tools - this is an indicator of ambiguity in the approach itself."

**Application:**
- Before adding new parameters, consider if existing mechanisms (regex, patterns) suffice
- Explicit behavior requiring documentation = potential API design problem
- Simpler API with clear semantics > feature-rich API with complex rules

### 2. LLM Behavior with Pattern Forms

**Observation from manual testing:**

Lightweight LLMs (qwen3-4b, qwen3-30b, gpt-oss-20b) ignore parameter descriptions and copy name form from user request:
- User asks about `"app::Config"` → LLM passes `"app::Config"` to tool
- Tool description says "use unqualified names" → LLM ignores this
- System prompt with **explicit instruction** "use unqualified names" → LLM follows

**Implication:**
- Tool descriptions alone insufficient to guide LLM behavior
- Explicit system prompt instructions required for critical constraints
- Better design: Accept both forms, auto-detect intent (dual-mode approach)

### 3. Token Efficiency vs Precision

Lightweight LLMs CAN extract qualified names from ambiguous results and match against user request, BUT this costs tokens for reasoning.

**Design goal:** Reduce reasoning tokens by returning precise results upfront.

**Approach:**
- Store qualified names in indexed fields
- Return qualified_name prominently in all results
- Support qualified patterns in search
- Minimize need for post-processing by LLM

---

## Notes for Continuation

### When resuming discussion, start with:

**Q3: Template Specialization Qualified Names**

Location in proposal: Lines 1056-1084

**Key question:** How to represent template argument types in qualified names?

**Current problem (Issue #102):**
- Template args shown with unqualified names: `Container<Foo>` (ambiguous)
- Should be: `Container<ns1::Foo>` (precise)

**Options to discuss:**
- Option A: Qualified template args (fixes #102, straightforward)
- Option B: Template USR (unique but not human-readable)

**Context needed from domain expert:**
- How critical is this ambiguity issue in practice?
- Typical complexity/nesting depth of template arguments?
- Readability vs precision trade-off
- Search behavior expectations for template specializations

---

## Document Maintenance

This log captures design decisions and rationale from expert discussions. It supplements the main proposal document and will be used to:

1. Update proposal with finalized decisions
2. Guide implementation phase planning
3. Inform documentation and system prompt design
4. Provide historical context for future design reviews

**Last Updated:** 2026-01-06
**Next Session:** Resume at Q3: Template Specialization Qualified Names
