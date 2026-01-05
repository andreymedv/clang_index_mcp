# Validation Test Plan - Manual Testing Observations

**Purpose:** Systematically validate observations from LM Studio testing and identify root causes
**Status:** 🔴 Not Started
**Related:** [docs/MANUAL_TESTING_OBSERVATIONS.md](MANUAL_TESTING_OBSERVATIONS.md)
**Related Issues:** #85 (Template Information Tracking)

---

## Overview

Manual testing with lightweight LLMs revealed several potential issues with MCP tools. This plan defines controlled test cases to:

1. **Validate observations** - Reproduce issues in controlled environment (SSE + curl)
2. **Identify root causes** - Determine if problems are tool-specific or systemic
3. **Expand testing** - Check if issues affect other similar tools
4. **Document behavior** - Create baseline for future fixes

---

## Test Environment Setup

```bash
# Start SSE server with debug logging
MCP_DEBUG=1 PYTHONUNBUFFERED=1 python -m mcp_server.cpp_mcp_server --transport sse --port 8000

# Create test project (examples/template_test/)
mkdir -p examples/template_test
cd examples/template_test

# Set project directory
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
    "params": {
      "name": "set_project_directory",
      "arguments": {"path": "/home/andrey/repos/cplusplus_mcp/examples/template_test"}
    }
  }' | jq -r '.result.content[0].text'

# Wait for indexing
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
    "params": {"name": "get_indexing_status", "arguments": {}}
  }' | jq '.result.content[0].text | fromjson | .metadata.completion_percentage'
```

---

## Test Cases

### TC1: Qualified Names in search_classes

**Observation:** #2 - Qualified names don't work
**Tools to test:** `search_classes`, `search_functions`, `search_symbols`
**Hypothesis:** Pattern matching operates on unqualified `name` field

#### Test File: `qualified_names.h`
```cpp
namespace ns1 {
    class View { };
    void render() { }
    int globalVar = 42;
}

namespace ns2 {
    class View { };
    void render() { }
    int globalVar = 100;
}

// Global namespace
class View { };
void render() { }
```

#### Test Steps:

**1.1 search_classes with qualified name**
```bash
# Expected: Should find ns1::View
# Actual: ?
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 10, "method": "tools/call",
    "params": {
      "name": "search_classes",
      "arguments": {"pattern": "ns1::View"}
    }
  }' | jq -r '.result.content[0].text'
```

**1.2 search_classes with unqualified name**
```bash
# Expected: Should find all 3 View classes
# Actual: ?
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 11, "method": "tools/call",
    "params": {
      "name": "search_classes",
      "arguments": {"pattern": "View"}
    }
  }' | jq -r '.result.content[0].text'
```

**1.3 search_functions with qualified name**
```bash
# Test if issue affects functions too
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 12, "method": "tools/call",
    "params": {
      "name": "search_functions",
      "arguments": {"pattern": "ns1::render"}
    }
  }' | jq -r '.result.content[0].text'
```

**1.4 search_symbols with qualified name**
```bash
# Test if issue affects symbols too
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 13, "method": "tools/call",
    "params": {
      "name": "search_symbols",
      "arguments": {"pattern": "ns1::globalVar"}
    }
  }' | jq -r '.result.content[0].text'
```

**1.5 Regex pattern with namespace**
```bash
# Try regex to match qualified names
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 14, "method": "tools/call",
    "params": {
      "name": "search_classes",
      "arguments": {"pattern": ".*::View"}
    }
  }' | jq -r '.result.content[0].text'
```

#### Expected Results:
- **If observation is correct:** Qualified names return empty results
- **Root cause identified:** Check if `symbol_info.name` contains qualified or unqualified name
- **Affected tools:** Determine if all search tools have same issue

#### Success Criteria:
- [ ] Reproduce empty results with qualified names
- [ ] Confirm unqualified names work
- [ ] Identify which tools are affected
- [ ] Check SQLite schema: does `symbols` table store qualified_name separately?

