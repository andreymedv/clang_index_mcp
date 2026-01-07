# libclang Validation Experiment

**Purpose:** Validate critical assumptions before prioritization session
**Date:** 2026-01-06
**Estimated time:** 2-3 hours
**Impact:** May significantly affect Q3/Q12 prioritization

---

## Critical Questions to Answer

### Question 1: Type Alias Resolution (CRITICAL for Q3/Q12)

**Assumption to validate:**
> Q3 decision assumes: `cursor.type.get_canonical()` automatically expands type aliases

**What to check:**
```cpp
using FooPtr = std::unique_ptr<Foo>;
class A : public Container<FooPtr> {};
```

**Expected (our assumption):**
- `cursor.type.get_canonical().spelling` → `"Container<std::unique_ptr<Foo>>"`

**If wrong:**
- Returns `"Container<FooPtr>"` → Q12 becomes blocker for Q3
- Increases Phase 1 from ~3 weeks to ~6-7 weeks

---

### Question 2: Template Specialization Detection (IMPORTANT for Q2)

**Assumption to validate:**
> Q2 decision: Add `is_template_specialization: bool` field to distinguish overloads from templates

**What to check:**
- How to detect if function/class is template specialization?
- What libclang APIs available?
- Can distinguish: generic template vs explicit specialization vs instantiation?

**Expected:**
- `cursor.kind` or `cursor.specialized_cursor_template()` provides this info

---

### Question 3: Template Function Metadata (IMPORTANT for Q11)

**Assumption to validate:**
> Q11 scope: Need to distinguish template functions from regular overloads

**What to check:**
```cpp
template<typename T> void foo(T);        // Generic template
template<> void foo<int>(int);           // Explicit specialization
void foo(double);                        // Regular overload
```

**Expected:**
- Can extract template parameters
- Can detect explicit specializations
- Can distinguish from implicit instantiations

---

## Test Cases

### TC1: Simple Type Alias
```cpp
using IntPtr = int*;
class Test {
    IntPtr member;
};
```

**Check:**
- `member` type canonical form
- Does it expand to `int*`?

---

### TC2: Nested Type Aliases
```cpp
using Ptr1 = int*;
using Ptr2 = Ptr1;
class Test {
    Ptr2 member;
};
```

**Check:**
- Chain resolution
- Final canonical form = `int*`?

---

### TC3: Template Type Aliases
```cpp
template<typename T>
using Vec = std::vector<T>;

class Test {
    Vec<int> member;
};
```

**Check:**
- Template alias expansion
- Canonical form = `std::vector<int>`?

---

### TC4: Base Class with Alias
```cpp
namespace ns1 { class Foo {}; }
using FooPtr = std::unique_ptr<ns1::Foo>;
template<typename T> class Container {};

class Derived : public Container<FooPtr> {};
```

**Check (CRITICAL):**
- `Derived` base class canonical name
- Is it `Container<std::unique_ptr<ns1::Foo>>` or `Container<FooPtr>`?

---

### TC5: Template Function Detection
```cpp
template<typename T> void func(T);       // Generic
template<> void func<int>(int);          // Explicit specialization
void func(double);                       // Overload
```

**Check:**
- How to distinguish these three?
- What metadata available?

---

### TC6: Template Class Specialization
```cpp
template<typename T> class Container {};
template<> class Container<int> { void special(); };
```

**Check:**
- Detect `Container<int>` is specialization
- Access to generic template info?

---

## Tools and Setup

### Prerequisites

1. **libclang Python bindings installed:**
   ```bash
   # Should already be available in mcp_env
   source mcp_env/bin/activate
   python -c "import clang.cindex; print(clang.cindex.__file__)"
   ```

2. **Test script location:**
   ```bash
   # Will be created at:
   scripts/experiments/test_libclang_behavior.py
   ```

3. **Test code samples:**
   ```bash
   # Will be created at:
   scripts/experiments/test_samples/
   ```

---

## Running the Experiments

### Step 1: Prepare Environment

```bash
cd /path/to/clang_index_mcp
source mcp_env/bin/activate

# Verify libclang available
python scripts/experiments/test_libclang_behavior.py --verify
```

### Step 2: Run Quick Tests

```bash
# Test all scenarios (takes ~2-3 minutes)
python scripts/experiments/test_libclang_behavior.py --all

# Or test individually:
python scripts/experiments/test_libclang_behavior.py --test tc1
python scripts/experiments/test_libclang_behavior.py --test tc4  # CRITICAL
```

