# Phase 3: Call Graph Enhancement - Comprehensive Test Plan

## Overview

This document defines comprehensive testing for Phase 3 features:
1. **Line-level call graph tracking** with exact call site locations
2. **Cross-reference extraction** from Doxygen tags (@see, @ref, @relates)
3. **Parameter documentation** extraction (@param, @tparam, @return)

## Test Organization

### Test File Structure

```
tests/
├── test_call_sites_extraction.py          # Call site line-level tracking
├── test_cross_references.py               # Cross-reference parsing
├── test_parameter_docs.py                 # Parameter documentation parsing
├── test_phase3_integration.py             # End-to-end integration tests
├── test_phase3_mcp_tools.py              # MCP tool enhancements
└── fixtures/
    └── phase3_samples/                    # Sample C++ code for testing
        ├── call_sites_example.cpp
        ├── cross_refs_example.cpp
        └── param_docs_example.cpp
```

## Unit Tests: Call Site Extraction

### File: `tests/test_call_sites_extraction.py`

#### Test 1: Basic Call Site Tracking
**Test ID:** CS-01
**Requirement:** FR-1.1, FR-1.2

```cpp
// Test fixture
void helper() { }

void caller() {
    helper();      // Line 5
}
```

**Expected:**
- call_sites table contains: (caller, helper, line=5)
- Verified via find_callers("helper") → call_sites array

**Assertions:**
- Call site count = 1
- Line number = 5
- Caller = "caller"

---

#### Test 2: Multiple Calls to Same Function
**Test ID:** CS-02
**Requirement:** FR-1.3

```cpp
void validate() { }

void process() {
    validate();    // Line 5
    // ...
    validate();    // Line 7
}
```

**Expected:**
- 2 call site records for (process → validate)
- Lines [5, 7]

**Assertions:**
- Call site count = 2
- Lines sorted ascending
- Same caller, same callee, different lines

---

#### Test 3: Calls in Different Control Flow Paths
**Test ID:** CS-03
**Requirement:** FR-1.5

```cpp
void action() { }

void controller(bool flag) {
    if (flag) {
        action();  // Line 5
    } else {
        action();  // Line 7
    }
}
```

**Expected:**
- 2 call sites even in different branches

**Assertions:**
- Call site count = 2
- Lines [5, 7] tracked
- Both calls from same caller function

---

#### Test 4: Method Calls (Member Functions)
**Test ID:** CS-04
**Requirement:** FR-1.5

```cpp
class Processor {
public:
    void process() {
        validate();     // Line 4 (member call)
        helper();       // Line 5 (static/free function)
    }

    void validate() { }
};

void helper() { }
```

**Expected:**
- Call to member function tracked
- Call to free function tracked

**Assertions:**
- 2 call sites from Processor::process
- Target functions correctly identified

---

#### Test 5: Function Pointers vs Direct Calls
**Test ID:** CS-05
**Requirement:** FR-1.6

```cpp
void callback() { }

void setup() {
    auto fn = callback;   // NOT a call (DECL_REF_EXPR)
    fn();                 // Call via function pointer (CALL_EXPR)
    callback();           // Direct call (CALL_EXPR)
}
```

**Expected:**
- 2 call sites (lines with actual calls)
- Function pointer assignment NOT tracked as call

**Assertions:**
- Call site count = 2
- Assignment line NOT in call_sites

---

#### Test 6: Lambda Captures
**Test ID:** CS-06
**Requirement:** FR-1.5

```cpp
void external() { }

void parent() {
    auto lambda = []() {
        external();       // Line 5
    };
    lambda();            // Line 7
}
```

**Expected:**
- Call from lambda to external tracked
- Lambda invocation tracked

**Assertions:**
- Call site from lambda context
- Line numbers correct

---

#### Test 7: Recursive Calls
**Test ID:** CS-07
**Requirement:** Edge case

```cpp
void recursive(int n) {
    if (n > 0) {
        recursive(n - 1);  // Line 3
    }
}
```

**Expected:**
- Self-referential call tracked
- Caller == Callee