---

### TC2: Namespace Disambiguation

**Observation:** #3 - No mechanism to filter by namespace
**Tools to test:** `search_classes`, `search_functions`, `get_class_info`
**Hypothesis:** Results include all matches regardless of namespace

#### Test File: Same as TC1 (`qualified_names.h`)

#### Test Steps:

**2.1 Search returns multiple namespace matches**
```bash
# Expected: Returns ns1::View, ns2::View, ::View
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 20, "method": "tools/call",
    "params": {
      "name": "search_classes",
      "arguments": {"pattern": "View"}
    }
  }' | jq -r '.result.content[0].text'
```

**2.2 Verify qualified_name in results**
```bash
# Check if results contain qualified_name field for disambiguation
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 21, "method": "tools/call",
    "params": {
      "name": "search_classes",
      "arguments": {"pattern": "View"}
    }
  }' | jq '.result.content[0].text | fromjson | .data[] | {name, qualified_name, namespace}'
```

**2.3 get_class_info with ambiguous name**
```bash
# Expected: Returns first match or error?
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 22, "method": "tools/call",
    "params": {
      "name": "get_class_info",
      "arguments": {"class_name": "View"}
    }
  }' | jq '.'
```

#### Success Criteria:
- [ ] Confirm no namespace filtering available
- [ ] Verify qualified_name is present in results (for user disambiguation)
- [ ] Document behavior of tools when multiple matches exist
- [ ] Determine if this is API design issue or missing parameter

---

### TC3: Template Class Search

**Observation:** #5 - Template classes not found by name
**Tools to test:** `search_classes`, `get_class_info`, `get_derived_classes`
**Hypothesis:** Template specializations stored separately from generic template
**Related:** Issue #85 (Template Information Tracking)

#### Test File: `templates.h`
```cpp
// Generic template definition
template<typename T>
class Container {
public:
    T value;
    void store(T v) { value = v; }
};

// Explicit specializations
template<>
class Container<int> {
public:
    int value;
    void store(int v) { value = v; }
    void optimized() { } // extra method
};

// Partial specialization
template<typename T>
class Container<T*> {
public:
    T* value;
    void store(T* v) { value = v; }
};

// Classes derived from specializations
class IntContainer : public Container<int> { };
class DoubleContainer : public Container<double> { };
class PtrContainer : public Container<void*> { };
```

#### Test Steps:

**3.1 Search for template by base name**
```bash
# Expected: Should find Container or its specializations
# Actual (hypothesis): Returns empty or only specializations
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 30, "method": "tools/call",
    "params": {
      "name": "search_classes",
      "arguments": {"pattern": "Container"}
    }
  }' | jq -r '.result.content[0].text'
```

**3.2 get_class_info for template base name**
```bash
# Expected: Info about template or error
# Actual (hypothesis): data: null
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 31, "method": "tools/call",
    "params": {
      "name": "get_class_info",
      "arguments": {"class_name": "Container"}
    }
  }' | jq '.'
```

**3.3 get_class_info for specialization**
```bash
# Expected: Should work
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 32, "method": "tools/call",
    "params": {
      "name": "get_class_info",
      "arguments": {"class_name": "Container<int>"}
    }
  }' | jq '.'
```

**3.4 Regex pattern for templates**
```bash
# Expected: Match specializations?
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 33, "method": "tools/call",
    "params": {
      "name": "search_classes",
      "arguments": {"pattern": "Container.*"}
    }
  }' | jq -r '.result.content[0].text'
```

**3.5 get_derived_classes for template**
```bash
# Expected: Should find IntContainer, DoubleContainer, PtrContainer
# Actual (hypothesis): Empty or requires per-specialization query
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 34, "method": "tools/call",
    "params": {
      "name": "get_derived_classes",
      "arguments": {"class_name": "Container"}
    }
  }' | jq -r '.result.content[0].text'
```

