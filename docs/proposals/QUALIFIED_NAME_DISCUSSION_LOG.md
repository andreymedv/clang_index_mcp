# Qualified Name Support - Discussion Log

**Status:** 🟡 In Progress
**Started:** 2026-01-06
**Participants:** Domain Expert (Andrey), System Analyst (Claude Code)

---

## Discussion Progress

### Completed Questions ✅

- **Q1: Partial Qualification Matching Rules** ✅ RESOLVED
- **Q2: Function Overload Identification** ✅ RESOLVED
- **Q3: Template Specialization Qualified Names** ✅ RESOLVED
- **Q4: Leading `::` Semantics** ✅ RESOLVED (discussed alongside Q1)
- **Q5: Namespace Filtering Scope** ✅ RESOLVED (discussed alongside Q1)
- **Q6: Performance vs Precision Trade-offs** ✅ RESOLVED
- **Q7: Anonymous Namespace Handling** ✅ RESOLVED
- **Q8: Nested Class Qualified Names** ✅ RESOLVED
- **Q9: Backward Compatibility - Schema Migration** ✅ RESOLVED
- **Q10: LLM Guidance - Tool Descriptions** ✅ RESOLVED

### New Research Tracks 🔬

- **Q11: Template Function Search Logic** - Separate investigation (related to #85, #99, #101)
- **Q12: Type Alias Support** - Separate investigation (identified during Q3 discussion)

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

### Q3: Template Specialization Qualified Names ✅

**Decision Date:** 2026-01-06
**Decision:** Qualified Canonical Template Args (without full alias support in v1)

#### Final Specification

**1. Store and return canonical (expanded) types:**
```cpp
// In code:
using FooPtr = std::unique_ptr<ns1::Foo>;
class A : public Container<FooPtr> {};

// What libclang provides:
cursor.type.get_canonical().spelling → "Container<std::unique_ptr<ns1::Foo>>"

// What we store and return:
{
  "base_classes": ["Container<std::unique_ptr<ns1::Foo>>"]
}
```

**2. Search matching:**
- `Container<FooPtr>` and `Container<std::unique_ptr<ns1::Foo>>` → same type (one result)
- libclang's canonical type ensures type identity
- No manual USR mapping needed in v1

**3. Display strategy:**
- Return fully qualified canonical names to LLM
- LLM decides what to show user (per system prompt rules)

**4. Type aliases NOT supported in v1:**
- **Documented limitation:** "Search by canonical type names (aliases expanded)"
- Users must use expanded form in searches
- NOT blocking for basic usage

**5. Implementation:**
- Use `cursor.type.get_canonical()` for all template arguments
- Store fully qualified canonical names
- ~2-3 days implementation

#### Deferred to Q12: Type Alias Support

**Scope of Q12 (separate research track):**

**Problem identified:**
- Intensive use of type aliases in real projects (containers, smart pointers, tagged types)
- Nested aliases: `using A = B; using B = C;`
- Template aliases: `template<T> using Vec = vector<T>;`
- Alias collisions: same alias name in different namespaces/classes
- Deep template nesting with aliases: `optional<vector<variant<Type1<int>, Type2<double>>>>`

**Real-world characteristics:**
- Deep nesting typical, not exception
- Solved in code by intensive alias usage
- Canonical names unreadable (multi-line compiler errors)
- Multiple as-written forms per type possible

**Scope for Q12:**
- Track alias declarations: `using Ptr = unique_ptr<Foo>`
- Store alias→canonical→USR mappings
- Support search by alias name
- Multiple as-written representations per type
- Chain resolution (alias→alias→type)
- Simple, template, and nested aliases

**Complexity estimate:** 3-4 weeks (separate from qualified name support)

**Not blocking:** Q3.9 - absence doesn't block MCP server usage

**To be prioritized:** After Q1-Q10 completion, when forming full feature list

---

### Q6: Performance vs Precision Trade-offs ✅

**Decision Date:** 2026-01-06
**Decision:** Precision First, Performance Later

#### Final Specification

**1. Performance targets:**
- Acceptable latency: **100ms per query**
- Regex searches: **100-200ms acceptable**
- No premature optimization in v1

**2. Rationale:**
- LLM reasoning: **1-2 orders of magnitude slower** than tool execution
- Tool latency **not the bottleneck** in overall workflow
- Database size: **>500K symbols** (8000+ cpp files, 14000 total files)
- Focus on **correctness and precision**, not speed

**3. Implementation approach:**
- Use straightforward algorithms (Python string methods for patterns)
- SQLite FTS5 for full-text search (already fast enough)
- LIKE queries acceptable for qualified name suffix matching
- Regex filtering in Python acceptable (simple, maintainable)

**4. Optimization strategy:**
- **Defer optimization** until performance becomes actual problem
- If needed later: Add specialized indexes, caching, etc.
- Benchmark on real project, not theoretical concerns

**5. Pattern optimization note:**
- Regex patterns like `".*::View"`, `"app::core::.*"` can use Python string methods
- `startswith()`, `endswith()`, `in` - faster than full regex
- Implement smart detection: use string methods when possible, fallback to regex

**Decision:** No performance optimization work in initial phases. Ship functionality first, optimize if needed.

---

### Q7: Anonymous Namespace Handling ✅

**Decision Date:** 2026-01-06
**Decision:** libclang as-is (Option A)

#### Final Specification

**1. Use standard libclang representation:**
- Store and return: `"(anonymous namespace)::Internal"`
- No custom formatting or special handling

**2. Context from real project:**
- Actively used for file-scope entities
- No scenarios requiring distinction between anonymous namespaces in different files
- Potential use: understanding symbol has file scope (no access from other files)
- This information implicit in `"(anonymous namespace)"` representation

**3. Implementation:**
- Accept libclang's naming as-is
- No additional processing needed

**Decision:** Simple, standard approach sufficient for known use cases.

---

### Q8: Nested Class Qualified Names ✅

**Decision Date:** 2026-01-06
**Decision:** Just qualified_name (no separate parent_class field)

#### Final Specification

**1. Storage:**
```cpp
namespace ns {
  class Outer {
    class Inner {};
  };
}

// Store as:
qualified_name: "ns::Outer::Inner"
namespace: "ns::Outer"  // includes parent class
```

**2. No separate parent_class field:**
- No distinction between namespace components and parent class components
- `namespace` field contains full prefix (namespaces + parent classes)
- Simpler schema, sufficient for use cases

**3. Context from real project:**
- Nested classes rare
- Some actively used inner types (e.g., `Outer::Inner`)
- Typically referenced with parent class name
- No scenarios requiring explicit namespace/class distinction
- No concerns with fully qualified name approach

**4. Implementation:**
- Store `qualified_name` as-is from libclang
- No special processing for nested classes

**Decision:** Simplicity over complexity. No known use cases require separate parent_class field.

---

### Q9: Backward Compatibility - Schema Migration ✅

**Decision Date:** 2026-01-06
**Decision:** Auto-recreation (Option A)

#### Final Specification

**1. Current behavior (continue):**
- Schema version mismatch → auto-delete cache and re-index
- No migration implementation
- Clean slate on schema changes

**2. Rationale:**
- Project in MVP/experimental phase (see Development Philosophy below)
- Schema changes frequent during development
- Re-indexing already optimized (multi-process parallelism)
- Few users work with truly large codebases
- Full re-indexing not frequent task

**3. Analogy:**
- Similar to clean build directories and full rebuild in C++ projects
- Developers not afraid of occasional full rebuilds
- Cache regeneration is similar concept

**4. Future consideration:**
- Can add migration when project stabilizes (post-MVP)
- Not priority for continuous delivery approach

**Decision:** Auto-recreation sufficient for current development phase and user base.

---

### Q10: LLM Guidance - Tool Descriptions ✅

**Decision Date:** 2026-01-06
**Decision:** Detailed with Lightweight LLM Adaptation (Modified Option A)

#### Final Specification

**1. Approach: Adaptive detailed descriptions**
- NOT simply verbose descriptions (token-heavy, ineffective)
- NOT concise with external links (LLMs ignore links)
- **Adapted language for lightweight LLM interpretation**

**2. Problem identified:**
- Lightweight LLMs poorly trained on C++ qualified name concepts
- What's obvious to Opus/Sonnet/Haiku has low weight for qwen3-4b/30b, gpt-oss-20b
- Technical terminology may not match their training
- Core issue: understanding qualified → unqualified extraction

**3. Strategy:**
- Analyze lightweight LLM interpretation patterns
- Use explicit, simple language vs technical terms
- Provide clear examples in descriptions
- Avoid assumptions about C++ knowledge
- Test descriptions with target LLMs

**4. Iterative improvement:**
- Post-deployment: analyze reasoning logs
- Identify misinterpretations
- Refine descriptions based on observed LLM behavior
- Continuous adaptation to lightweight LLM capabilities

**5. Critical constraints in system prompt:**
- Tool descriptions alone insufficient (as observed)
- Explicit system prompt instructions for critical behaviors
- Dual approach: tool descriptions + system prompt

**Decision:** Detailed descriptions optimized for lightweight LLM comprehension, with iterative refinement based on observed behavior.

---

## libclang Assumptions Validation ✅

**Validation Date:** 2026-01-06
**Method:** Automated experiments using test_libclang_behavior.py
**Status:** All critical assumptions validated

### Experiment Execution

**Decision Point:**
During Q3-Q10 discussion, domain expert correctly identified that libclang experiments should happen BEFORE prioritization session (not after), because TC4 results could significantly affect Q3/Q12 dependency relationship.

**Experiment Framework Created:**
- `docs/experiments/LIBCLANG_VALIDATION_EXPERIMENT.md` - Detailed experiment guide
- `scripts/experiments/test_libclang_behavior.py` - Automated test script
- `docs/experiments/LIBCLANG_EXPERIMENT_RESULTS_TEMPLATE.md` - Results template
- `docs/experiments/README.md` - Quick start guide

**Test Cases:**
- TC1: Simple Type Alias
- TC2: Nested Type Aliases
- TC3: Template Type Alias
- TC4: Base Class with Alias (CRITICAL)
- TC5: Template Function Detection
- TC6: Template Class Specialization

### Critical Finding: TC4 (Base Class with Alias)

**Test Code:**
```cpp
namespace ns1 { class Foo {}; }
using FooPtr = std::unique_ptr<ns1::Foo>;
template<typename T> class Container {};
class Derived : public Container<FooPtr> {};
```

**Question Tested:**
Does `cursor.type.get_canonical()` expand type aliases AND preserve namespace qualification in template arguments?

**Result:**
```
canonical_spelling: Container<std::unique_ptr<ns1::Foo>>
verdict: ALIAS EXPANDED + QUALIFIED - Q3 works!
```

**What This Validates:**
- ✅ Type aliases ARE expanded by libclang canonical types
- ✅ Namespace qualification IS preserved in template arguments (ns1::Foo)
- ✅ Q3 assumption (store canonical types) is correct
- ✅ Q12 (Type Alias Support) does NOT block Q3 implementation
- ✅ Phase 1 timeline unchanged (~2-3 weeks)

### Template Function Detection: TC5

**Test Code:**
```cpp
template<typename T> void func(T);        // Generic template
template<> void func<int>(int);           // Explicit specialization
void func(double);                        // Regular overload
```

**Question Tested:**
Can libclang distinguish template functions from specializations from regular overloads?

**Result:**
```
functions: [
  {kind: "FUNCTION_TEMPLATE", ...},           // Generic template
  {kind: "FUNCTION_DECL", displayname: "func<int>", ...},  // Specialization
  {kind: "FUNCTION_DECL", displayname: "func", ...}        // Overload
]
```

**What This Validates:**
- ✅ `cursor.kind` successfully distinguishes templates (FUNCTION_TEMPLATE) from regular functions (FUNCTION_DECL)
- ✅ Explicit specializations can be identified by `<>` in displayname
- ⚠️ `cursor.specialized_cursor_template()` less reliable (returns 'unknown' in tests)
- ✅ Q2 `is_template_specialization` field feasible using `cursor.kind` + displayname analysis

### Impact on Q2 Implementation

**Original approach (from Q2 discussion):**
Use `cursor.specialized_cursor_template()` to detect template specializations.

**Validated approach (from experiments):**
Use simpler detection:
```python
def is_template_specialization(cursor) -> bool:
    if cursor.kind == CursorKind.FUNCTION_TEMPLATE:
        return False  # Generic template
    if cursor.kind == CursorKind.FUNCTION_DECL:
        # Check displayname for template arguments
        return '<' in cursor.displayname and '>' in cursor.displayname
    return False
```

**Rationale:**
- More reliable (tested in practice)
- Simpler implementation
- No dependency on potentially unreliable API
- Distinguishes generic templates, specializations, regular overloads

### Impact on Q3 Implementation

**No changes needed:**
- Original Q3 decision (use canonical types) validated by experiments
- Implementation can proceed as planned
- No workarounds or adjustments required
- Q12 (Type Alias Support) confirmed as separate concern

### Summary of Validated Assumptions

**Type Alias Resolution (TC1-TC4):**
- ✅ Simple aliases expanded: `IntPtr` → `int*`
- ✅ Nested aliases resolved: `Ptr2` → `Ptr1` → `int*`
- ✅ Template aliases expanded: `Vec<int>` → `std::vector<int>`
- ✅ Aliases in template args expanded AND qualified

**Template Metadata (TC5-TC6):**
- ✅ Template function detection feasible via `cursor.kind`
- ✅ Specialization detection via displayname analysis
- ✅ Foundation for Q2 `is_template_specialization` field

**Prioritization Impact:**
- ✅ Q3 implementation: no blockers, proceed as planned
- ✅ Q12 (Type Alias Support): stays deferred (NOT blocking)
- ✅ Phase 1 timeline: no changes (~2-3 weeks)
- ✅ Q2 implementation: simplified approach using cursor.kind

**Experiment Time:**
- Estimated: 2-3 hours
- Actual: ~40 minutes (automated script + quick execution)

---

## Project Development Philosophy 🎯

**Documented:** 2026-01-06
**Source:** Domain expert guidance during Q6 discussion

### Continuous Delivery Approach

**1. Project Status:**
- **MVP/Experimental phase** - not production-ready
- Active experimentation and major changes ongoing
- Recent stabilization efforts = making testable after big changes
- NOT formal releases - working checkpoints

**2. Development Mindset:**

**❌ NOT thinking in terms of:**
- "What must be in v1/v2/v3"
- Formal version numbers and release planning
- Feature-complete milestones

**✅ YES thinking in terms of:**
- "What is higher priority"
- "What order is technically most efficient"
- "What enables other work" (technical dependencies)
- Continuous incremental improvements

**3. Prioritization Criteria:**

**A. Low-hanging fruit:**
- Small effort, high value → **do immediately**
- Don't defer simple improvements
- Quick wins compound

**B. Technical dependencies:**
- What enables other work comes first
- Build foundation before dependent features
- Minimize blocking relationships

**C. Maintain working state:**
- Usable after intermediate steps
- Can use project during development
- Temporary degradation acceptable if needed

**D. Avoid throwaway work:**
- Minimize rework and refactoring
- Choose architecture that won't require major changes
- Incremental evolution over replacements

**4. Acceptable Trade-offs:**

**Temporary functionality degradation:**
- OK if needed for progress toward better solution
- Document what's temporarily missing
- Plan restoration/improvement

**Partial features:**
- OK if they don't break existing usage
- Deliver incrementally
- Document known limitations

**Documented limitations:**
- Better than half-baked implementations
- Clear communication of current state
- Plan for future improvement

**5. Stability Points:**

**Not formal releases:**
- Working checkpoints between features
- Testable state after major changes
- Allows real-world usage and feedback

**When to stabilize:**
- After major architectural changes
- Before starting next significant feature
- When accumulated changes need validation

**6. Example Application:**

> "If we can add something with small effort - do it. Otherwise, choose sequence that minimizes rework and keeps project working at intermediate steps."

**Translation to decisions:**
- Don't defer Q6 performance optimization → will optimize if/when needed
- Don't over-engineer Q9 schema migration → auto-recreation sufficient for now
- Do implement Q1-Q5 properly → foundation for everything else
- Do document Q12 (type aliases) limitation → plan for future, don't block now

**7. Contrast with Traditional Approach:**

| Traditional | Continuous Delivery (Our Approach) |
|-------------|-----------------------------------|
| Plan all features for v1 | Implement by priority |
| Feature-complete releases | Working checkpoints |
| Avoid breaking changes | Acceptable if needed for progress |
| Formal versioning | Experimental/stable states |
| Complete before ship | Ship and iterate |

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

## Discussion Complete ✅

**Status:** All questions (Q1-Q10) resolved + libclang assumptions validated
**Date completed:** 2026-01-06
**Experiments completed:** 2026-01-06

### Summary of Decisions

**Core Qualified Name Support (Q1-Q5):**
- ✅ Component-based suffix matching
- ✅ Return all function overloads
- ✅ Canonical template args (aliases deferred to Q12)
- ✅ Leading `::` = exact match
- ✅ No separate namespace parameter (use regex)

**Implementation Approach (Q6-Q10):**
- ✅ Precision first, optimize later (100ms acceptable)
- ✅ libclang as-is for anonymous namespaces
- ✅ Simple qualified_name for nested classes
- ✅ Auto-recreation for schema changes
- ✅ Lightweight LLM-adapted tool descriptions

**New Research Tracks Identified:**
- 🔬 Q11: Template Function Search Logic (hundreds of instantiations, token economy)
- 🔬 Q12: Type Alias Support (3-4 weeks, intensive real-world usage)

### Next Steps

1. ✅ **libclang experiments:** Assumptions validated - Q3 works, Q12 stays deferred
2. **Prioritization session:** Review all identified features/improvements
3. **Implementation sequencing:** Order by technical dependencies and value
4. **Implementation planning:** Begin Phase 1 planning based on validated decisions

---

## Document Maintenance

This log captures design decisions and rationale from expert discussions. It supplements the main proposal document and will be used to:

1. Guide implementation phase planning
2. Inform documentation and system prompt design
3. Provide historical context for future design reviews
4. Support prioritization of Q11, Q12, and other improvements

**Last Updated:** 2026-01-06
**Status:** Discussion complete - ready for prioritization and planning