**Assertions:**
- Call site exists
- caller_usr == callee_usr

---

#### Test 8: Template Function Calls
**Test ID:** CS-08
**Requirement:** Edge case

```cpp
template<typename T>
void process(T value) { }

void caller() {
    process<int>(42);     // Line 5
    process<float>(3.14); // Line 6
}
```

**Expected:**
- Template instantiations tracked separately (if libclang provides distinct USRs)
- OR tracked as single generic call (implementation-dependent)

**Assertions:**
- Call sites tracked
- Line numbers correct

---

## Unit Tests: Cross-Reference Extraction

### File: `tests/test_cross_references.py`

#### Test 9: Basic @see Tag Extraction
**Test ID:** XR-01
**Requirement:** FR-3.1

```cpp
/**
 * @brief Validates input
 * @see DataValidator::check
 */
void validate() { }
```

**Expected:**
- cross_references table: (validate, "see", "DataValidator::check")

**Assertions:**
- 1 cross-reference
- ref_type = "see"
- target = "DataValidator::check"

---

#### Test 10: Multiple @see Tags
**Test ID:** XR-02
**Requirement:** FR-3.6

```cpp
/**
 * @see functionA
 * @see functionB
 * @see ClassName::method
 */
void caller() { }
```

**Expected:**
- 3 cross-references

**Assertions:**
- Cross-reference count = 3
- All targets extracted

---

#### Test 11: @ref Tag Extraction
**Test ID:** XR-03
**Requirement:** FR-3.2

```cpp
/**
 * Uses @ref helper function
 */
void process() { }
```

**Expected:**
- 1 cross-reference with ref_type = "ref"

**Assertions:**
- ref_type = "ref"
- target = "helper"

---

#### Test 12: @relates Tag Extraction
**Test ID:** XR-04
**Requirement:** FR-3.3

```cpp
/**
 * @relates DataProcessor
 */
void helperFunction() { }
```

**Expected:**
- 1 cross-reference with ref_type = "relates"

**Assertions:**
- ref_type = "relates"
- target = "DataProcessor"

---

#### Test 13: Cross-Reference Resolution
**Test ID:** XR-05
**Requirement:** FR-3.5

```cpp
void target() { }

/**
 * @see target
 */
void source() { }
```

**Expected:**
- target resolved to USR if symbol exists in index
- target_usr populated

**Assertions:**
- target_usr is NOT NULL
- target_usr matches target function's USR

---

#### Test 14: Unresolved Cross-References
**Test ID:** XR-06
**Requirement:** FR-3.7

```cpp
/**
 * @see NonExistentFunction
 * @see ExternalLibrary::method
 */
void function() { }
```

**Expected:**
- 2 cross-references stored
- target stored as text
- target_usr = NULL (unresolved)

**Assertions:**
- Cross-references stored despite missing targets
- target_usr = NULL

---

#### Test 15: Malformed Doxygen Tags
**Test ID:** XR-07
**Requirement:** Error handling

```cpp
/**
 * @see
 * @see
 * @ref
 */
void function() { }
```

**Expected:**
- Empty/malformed tags ignored gracefully
- No crashes or exceptions

**Assertions:**
- No cross-references extracted (or empty strings filtered out)

---

#### Test 16: Mixed Tag Styles
**Test ID:** XR-08
**Requirement:** FR-3.1, FR-3.2, FR-3.3

```cpp
/**
 * @brief Main processor
 * @see Validator::validate
 * Uses @ref helper internally
 * @relates ProcessorGroup
 */
void process() { }
```

**Expected:**
- 3 cross-references (1 see, 1 ref, 1 relates)

**Assertions:**
- Each ref_type correct
- All targets extracted

---

## Unit Tests: Parameter Documentation

### File: `tests/test_parameter_docs.py`

#### Test 17: Basic @param Extraction
**Test ID:** PD-01
**Requirement:** FR-4.1

```cpp
/**
 * @param input The input string
 * @param flags Processing flags
 */
void process(const std::string& input, int flags) { }
```

**Expected:**
- 2 parameter_docs entries
- Names match function signature