**3.6 get_derived_classes for specific specialization**
```bash
# Expected: Should find IntContainer
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 35, "method": "tools/call",
    "params": {
      "name": "get_derived_classes",
      "arguments": {"class_name": "Container<int>"}
    }
  }' | jq -r '.result.content[0].text'
```

#### Success Criteria:
- [ ] Reproduce issue: template base name not found
- [ ] Confirm specializations work with exact names
- [ ] Test regex matching behavior with `<>` characters
- [ ] Identify libclang representation: how are templates stored in AST?
- [ ] Check SQLite: are templates and specializations separate rows?

---

### TC4: Template-Based Inheritance

**Observation:** #4 - Inheritance through template parameters not detected
**Tools to test:** `get_derived_classes`, `get_class_info` (base_classes)
**Hypothesis:** libclang reports direct base only, doesn't unwrap template params
**Related:** Issue #85

#### Test File: `template_inheritance.h`
```cpp
// Interface
class IInterface {
public:
    virtual void execute() = 0;
};

// CRTP-like base that inherits from template parameter
template<typename Interface>
class ImplementationBase : public Interface {
public:
    void commonLogic() { }
};

// Concrete class derived from template specialization
class ConcreteImpl : public ImplementationBase<IInterface> {
public:
    void execute() override { }
};

// Another variation
class IAnotherInterface {
public:
    virtual void process() = 0;
};

class AnotherImpl : public ImplementationBase<IAnotherInterface> {
public:
    void process() override { }
};
```

#### Test Steps:

**4.1 get_derived_classes for IInterface**
```bash
# Expected (ideal): ConcreteImpl (through ImplementationBase<IInterface>)
# Actual (hypothesis): Empty - only direct inheritance detected
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 40, "method": "tools/call",
    "params": {
      "name": "get_derived_classes",
      "arguments": {"class_name": "IInterface"}
    }
  }' | jq -r '.result.content[0].text'
```

**4.2 get_class_info for ConcreteImpl**
```bash
# Check what base classes are reported
# Expected: Should show ImplementationBase<IInterface>
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 41, "method": "tools/call",
    "params": {
      "name": "get_class_info",
      "arguments": {"class_name": "ConcreteImpl"}
    }
  }' | jq '.result.content[0].text | fromjson | .data.base_classes'
```

**4.3 get_class_info for ImplementationBase specialization**
```bash
# Check if specialization shows IInterface as base
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 42, "method": "tools/call",
    "params": {
      "name": "get_class_info",
      "arguments": {"class_name": "ImplementationBase<IInterface>"}
    }
  }' | jq '.result.content[0].text | fromjson | .data.base_classes'
```

**4.4 get_derived_classes for ImplementationBase**
```bash
# Try querying template base directly
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 43, "method": "tools/call",
    "params": {
      "name": "get_derived_classes",
      "arguments": {"class_name": "ImplementationBase"}
    }
  }' | jq -r '.result.content[0].text'
```

#### Success Criteria:
- [ ] Reproduce issue: IInterface shows no derived classes
- [ ] Confirm ConcreteImpl reports ImplementationBase<IInterface> as base
- [ ] Determine if specialization reports IInterface as its base
- [ ] Assess complexity: would need recursive template param analysis
- [ ] Document expected vs actual behavior

---

### TC5: Template Argument Qualification

**Observation:** #6 - Template args shown with unqualified names
**Tools to test:** `get_class_info`, `get_derived_classes`, `search_classes`
**Hypothesis:** libclang displayname vs qualified name for template args

#### Test File: `template_args.h`
```cpp
namespace ns1 {
    class FooClass { };
}

namespace ns2 {
    class FooClass { };
}

template<typename T>
class BarClass : public T {
public:
    T value;
};

// Specializations using different FooClass
class Example1 : public BarClass<ns1::FooClass> { };
class Example2 : public BarClass<ns2::FooClass> { };
```

#### Test Steps:

