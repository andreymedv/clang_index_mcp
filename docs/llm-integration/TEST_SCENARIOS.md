# Test Scenarios for LLM Integration

This document provides concrete test scenarios to validate the effectiveness of the LLM integration enhancements.

## Test Setup

### Test Projects
1. **Small:** `examples/compile_commands_example` (~100 LOC)
2. **Medium:** nlohmann/json (~20K LOC)
3. **Large:** spdlog (~10K LOC) or similar production library

### MCP Server Configuration

Add to Claude Desktop config:
```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "/path/to/mcp_env/bin/python",
      "args": ["-m", "mcp_server.cpp_mcp_server"],
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/test/project"]
    }
  }
}
```

## Scenario 1: Understanding a Class

### User Request
"Show me the Logger class and explain how it works"

### Expected LLM Workflow

**Without enhancements (current state):**
1. `search_classes("Logger")` → gets file path and line number
2. `read_file("src/logger.cpp")` → reads entire file (500+ lines)
3. LLM manually searches for class definition in content
4. LLM manually determines where class ends
5. No brief description available
6. No quick understanding of purpose

**With enhancements:**
1. `get_class_info("Logger")` → gets:
   - File: `src/logger.cpp`
   - Lines: 45-120 (exact range)
   - Header: `include/logger.h`, lines 15-30
   - Brief: "Provides logging functionality with multiple severity levels"
   - Methods: list with brief descriptions
   - Members: list with types
2. `read_file("include/logger.h", start_line=15, end_line=30)` → reads only class definition
3. LLM immediately understands purpose from brief
4. Can explain without reading full source

### Success Criteria
- ✅ LLM gets class definition in <100 lines instead of 500+
- ✅ LLM understands purpose without reading implementation
- ✅ Context window savings: >80%
- ✅ Response time: <50% of current

### Metrics to Track
- Lines read from filesystem
- Number of file reads
- LLM response time
- Context window tokens used

## Scenario 2: Finding Usage Examples

### User Request
"Show me examples of how to use the HttpClient class"

### Expected LLM Workflow

**Without enhancements (current state):**
1. `search_classes("HttpClient")` → gets file path
2. `grep_project("HttpClient")` → searches ALL files (10,000+)
3. Receives hundreds of matches
4. LLM must filter through results manually
5. Slow and context-intensive

**With enhancements:**
1. `get_class_info("HttpClient")` → gets metadata with brief
2. `get_files_containing_symbol("HttpClient", kind="class")` → gets:
   - `["src/http_client.cpp", "tests/test_http.cpp", "examples/simple_get.cpp"]`
3. `grep_files(pattern="HttpClient.*request", files=[...])` → searches only 3 files
4. Gets precise, relevant examples quickly

### Success Criteria
- ✅ Search reduced from 10,000 files to <10 files
- ✅ 1000x performance improvement
- ✅ All examples relevant (no false positives from unrelated code)
- ✅ Response time: <10s instead of 60s+

### Metrics to Track
- Number of files searched
- Grep execution time
- Number of results returned
- Relevance of results

## Scenario 3: Impact Analysis

### User Request
"If I change the signature of parse(), what code will be affected?"

### Expected LLM Workflow

**Without enhancements (current state):**
1. `find_callers("parse")` → gets caller functions
2. For each caller, read entire file to understand context
3. Manual analysis of impact
4. May miss indirect dependencies

**With enhancements:**
1. `get_function_info("parse")` → gets:
   - Signature: `bool parse(const std::string& input)`
   - Brief: "Parses input string and builds AST"
   - File: `src/parser.cpp`, lines 100-150
2. `find_callers("parse")` → gets list with line ranges
3. `get_files_containing_symbol("parse")` → gets all files that reference it
4. For each file, read only relevant line ranges
5. Comprehensive impact assessment

### Success Criteria
- ✅ All affected code identified
- ✅ Minimal context reading (only relevant sections)
- ✅ Clear understanding of impact
- ✅ Can provide refactoring plan

### Metrics to Track
- Completeness: % of affected code identified
- Precision: % of identified code actually affected
- Context efficiency: lines read vs total lines in files

## Scenario 4: Debugging a Crash

### User Request
"The validate() function crashes. Help me debug it."

### Expected LLM Workflow

**Without enhancements (current state):**
1. `search_functions("validate")` → gets file and line
2. Read entire file
3. `find_callers("validate")` → gets callers
4. Read all caller files
5. No type information for parameters