### Step 3: Run on Real Project (Optional)

```bash
# Test on your actual codebase
python scripts/experiments/test_libclang_behavior.py \
  --real-project /path/to/your/project \
  --sample-size 10
```

This will:
- Sample 10 random files with base classes
- Check how aliases are resolved in real code
- Report statistics

---

## Interpreting Results

### Critical Decision Points

**Result Set A: Aliases ARE expanded**
```
TC4: Base class canonical = "Container<std::unique_ptr<ns1::Foo>>"
```
**Conclusion:** ✅ Q3 works as planned, Q12 stays deferred
**Action:** Continue with prioritization as discussed

---

**Result Set B: Aliases NOT expanded**
```
TC4: Base class canonical = "Container<FooPtr>"
```
**Conclusion:** ❌ Q3 BLOCKED by Q12
**Action:**
- Re-evaluate Q3/Q12 dependency
- Q12 priority increases significantly
- Phase 1 timeline increases 2x

---

**Result Set C: Partial expansion**
```
TC4: Base class canonical = "Container<unique_ptr<ns1::Foo>>"
     (namespace prefix missing from template arg)
```
**Conclusion:** ⚠️ Need workaround in Q3
**Action:**
- Add namespace resolution for template args
- Increases Q3 complexity slightly

---

### Template Metadata Check

**If template detection works:**
```
TC5:
- Generic template: cursor.kind = FUNCTION_TEMPLATE
- Specialization: cursor.specialized_cursor_template() returns template
- Overload: cursor.kind = FUNCTION_DECL (no template link)
```
**Conclusion:** ✅ Q2 `is_template_specialization` feasible

**If template detection unclear:**
**Conclusion:** ⚠️ Need alternative approach for Q2 field

---

## Recording Results

### Template for Recording

Create file: `docs/experiments/LIBCLANG_EXPERIMENT_RESULTS.md`

```markdown
# libclang Experiment Results

**Date:** 2026-01-XX
**Operator:** [Your Name]
**Environment:**
- OS: [Linux/macOS/Windows]
- Python version: [X.X.X]
- libclang version: [X.X.X]

---

## TC1: Simple Type Alias

**Code:**
```cpp
using IntPtr = int*;
class Test { IntPtr member; };
```

**Results:**
- member type: [what you see]
- canonical type: [expanded or not?]
- spelling: [exact string]

**Conclusion:** [works as expected / unexpected behavior]

---

## TC4: Base Class with Alias (CRITICAL)

**Code:**
```cpp
[copy from test]
```

**Results:**
- Base class type: [...]
- Canonical form: [...]
- Expanded?: YES/NO

**Conclusion:** [Q3 assumptions valid / need adjustment]

---

[Continue for all TCs...]

## Summary

### Critical Findings:
1. Type aliases: [expanded / not expanded / partially]
2. Template detection: [feasible / needs workaround]
3. Impact on Q3/Q12: [no change / significant change]

### Recommendations:
- [What should be done before prioritization]
- [Any surprises or concerns]
```

---

## Expected Outcomes

### Outcome A: All Assumptions Valid ✅
- Type aliases expanded by canonical
- Template detection clear
- **Action:** Proceed with prioritization as planned

### Outcome B: Aliases Not Expanded ❌
- Q12 becomes dependency for Q3
- **Action:** Adjust prioritization, Q12 moves up

### Outcome C: Mixed Results ⚠️
- Some assumptions valid, some not
- **Action:** Adjust specific tasks, spike needed solutions

---

## Questions During Experiment

**If you encounter:**
- Unexpected libclang behavior → Document it, we'll analyze together
- Unclear API usage → Check mcp_server/cpp_analyzer.py for current usage patterns
- Compilation errors in test code → Simplify test case, focus on core question
- Missing libclang features → Note limitation, we'll find workaround

**Get help:**
- Share results.md in next session
- I'll help interpret and decide next steps
- We'll adjust prioritization based on findings

---

## Success Criteria

- ✅ All 6 test cases executed
- ✅ Critical TC4 result documented
- ✅ Template detection feasibility assessed
- ✅ Clear decision on Q3/Q12 dependency
- ✅ Results recorded for prioritization session

---

**Estimated time breakdown:**
- Setup: 15 minutes
- Running tests: 30 minutes
- Real project sampling: 30 minutes (optional)
- Documentation: 30 minutes
- Analysis with Claude: 30 minutes

**Total: 2-3 hours**

Good luck! Я буду помогать с анализом результатов. 🔬