**Assertions:**
- Parameter count = 2
- Names: ["input", "flags"]
- Descriptions match

---

#### Test 18: @tparam Template Parameter
**Test ID:** PD-02
**Requirement:** FR-4.2

```cpp
/**
 * @tparam T The data type
 * @param value The value to process
 */
template<typename T>
void process(T value) { }
```

**Expected:**
- 1 template param doc (T)
- 1 regular param doc (value)

**Assertions:**
- param_type = "tparam" for T
- param_type = "param" for value

---

#### Test 19: @return Documentation
**Test ID:** PD-03
**Requirement:** FR-4.3

```cpp
/**
 * @return The result code
 */
int compute() { return 0; }
```

**Expected:**
- 1 parameter_docs entry with param_type = "return"

**Assertions:**
- param_type = "return"
- description = "The result code"

---

#### Test 20: Parameter Direction ([in], [out])
**Test ID:** PD-04
**Requirement:** FR-4.6

```cpp
/**
 * @param[in] input Input data
 * @param[out] output Output buffer
 * @param[in,out] state State variable
 */
void process(const int* input, int* output, int* state) { }
```

**Expected:**
- 3 parameter_docs with direction field populated

**Assertions:**
- input: direction = "in"
- output: direction = "out"
- state: direction = "inout"

---

#### Test 21: Missing Parameter Documentation
**Test ID:** PD-05
**Requirement:** FR-4.7

```cpp
/**
 * @param a First param documented
 * (parameter b not documented)
 */
void func(int a, int b) { }
```

**Expected:**
- 1 parameter_doc for 'a'
- No entry for 'b' (or NULL description)

**Assertions:**
- Parameter 'a' has documentation
- Parameter 'b' either missing or NULL

---

#### Test 22: Parameter Name Mismatch
**Test ID:** PD-06
**Requirement:** Error handling

```cpp
/**
 * @param inputData The input (typo: actual name is "input")
 */
void process(int input) { }
```

**Expected:**
- Store documentation even if name mismatch
- Optionally log warning (debug level)

**Assertions:**
- Documentation stored with name "inputData"
- No crash or exception

---

#### Test 23: Variadic Parameters
**Test ID:** PD-07
**Requirement:** Edge case

```cpp
/**
 * @param format Format string
 * @param ... Variable arguments
 */
void printf_like(const char* format, ...) { }
```

**Expected:**
- 2 parameter_docs (format, ...)

**Assertions:**
- "..." captured as param_name if documented

---

#### Test 24: Multiple @return Tags (Invalid)
**Test ID:** PD-08
**Requirement:** Error handling

```cpp
/**
 * @return First return doc
 * @return Second return doc (invalid)
 */
int func() { return 0; }
```

**Expected:**
- Last @return wins, or first wins (implementation-defined)
- No crash

**Assertions:**
- Exactly 1 return documentation entry

---

## Integration Tests: MCP Tools

### File: `tests/test_phase3_mcp_tools.py`

#### Test 25: find_callers with Call Sites
**Test ID:** INT-01
**Requirement:** FR-2.1, FR-2.2

```cpp
void target() { }

void caller1() {
    target();  // Line 4
}

void caller2() {
    target();  // Line 8
}
```

**MCP Call:**
```json
find_callers("target")
```

**Expected Response:**
```json
{
  "function": "target",
  "callers": ["caller1", "caller2"],
  "call_sites": [
    {
      "file": "test.cpp",
      "caller": "caller1",
      "line": 4,
      "column": 5
    },
    {
      "file": "test.cpp",
      "caller": "caller2",
      "line": 8,
      "column": 5
    }
  ]
}
```

**Assertions:**
- call_sites array present
- 2 call sites
- Line numbers match source

---

#### Test 26: get_function_info with Parameters
**Test ID:** INT-02
**Requirement:** FR-6.1, FR-6.2

```cpp
/**
 * @brief Processes data
 * @param input Input data
 * @param flags Processing flags
 * @return Result code
 */
int process(const char* input, int flags) { return 0; }
```

**MCP Call:**
```json
get_function_info("process")
```