**With enhancements:**
1. `get_function_info("validate")` → gets:
   - File: `src/validator.cpp`, lines 50-85
   - Signature: `bool validate(const Data* data, ValidationRules rules)`
   - Brief: "Validates data against specified rules"
   - Parameters with types
2. Read only lines 50-85 from validator.cpp
3. `find_callers("validate")` → gets callers with line ranges
4. For each caller, read only relevant section
5. Can analyze parameter passing, null checks, etc.

### Success Criteria
- ✅ Reads only relevant code sections
- ✅ Understands function contract from signature + brief
- ✅ Can identify potential issues (null pointers, invalid params)
- ✅ Efficient debugging workflow

## Scenario 5: Adding a New Method

### User Request
"I need to add a serialize() method to the DataModel class. Where should I add it?"

### Expected LLM Workflow

**Without enhancements (current state):**
1. `search_classes("DataModel")` → gets file
2. Read entire file to find class
3. Manually parse class structure
4. Make recommendation

**With enhancements:**
1. `get_class_info("DataModel")` → gets:
   - Header: `include/data_model.h`, lines 20-60
   - Implementation: `src/data_model.cpp`, lines 10-150
   - Methods: list with types and line ranges
   - Members: list with types
   - Brief: "Represents data model with validation"
2. Read header lines 20-60
3. Identify similar methods (e.g., deserialize)
4. Make informed recommendation with exact line numbers

### Success Criteria
- ✅ Accurate placement recommendation
- ✅ Follows existing patterns
- ✅ Considers related methods
- ✅ Minimal file reading

## Scenario 6: Understanding Dependencies

### User Request
"What headers does parser.cpp depend on?"

### Expected LLM Workflow

**Without enhancements (current state):**
1. Read entire parser.cpp file
2. Manually extract #include directives
3. No information about transitive dependencies
4. May miss important dependencies

**With enhancements:**
1. `get_file_includes("src/parser.cpp")` → gets:
   ```json
   {
     "file": "src/parser.cpp",
     "direct_includes": ["parser.h", "ast.h", "lexer.h", "token.h"],
     "system_includes": ["<vector>", "<string>", "<memory>"],
     "include_paths": ["/usr/include", "include/"]
   }
   ```
2. Optional: `get_file_includes("include/parser.h", transitive=true)` → gets full dependency tree
3. Clear understanding of dependencies

### Success Criteria
- ✅ All direct includes identified
- ✅ System includes separated
- ✅ Include paths provided
- ✅ Optional transitive dependencies

## Scenario 7: Understanding Template Code

### User Request
"Explain how the SmartPointer template works"

### Expected LLM Workflow

**Without enhancements (current state):**
1. `search_classes("SmartPointer")` → gets file
2. Read entire file
3. Manually parse template parameters
4. Guess at member types

**With enhancements:**
1. `get_class_info("SmartPointer")` → gets:
   - Template parameters: `["typename T", "typename Deleter = std::default_delete<T>"]`
   - Members with types: `[{"name": "ptr_", "type": "T*"}, {"name": "deleter_", "type": "Deleter"}]`
   - Methods with full signatures
   - Brief: "RAII smart pointer with custom deleter support"
   - Header: `include/smart_pointer.h`, lines 15-80
2. Read header lines 15-80
3. Full understanding of template design

### Success Criteria
- ✅ Template parameters understood
- ✅ Member types clear (including template types)
- ✅ Design pattern recognized
- ✅ Can explain usage and design

## Scenario 8: Dead Code Detection

### User Request
"Find functions that are never called"

### Expected LLM Workflow

**Without enhancements (current state):**
1. `list_all_functions()` → gets all functions
2. For each function, `find_callers(function)` → check if empty
3. Slow, many queries
4. May miss entry points (main, callbacks, etc.)

**With enhancements:**
1. `list_all_functions()` → gets all functions
2. For each function, `find_callers(function)` → check if empty
3. `get_files_containing_symbol(function)` → verify not used elsewhere
4. Filter out entry points based on naming conventions
5. Comprehensive dead code report

### Success Criteria
- ✅ Identifies truly unused functions
- ✅ Excludes entry points and callbacks
- ✅ Reasonable performance (<30s for medium project)
- ✅ Minimal false positives

## Scenario 9: API Documentation Generation

### User Request
"Generate documentation for the public API of the Logger class"

### Expected LLM Workflow

**Without enhancements (current state):**
1. `get_class_info("Logger")` → gets methods
2. Read entire file
3. Manually extract comments
4. Format as documentation