**5.1 get_class_info for Example1**
```bash
# Check how base class BarClass<ns1::FooClass> is represented
# Expected (ideal): BarClass<ns1::FooClass>
# Actual (hypothesis): BarClass<FooClass> - ambiguous!
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 50, "method": "tools/call",
    "params": {
      "name": "get_class_info",
      "arguments": {"class_name": "Example1"}
    }
  }' | jq '.result.content[0].text | fromjson | .data.base_classes'
```

**5.2 get_class_info for Example2**
```bash
# Should show BarClass<ns2::FooClass> but might show BarClass<FooClass>
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 51, "method": "tools/call",
    "params": {
      "name": "get_class_info",
      "arguments": {"class_name": "Example2"}
    }
  }' | jq '.result.content[0].text | fromjson | .data.base_classes'
```

**5.3 get_derived_classes for BarClass specialization**
```bash
# Try with qualified template arg
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 52, "method": "tools/call",
    "params": {
      "name": "get_derived_classes",
      "arguments": {"class_name": "BarClass<ns1::FooClass>"}
    }
  }' | jq -r '.result.content[0].text'
```

**5.4 Try with unqualified template arg**
```bash
# Will this work or be ambiguous?
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 53, "method": "tools/call",
    "params": {
      "name": "get_derived_classes",
      "arguments": {"class_name": "BarClass<FooClass>"}
    }
  }' | jq -r '.result.content[0].text'
```

#### Success Criteria:
- [ ] Reproduce issue: template args lose qualification
- [ ] Identify libclang API: cursor.displayname vs cursor.type.spelling
- [ ] Check if both Example1 and Example2 show same base class name (ambiguous)
- [ ] Determine fix: use qualified type names for template arguments

---

### TC6: Expand Testing to Other Tools

**Purpose:** Check if issues are systemic across similar tools
**Tools to test systematically:**

#### 6.1 Tools accepting class names:
- [ ] `get_class_info` - Test with qualified, template, ambiguous names
- [ ] `get_derived_classes` - Same tests
- [ ] `get_base_classes` - Same tests
- [ ] `search_classes` - Already tested above

#### 6.2 Tools accepting function names:
- [ ] `search_functions` - Test qualified names, template functions
- [ ] `get_function_info` - Test with qualified, overloaded, template functions
- [ ] `find_callers` - Test with qualified function names
- [ ] `find_callees` - Same

#### 6.3 Tools accepting symbol names:
- [ ] `search_symbols` - Already tested above
- [ ] `find_in_file` - Test qualified patterns

#### Test Matrix Template:
```bash
# For each tool, test:
# 1. Qualified name: "ns::Entity"
# 2. Unqualified name: "Entity"
# 3. Regex with namespace: ".*::Entity"
# 4. Template name: "Template<Type>"
# 5. Template base: "Template"
# 6. Ambiguous name (multiple namespaces)
```

---

## Root Cause Investigation

### Investigation 1: Symbol Storage in SQLite

**Check schema:**
```bash
sqlite3 .mcp_cache/<project>/symbols.db
```

```sql
-- Check symbols table schema
.schema symbols

-- Check if qualified_name is stored
SELECT name, qualified_name, namespace, kind
FROM symbols
WHERE name = 'View'
LIMIT 5;

-- Check template representation
SELECT name, qualified_name, kind
FROM symbols
WHERE name LIKE '%Container%';
```

**Questions to answer:**
- Does `symbols` table have `qualified_name` column?
- How are template specializations stored (separate rows)?
- Is template base definition stored?
- Do template argument types include qualification?

### Investigation 2: Pattern Matching Logic

**Code locations to check:**
- `mcp_server/search_engine.py` - Pattern matching implementation
- `mcp_server/cpp_analyzer.py` - Symbol extraction and storage

**Questions to answer:**
- Where does pattern matching happen (SQL LIKE vs Python regex)?
- What field is matched against (`name` vs `qualified_name`)?
- Why doesn't `::` in pattern work?

### Investigation 3: libclang Template Representation