**Expected Response:**
```json
{
  "name": "process",
  "brief": "Processes data",
  "parameters": [
    {
      "name": "input",
      "type": "const char*",
      "doc": "Input data"
    },
    {
      "name": "flags",
      "type": "int",
      "doc": "Processing flags"
    }
  ],
  "return_doc": "Result code"
}
```

**Assertions:**
- parameters array present
- 2 parameters with docs
- return_doc present

---

#### Test 27: get_cross_references Tool
**Test ID:** INT-03
**Requirement:** FR-5

```cpp
void helperA() { }
void helperB() { }

/**
 * @see helperA
 * @ref helperB
 */
void caller() { }
```

**MCP Call:**
```json
get_cross_references("caller")
```

**Expected Response:**
```json
{
  "symbol": "caller",
  "references": [
    {
      "type": "see",
      "target": "helperA",
      "file": "test.cpp",
      "line": 10
    },
    {
      "type": "ref",
      "target": "helperB",
      "file": "test.cpp",
      "line": 10
    }
  ]
}
```

**Assertions:**
- 2 cross-references
- Types correct
- Targets resolved

---

#### Test 28: get_call_sites Tool
**Test ID:** INT-04
**Requirement:** FR-7

```cpp
void funcA() { }
void funcB() { }

void caller() {
    funcA();  // Line 5
    funcB();  // Line 6
}
```

**MCP Call:**
```json
get_call_sites("caller")
```

**Expected Response:**
```json
{
  "caller": "caller",
  "calls": [
    {
      "target": "funcA",
      "file": "test.cpp",
      "line": 5
    },
    {
      "target": "funcB",
      "file": "test.cpp",
      "line": 6
    }
  ]
}
```

**Assertions:**
- 2 calls
- Targets and lines correct

---

#### Test 29: Backward Compatibility Check
**Test ID:** INT-05
**Requirement:** NFR-3

**Test:**
- Call find_callers and verify "callers" array still present
- Verify old clients can ignore new fields
- Verify NULL fields omitted in JSON

**Assertions:**
- "callers" field unchanged
- New fields are additions, not replacements

---

## Integration Tests: End-to-End

### File: `tests/test_phase3_integration.py`

#### Test 30: Full Workflow with Real Project
**Test ID:** E2E-01

**Steps:**
1. Create sample C++ project with:
   - Multiple files with call chains
   - Documentation with @param, @see, @ref tags
   - Cross-references between files
2. Index project with Phase 3 enabled
3. Query call sites, cross-refs, parameter docs
4. Verify all data correct

**Assertions:**
- Indexing completes successfully
- All Phase 3 data stored
- Queries return expected results

---

#### Test 31: Performance Benchmark
**Test ID:** PERF-01
**Requirement:** NFR-1

**Test:**
- Index large sample project (1000+ functions)
- Measure indexing time with/without Phase 3
- Measure cache size increase

**Acceptance:**
- Indexing overhead <10%
- Cache size increase <10 MB per 100K symbols

---

#### Test 32: Schema Migration
**Test ID:** MIG-01
**Requirement:** NFR-3

**Test:**
1. Create cache with schema v7.0
2. Upgrade to schema v8.0
3. Verify old data preserved
4. Verify new tables created

**Assertions:**
- symbols table unchanged
- New tables exist
- No data loss

---

## Edge Case Tests

#### Test 33: Macro Expansion Calls
**Test ID:** EDGE-01

```cpp
#define CALL_HELPER() helper()

void helper() { }

void caller() {
    CALL_HELPER();  // Line 6 (macro expansion)
}
```

**Expected:**
- Call site tracked (if libclang expands macro)
- OR ignored (if macro not expanded)

**Assertion:**
- No crash, graceful handling

---

#### Test 34: Operator Overloading Calls
**Test ID:** EDGE-02

```cpp
class Wrapper {
public:
    void operator()() { }
};

void caller() {
    Wrapper w;
    w();  // Line 8 (operator() call)
}
```

**Expected:**
- Operator call tracked as call site