**With enhancements:**
1. `get_class_info("Logger")` → gets:
   - Methods with signatures, briefs, and doc_comments
   - Members with types and descriptions
   - All documentation already extracted
2. Format and present without reading source files

### Success Criteria
- ✅ Documentation generated without reading source
- ✅ Includes parameter descriptions
- ✅ Includes return value descriptions
- ✅ Professional formatting

## Scenario 10: Cross-Reference Analysis

### User Request
"Show me all places where the deprecated old_api() function is used"

### Expected LLM Workflow

**Without enhancements (current state):**
1. `search_functions("old_api")` → gets definition
2. `find_callers("old_api")` → gets caller functions
3. Grep entire project for usage
4. Read many files to understand context

**With enhancements:**
1. `get_function_info("old_api")` → gets metadata
2. `get_files_containing_symbol("old_api")` → gets 5 files
3. `find_callers("old_api")` → gets specific call sites with line ranges
4. Read only relevant sections from 5 files
5. Can generate refactoring plan

### Success Criteria
- ✅ All usage sites identified
- ✅ Minimal file reading (only relevant sections)
- ✅ Context preserved for each usage
- ✅ Can recommend replacements

## Performance Benchmarks

### Indexing Performance (One-Time Cost)

**Target metrics after enhancements:**
- Small project (100 LOC): <1s (baseline: <1s)
- Medium project (20K LOC): <30s (baseline: ~20s)
- Large project (100K LOC): <5min (baseline: ~3min)

**Acceptable overhead:** +30-50% due to documentation extraction and include tracking

### Query Performance (Frequent Operations)

**Target metrics:**
| Operation | Current | Target | Improvement |
|-----------|---------|--------|-------------|
| get_class_info | ~5ms | ~10ms | +5ms acceptable |
| get_files_containing_symbol | N/A | <50ms | New tool |
| search_classes | ~10ms | ~15ms | +5ms acceptable |
| Combined workflow | ~60s | ~10s | 6x faster |

### Context Efficiency

**Target metrics:**
| Scenario | Current Lines Read | Target Lines Read | Improvement |
|----------|-------------------|-------------------|-------------|
| Understand class | 500+ | <100 | 5x reduction |
| Find usage | 10,000+ | <500 | 20x reduction |
| Impact analysis | 5,000+ | <300 | 16x reduction |
| Debugging | 2,000+ | <200 | 10x reduction |

## Test Execution Plan

### Phase 1: Baseline Measurement
1. Configure MCP server (current version) with test project
2. Run all 10 scenarios
3. Measure: lines read, queries made, time taken, context tokens
4. Document pain points and inefficiencies

### Phase 2: Implementation
1. Implement Phase 1 enhancements (line ranges + file lists)
2. Run automated tests to ensure correctness
3. Performance tests to measure overhead

### Phase 3: Effectiveness Testing
1. Configure MCP server (enhanced version) with same test project
2. Run same 10 scenarios
3. Measure same metrics
4. Compare results

### Phase 4: Analysis
1. Calculate improvements
2. Identify remaining gaps
3. Prioritize next phase

### Phase 5: Iteration
1. Implement Phase 2 enhancements (documentation)
2. Repeat testing
3. Continue iterating

## Success Criteria Summary

**Quantitative targets:**
- File reading reduction: >80%
- Search scope reduction: >95% (from all files to <5%)
- Query time reduction: >70%
- Context window efficiency: >80% improvement

**Qualitative targets:**
- LLM can answer "explain class" without reading source: ✅
- LLM can find usage examples in <10s: ✅
- LLM can perform impact analysis accurately: ✅
- LLM can assist with debugging efficiently: ✅
- LLM can recommend code changes with confidence: ✅

## Regression Testing

After each enhancement, verify:
- [ ] All existing tools still work
- [ ] Performance hasn't degraded for existing queries
- [ ] Cache compatibility maintained
- [ ] Error handling robust
- [ ] Documentation updated

## Future Test Scenarios (Advanced)

Once basic integration works well:

### Scenario 11: Refactoring Assistance
"Help me extract this 100-line function into smaller functions"

### Scenario 12: Design Pattern Recognition
"What design patterns are used in this codebase?"

### Scenario 13: Architectural Analysis
"Map out the dependency structure of the networking module"

### Scenario 14: Code Quality Assessment
"Find functions with high complexity that need refactoring"

### Scenario 15: Security Analysis
"Find all places where user input is used without validation"

These scenarios may require additional tools beyond the current scope, but the bridging data we're adding will enable them.