**Create minimal test script:**
```python
import clang.cindex as clx

code = """
template<typename T> class Container { };
class Derived : public Container<int> { };
"""

# Parse and inspect AST
# Check: cursor.spelling, cursor.displayname, cursor.type.spelling
# For base classes: base.type.spelling vs base.type.get_declaration().spelling
```

**Questions to answer:**
- How does libclang represent template definitions vs specializations?
- What names are available (spelling, displayname, type.spelling)?
- Are qualified names available for template arguments?

---

## Documentation Requirements

For each test case, document:

### ✅ Pass Criteria:
- Observation confirmed or refuted
- Root cause identified (code location + explanation)
- Affected tools listed
- SQLite data structure examined

### 📊 Results Format:
```markdown
## TC1: Qualified Names - RESULTS

**Status:** ✅ CONFIRMED / ❌ REFUTED / ⚠️ PARTIAL

**Affected Tools:**
- search_classes: ❌ Qualified names return empty
- search_functions: ❌ Same issue
- get_class_info: ⚠️ Works with unqualified, fails with qualified

**Root Cause:**
File: mcp_server/search_engine.py:45
Behavior: Pattern matched against `symbol_info.name` (unqualified)
SQLite: `symbols.name` column contains unqualified names only

**Evidence:**
- Test 1.1: `search_classes("ns1::View")` → []
- Test 1.2: `search_classes("View")` → [ns1::View, ns2::View, ::View]
- SQLite query: `SELECT name FROM symbols WHERE name='View'` → 3 rows
- SQLite query: `SELECT name FROM symbols WHERE name='ns1::View'` → 0 rows

**Impact:** Confirmed - no namespace filtering possible

**Next Steps:**
- Check if `qualified_name` field exists in schema
- Evaluate fix complexity: add namespace filtering parameter
- Create GitHub issue with evidence
```

---

## Execution Plan

### Phase 1: Environment Setup (15 min)
- [ ] Create `examples/template_test/` directory
- [ ] Write test files: qualified_names.h, templates.h, template_inheritance.h, template_args.h
- [ ] Start SSE server
- [ ] Index test project
- [ ] Verify indexing complete

### Phase 2: Execute Test Cases (2-3 hours)
- [ ] TC1: Qualified Names (30 min)
- [ ] TC2: Namespace Disambiguation (30 min)
- [ ] TC3: Template Class Search (45 min)
- [ ] TC4: Template-Based Inheritance (45 min)
- [ ] TC5: Template Argument Qualification (30 min)
- [ ] TC6: Expand to Other Tools (1 hour)

### Phase 3: Root Cause Analysis (2-3 hours)
- [ ] SQLite schema inspection
- [ ] Code review: search_engine.py, cpp_analyzer.py
- [ ] libclang API investigation
- [ ] Document findings

### Phase 4: Documentation (1 hour)
- [ ] Compile results document
- [ ] Update MANUAL_TESTING_OBSERVATIONS.md with evidence
- [ ] Prepare GitHub issue descriptions with test cases

### Phase 5: GitHub Issues Creation (30 min)
- [ ] Create Issue #1: Qualified Names Support
- [ ] Create Issue #2: Template Class Search
- [ ] Create Issue #3: Namespace Disambiguation
- [ ] Create Issue #4: Template-Based Inheritance
- [ ] Create Issue #5: Template Argument Qualification
- [ ] Link to Issue #85 (Template Information Tracking)

---

## Success Metrics

- [ ] All 5 observations validated or refuted with evidence
- [ ] Root causes identified for each confirmed issue
- [ ] Test cases documented (can be automated later)
- [ ] GitHub issues created with reproduction steps
- [ ] Recommendations for fixes or workarounds

---

## Notes

- Use SSE transport for all tests (easier to script with curl)
- Save all curl commands and responses for evidence
- Check both positive and negative cases
- Consider performance implications (large project testing in Phase 6)
- Link all findings back to original LM Studio observations