**Assertion:**
- Call site exists
- Target = "Wrapper::operator()"

---

#### Test 35: Deeply Nested Calls
**Test ID:** EDGE-03

```cpp
int c() { return 0; }
int b() { return c(); }
int a() { return b(); }
```

**Expected:**
- Call chains tracked: a→b, b→c

**Assertions:**
- 2 distinct call site records
- Correct callers and callees

---

#### Test 36: Unicode in Documentation
**Test ID:** EDGE-04

```cpp
/**
 * @param データ Input data (Japanese)
 * @return 結果 Result (Japanese)
 */
int process(int データ) { return 0; }
```

**Expected:**
- UTF-8 documentation stored correctly

**Assertions:**
- No encoding errors
- Japanese characters preserved

---

## Test Fixtures

### Sample Code: call_sites_example.cpp

```cpp
// Tests: CS-01, CS-02, CS-03
void helper() { }
void validate() { }

void caller() {
    helper();     // Line 6
    validate();   // Line 7
    validate();   // Line 8 (second call)
}

void conditional(bool flag) {
    if (flag) {
        helper(); // Line 13
    } else {
        helper(); // Line 15
    }
}
```

### Sample Code: cross_refs_example.cpp

```cpp
// Tests: XR-01 through XR-08
void targetA() { }
void targetB() { }
class RelatedClass { };

/**
 * @brief Main processor
 * @see targetA
 * @ref targetB
 * @relates RelatedClass
 */
void process() { }

/**
 * @see NonExistentFunction
 */
void withUnresolved() { }
```

### Sample Code: param_docs_example.cpp

```cpp
// Tests: PD-01 through PD-08

/**
 * @brief Basic function
 * @param input The input string
 * @param flags Processing flags
 * @return Success status
 */
int basicFunc(const char* input, int flags) {
    return 0;
}

/**
 * @tparam T Data type
 * @param value The value
 */
template<typename T>
void templateFunc(T value) { }

/**
 * @param[in] input Input buffer
 * @param[out] output Output buffer
 * @param[in,out] state State variable
 */
void withDirections(const int* input, int* output, int* state) { }
```

## Test Execution

### Running Tests

```bash
# Run all Phase 3 tests
pytest tests/test_call_sites_extraction.py -v
pytest tests/test_cross_references.py -v
pytest tests/test_parameter_docs.py -v
pytest tests/test_phase3_mcp_tools.py -v
pytest tests/test_phase3_integration.py -v

# Run all with coverage
pytest tests/test_*phase3* --cov=mcp_server --cov-report=html

# Run specific test
pytest tests/test_call_sites_extraction.py::test_basic_call_site_tracking -v
```

### Test Metrics

**Target Metrics:**
- Test count: 36+ tests
- Code coverage: ≥95% for Phase 3 code
- Pass rate: 100%
- Execution time: <30 seconds for all Phase 3 tests

## Success Criteria

**Phase 3 testing is complete when:**
1. ✅ All 36+ tests pass (100% pass rate)
2. ✅ Code coverage ≥95% for new Phase 3 code
3. ✅ Performance benchmarks within targets (NFR-1)
4. ✅ Edge cases handled gracefully
5. ✅ Integration tests demonstrate end-to-end functionality
6. ✅ Backward compatibility verified
7. ✅ No regressions in existing Phase 1 & 2 tests

## Test Schedule

**Week 1: Call Sites (Phase 3.1)**
- Tests CS-01 through CS-08
- Integration test INT-01

**Week 2: Cross-References (Phase 3.2)**
- Tests XR-01 through XR-08
- Integration test INT-03

**Week 2-3: Parameter Docs (Phase 3.3)**
- Tests PD-01 through PD-08
- Integration tests INT-02, INT-04

**Week 3: Integration & Edge Cases (Phase 3.4)**
- Tests INT-05, E2E-01, PERF-01, MIG-01
- Tests EDGE-01 through EDGE-04
- Final verification

---

**Document Version:** 1.0
**Created:** 2025-12-09
**Status:** Draft - Ready for implementation
**Total Tests:** 36+ tests across 5 test files
