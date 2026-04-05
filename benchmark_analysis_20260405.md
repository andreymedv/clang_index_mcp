# Benchmark Results Analysis: Tool Description Optimization

**Date:** 2026-04-05  
**Benchmark:** bench_20260405_110953  
**Total Scenarios:** 77 per model  
**Total Time:** 209.5 minutes

## Summary

| Model | Pass | Total | Rate |
|-------|------|-------|------|
| qwen/qwen3-4b-thinking-2507 | 77 | 77 | 100.0% * |
| qwen3-30b-a3b-thinking-2507 | 77 | 77 | 100.0% * |
| qwen3-next-80b-a3b-instruct | 77 | 77 | 100.0% * |
| qwen3.5-9b-opus-4.6-functiongemma.gguf | 73 | 77 | 94.8% |
| zai-org/glm-4.7-flash | 72 | 77 | 93.5% |
| qwen3.5-9b | 71 | 77 | 92.2% |
| qwen3.5-27b-claude-4.6-opus-reasoning-distilled-i1 | 71 | 77 | 92.2% |
| qwen/qwen3-4b-2507 | 70 | 77 | 90.9% |
| qwen3-coder-30b-a3b-instruct | 67 | 77 | 87.0% |

*Models with 100% pass rate achieved perfect tool selection across all test scenarios.

---

## Root Cause Analysis: Recurring Failure Patterns

Based on LLM explanations from failing scenarios, I identified **6 major root causes** affecting tool selection across models:

### Root Cause 1: Direction Confusion (OUTGOING vs INCOMING calls)

**Affected Models:** qwen3-4b, qwen3.5-9b, qwen3-coder-30b, glm-4.7-flash, qwen3.5-27b-claude

**Failure Pattern:** Models confuse `find_outgoing_calls` with `find_incoming_calls` despite the clear directional hints in descriptions.

**Example Failures:**
- Query: `"What functions are called BY processEvent?"` → Uses `find_incoming_calls` (wrong)
- Query: `"Show me what processEvent invokes"` → Uses `find_symbols_by_pattern` instead of `find_outgoing_calls`
- Query: `"Find all code that depends on the processEvent function"` → Expected `find_incoming_calls`, got `find_symbols_by_pattern`

**LLM Explanation Quote:**
> "find_incoming_calls finds all functions that call the given function"

This explanation came from qwen3-4b after incorrectly choosing `find_incoming_calls` for an outgoing query. The model understood the description but failed to map "called BY" to outgoing direction.

**Analysis:**
The current descriptions have clear directionality hints:
- `find_outgoing_calls`: "Find functions called by this function (outbound direction): X -> called functions"
- `find_incoming_calls`: "Find all functions that call the specified function (inbound direction): callers -> X"

However, models still struggle because:
1. The phrases "called BY" in user queries create cognitive overload - models interpret "BY" as "incoming"
2. Natural language is ambiguous - "what does X call" vs "what calls X" requires careful parsing
3. Models default to searching first (`find_symbols_by_pattern`) when uncertain

**Suggested Improvement:**

```python
# Current description for find_outgoing_calls:
"Find functions called by this function (outbound direction): X -> called functions."
"- Do NOT use for 'who calls X?' or 'where is X used?' — use find_incoming_calls instead."

# Improved description:
"OUTBOUND call graph traversal: find functions that X calls (X → callees).\n\n"
"Use when user asks what X calls, invokes, depends on, or 'calls internally'.\n"
"Do NOT use when user asks who calls X, what calls X, or 'where is X used' — "
"those require find_incoming_calls (inbound direction).\n\n"
"Direction quick reference:\n"
"- X calls Y → find_outgoing_calls (this tool)\n"
"- Y calls X → find_incoming_calls (other tool)"
```

---

### Root Cause 2: Over-reliance on `find_symbols_by_pattern` as First Step

**Affected Models:** qwen3-coder-30b, qwen3.5-27b-claude, glm-4.7-flash, qwen3.5-9b

**Failure Pattern:** When a function or class name is explicitly provided in the query, models still use `find_symbols_by_pattern` first instead of directly calling specialized tools.

**Example Failures:**
- Query: `"What functions are called by processData? Show me its dependencies."` → Uses `find_symbols_by_pattern` first (expected: direct `find_outgoing_calls`)
- Query: `"Show me all subclasses and parent classes of Widget"` → Uses `find_symbols_by_pattern` first (expected: direct `get_class_hierarchy`)
- Query: `"Find all implementations of the IProcessor interface"` → Uses `find_symbols_by_pattern` first (expected: direct `get_class_hierarchy`)

**LLM Explanation Quote:**
> "I used find_symbols_by_pattern because I needed to locate the IProcessor interface definition first, then find all implementations. The pattern search allows me to discover the interface and subsequently..."

**Analysis:**
Models are being overly cautious and following a "search first, then specialize" pattern even when:
1. The symbol name is already explicitly provided
2. The specialized tool can handle the name directly
3. The descriptions say "Do not search first when the function name is already known"

The `find_symbols_by_pattern` tool description already contains:
> "Use symbol_name for C++ symbol names only; use file_name for file or directory prefixes"
> "Do not encode file paths or namespaces in the symbol_name when a dedicated filter exists"

But this guidance isn't strong enough to override the "search first" habit.

**Suggested Improvement:**

Add explicit guidance to specialized tools' descriptions:

```python
# For get_class_hierarchy:
"Get complete inheritance graph for a named class or structure.\n\n"
"IMPORTANT: Call directly when you know the class name; do NOT call find_symbols_by_pattern first.\n"
"This tool accepts simple names ('Widget') and qualified names ('UI::Widget') directly.\n\n"
"Examples:\n"
"- 'full hierarchy of X' → get_class_hierarchy('X') — call directly\n"
"- 'all implementations of Y' → get_class_hierarchy('Y') — call directly"

# For find_outgoing_calls / find_incoming_calls:
"IMPORTANT: When the function name is known from the user's query, call this tool directly.\n"
"Do NOT use find_symbols_by_pattern first to 'verify' the function exists.\n"
"If the function doesn't exist, this tool will report it clearly."
```

---

### Root Cause 3: `target_type` Parameter Confusion

**Affected Models:** qwen3-4b, qwen3-coder-30b

**Failure Pattern:** Models omit `target_type` parameter when it should be explicitly set, or they misunderstand when to include it.

**Example Failures:**
- Query: `"List all functions in files that start with Util_"` → Omits `target_type=functions_and_methods_only`
- Query: `"Search for functions with 'Merge' in their name within TBL_ files"` → Omits `target_type`

**LLM Explanation Quotes:**
> "The parameter target_type was omitted because the query specifically asks for 'functions' and the pattern Util_ is a file name pattern, not a symbol name pattern."

> "Looking at the tool call, I omitted target_type because the request specifically asked for 'functions' with 'Merge' in their name. The pattern .*Merge.* is designed to match function names..."

**Analysis:**
Models are misinterpreting the relationship between:
1. Natural language intent ("find all functions")
2. The `symbol_name` pattern field
3. The `target_type` filter parameter

They believe that if the natural language query specifies "functions," the tool should automatically infer this. But `find_symbols_by_pattern` defaults to `all_symbol_types`.

**Current `target_type` description:**
```python
"What to search for. 'classes_and_structs_only': class/struct definitions. "
"'functions_and_methods_only': functions and class methods. 'all_symbol_types': both."
```

**Suggested Improvement:**

Clarify the default behavior and when explicit filtering is necessary:

```python
"target_type": {
    "description": (
        "REQUIRED when searching for ONLY classes OR ONLY functions. "
        "Default is 'all_symbol_types' which returns both classes and functions.\n\n"
        "Use 'classes_and_structs_only' when the user explicitly asks for classes/structs.\n"
        "Use 'functions_and_methods_only' when the user explicitly asks for functions/methods.\n\n"
        "Examples:\n"
        "- 'Find classes...' → target_type='classes_and_structs_only'\n"
        "- 'List functions...' → target_type='functions_and_methods_only'"
    ),
    "default": "all_symbol_types",
}
```

---

### Root Cause 4: `find_in_file` vs `find_symbols_by_pattern` Confusion

**Affected Models:** qwen3.5-9b

**Failure Pattern:** Models use `find_symbols_by_pattern` with a `file_name` filter when the user asks for symbols in a specific file by exact name.

**Example Failure:**
- Query: `"What symbols are defined in DOM_Document.h?"` → Some models don't use `find_in_file`

**Analysis:**
The distinction between these tools is:
- `find_in_file`: List ALL symbols in ONE specific file you already know by exact name
- `find_symbols_by_pattern` with `file_name`: Search for symbols matching a pattern, filtered by file path substring

Models sometimes conflate these because both can work with file paths.

**Suggested Improvement:**

Clarify the distinction in both descriptions:

```python
# For find_in_file:
"List all symbols defined in ONE specific file you already know by exact name.\n\n"
"Use this when the user names ONE concrete file and asks what symbols are in it.\n"
"Examples: 'What is defined in Foo.h?', 'List symbols in src/main.cpp'\n\n"
"Do NOT use this for searching across multiple files or file patterns — "
"use find_symbols_by_pattern with file_name filter instead."

# For find_symbols_by_pattern (add to existing description):
"\n\nEnumeration via filters (use empty symbol_name=''):\n"
"- symbol_name='' + file_name='Helper' → all symbols in files with 'Helper' in path\n"
"- Use this pattern when the user asks for 'all classes in files starting with X'\n"
"- NOT for 'what is in File.h' (that's find_in_file)"
```

---

### Root Cause 5: Multi-step Scenario Completion Issues

**Affected Models:** qwen3.5-9b, qwen3-coder-30b, glm-4.7-flash

**Failure Pattern:** In multi-step scenarios, models sometimes:
1. Only complete the first step and stop
2. Choose wrong tools for subsequent steps
3. Use wrong function names in subsequent steps

**Example Failures:**
- Query: `"How is ApplyStyle used with DOM elements? Find the function first, then show me its callers"`
  - Expected: `find_symbols_by_pattern` (optional) → `find_incoming_calls`
  - Some models use `get_class_info` for the second step (wrong tool)

- Query: `"Show me the INodeVisitor interface details, then its full implementation tree"`
  - Expected: `get_class_info` → `get_class_hierarchy`
  - Some models use `find_symbols_by_pattern` for first step (unnecessary)

**Analysis:**
Models struggle with:
1. Understanding that "find X first, then Y" means X is optional if X is already known
2. Carrying context from one step to the next (remembering which function/class to query)
3. Selecting the right tool when multiple steps involve similar but different operations

**Suggested Improvement:**

This is more of a prompt engineering issue than a description issue. The current descriptions are clear about individual tool usage. However, we could add hints about multi-step workflows:

```python
# For tools commonly used in sequence:
"Note: If the user asks to 'find X first, then do Y', and you already know X from context, "
"you can call this tool directly without the preliminary search step."
```

---

### Root Cause 6: Model-Specific Function Calling Issues

**Affected Model:** qwen3.5-9b-opus-4.6-functiongemma.gguf

**Failure Pattern:** This model has unique issues:
1. Sometimes produces malformed tool calls with garbled parameter encoding
2. Occasionally fails to call any tool at all

**Example Failures:**
- Query: `"Search for classes with 'Widget' in the name"` → Tool name is garbled with parameters appended
- Query: `"Search for classes with 'NonExistentSymbol12345' in the name"` → No tool call made

**Analysis:**
This appears to be a model-specific function calling format issue, likely related to how the GGUF model was quantized or the function calling adapter used.

**Suggested Action:**
Not a description issue — this requires either:
1. Model retraining/quantization with better function calling support
2. Adjusting the function calling prompt format for this specific model
3. Excluding this model from benchmarks until function calling is fixed

---

## Specific Tool Description Improvement Recommendations

### 1. `find_outgoing_calls` - Add directionality clarifications

```python
description=(
    "OUTBOUND call graph: find functions that the specified function calls (X → callees).\n\n"
    "Use for: what X calls, what X invokes, X's dependencies, outgoing calls from X, "
    "functions called BY X (note: BY X means X is the caller).\n\n"
    "Do NOT use for: who calls X, what calls X, callers of X, where is X used — "
    "those are INBOUND queries; use find_incoming_calls instead.\n\n"
    "Direction quick reference:\n"
    "- X calls Y → find_outgoing_calls (this tool, X is the subject)\n"
    "- Y calls X → find_incoming_calls (other tool, X is the subject)\n\n"
    "Call directly when function name is known; do not search first."
)
```

### 2. `find_incoming_calls` - Add directionality clarifications

```python
description=(
    "INBOUND call graph: find all functions that call the specified function (callers → X).\n\n"
    "Use for: who calls X, what calls X, callers of X, where is X used/invoked, "
    "functions that depend on X.\n\n"
    "Do NOT use for: what X calls, what X invokes, X's dependencies — "
    "those are OUTBOUND queries; use find_outgoing_calls instead.\n\n"
    "Direction quick reference:\n"
    "- Y calls X → find_incoming_calls (this tool, X is the subject)\n"
    "- X calls Y → find_outgoing_calls (other tool, X is the subject)\n\n"
    "Call directly when function name is known; do not search first."
)
```

### 3. `get_class_hierarchy` - Emphasize direct calling

```python
description=(
    "Get complete inheritance graph for a named class or structure — all ancestors "
    "and descendants as a flat adjacency list.\n\n"
    "IMPORTANT: Call directly when you know the class name; do NOT call find_symbols_by_pattern first. "
    "This tool accepts simple names ('Widget') and qualified names ('UI::Widget') directly.\n\n"
    "Use for: full inheritance trees, interface implementations, subclass discovery, "
    "'all implementations of Y', 'classes derived from Z'.\n\n"
    "Examples:\n"
    "- 'full hierarchy of X' → get_class_hierarchy('X') — call directly\n"
    "- 'all implementations of IProcessor' → get_class_hierarchy('IProcessor') — call directly\n"
    "- 'find all derived classes of Widget' → get_class_hierarchy('Widget') — call directly"
)
```

### 4. `get_class_info` - Emphasize direct calling

```python
description=(
    "Get full details of a specific class: methods, base classes, "
    "derived classes, and documentation.\n\n"
    "IMPORTANT: Call directly when class name is known from the query; "
    "do NOT call find_symbols_by_pattern first to 'verify' the class exists. "
    "Handles simple or qualified names and reports ambiguities when a name matches multiple classes.\n\n"
    "If you need the full inheritance tree, subclasses, or implementations, "
    "use get_class_hierarchy instead."
)
```

### 5. `find_symbols_by_pattern` - Clarify relationship with specialized tools

```python
description=(
    "Discover C++ classes, functions, and methods by name pattern; "
    "optional filters narrow results by symbol kind, namespace, and file path.\n\n"
    "Use this tool when you need to DISCOVER symbols by pattern or enumerate "
    "symbols matching certain criteria.\n\n"
    "Do NOT use this tool when:\n"
    "- You already know the exact class name and need its hierarchy → use get_class_hierarchy\n"
    "- You already know the exact class name and need its details → use get_class_info\n"
    "- You already know the exact function name and need its callers → use find_incoming_calls\n"
    "- You already know the exact function name and need its callees → use find_outgoing_calls\n"
    "- You know the exact file name and want ALL symbols in it → use find_in_file\n\n"
    "Pattern matching (case-insensitive):\n"
    "- 'DataRecord' — matches in any namespace\n"
    "- 'storage::DataRecord' — matches namespace suffix\n"
    "- '.*Manager.*' — regex, matches containing 'Manager'\n"
    "- '' (empty) — matches ALL symbols; combine with file_name or namespace for enumeration\n\n"
    "Use symbol_name for C++ symbol names only; use file_name for file or directory prefixes; "
    "use namespace for namespace-scoped searches. "
    "Do not encode file paths or namespaces in the symbol_name when a dedicated filter exists."
)
```

### 6. `find_symbols_by_pattern.target_type` - Clarify when to use

```python
"target_type": {
    "type": "string",
    "enum": [
        "classes_and_structs_only",
        "functions_and_methods_only",
        "all_symbol_types",
    ],
    "description": (
        "What symbol kinds to return. Default 'all_symbol_types' returns both classes and functions. "
        "IMPORTANT: When the user explicitly asks for ONLY classes OR ONLY functions, "
        "you MUST set this parameter accordingly.\n\n"
        "- 'classes_and_structs_only': class/struct definitions only\n"
        "- 'functions_and_methods_only': functions and class methods only\n"
        "- 'all_symbol_types': both classes and functions (default)\n\n"
        "Examples:\n"
        "- 'Find all classes with Widget in the name' → target_type='classes_and_structs_only'\n"
        "- 'List functions in files starting with Util_' → target_type='functions_and_methods_only'"
    ),
    "default": "all_symbol_types",
}
```

---

## Impact Assessment

### High Impact (affects multiple models, frequent failures)

1. **Root Cause 1 (Direction Confusion):** Affects 5/6 non-perfect models
   - Estimated 2-4 failures per model could be fixed

2. **Root Cause 2 (find_symbols_by_pattern overuse):** Affects 4/6 non-perfect models
   - Estimated 3-6 failures per model could be fixed

3. **Root Cause 3 (target_type confusion):** Affects 2/6 non-perfect models
   - Estimated 1-3 failures per model could be fixed

### Medium Impact (affects fewer models)

4. **Root Cause 4 (find_in_file confusion):** Affects 1/6 non-perfect models
5. **Root Cause 5 (Multi-step issues):** Affects 3/6 non-perfect models

### Low Impact (model-specific)

6. **Root Cause 6 (GGUF model issues):** Affects 1 model, requires non-description fixes

---

## Conclusion

The benchmark reveals that **directional clarity** is the most critical factor for tool selection accuracy. Models struggle with:

1. **Direction confusion:** The words "called BY" create ambiguity. Models need clearer directional guidance with explicit examples.

2. **Over-caution:** Models prefer searching first (`find_symbols_by_pattern`) even when specialized tools can accept names directly. The descriptions need stronger "call directly" guidance.

3. **Parameter inference:** Models don't always map natural language ("find all functions") to explicit parameters (`target_type`). Defaults should be more conservative, or descriptions should emphasize explicit filtering.

### Recommended Next Steps

1. **Implement directionality improvements** for `find_outgoing_calls` and `find_incoming_calls` (high impact)
2. **Add "call directly" guidance** to specialized tools: `get_class_info`, `get_class_hierarchy`, `find_outgoing_calls`, `find_incoming_calls` (high impact)
3. **Clarify `target_type` usage** in `find_symbols_by_pattern` (medium impact)
4. **Re-run benchmark** with updated descriptions to measure improvement
5. **Consider probe scenario refinement** for root causes that persist after description updates

### Potential Pass Rate Improvements

Based on the analysis, implementing the suggested improvements could potentially increase pass rates by:
- qwen3-coder-30b: 87.0% → ~93-95% (+6-8 failures fixed)
- qwen/qwen3-4b-2507: 90.9% → ~95-97% (+4-5 failures fixed)
- qwen3.5-9b: 92.2% → ~96-98% (+3-4 failures fixed)
- glm-4.7-flash: 93.5% → ~96-98% (+2-3 failures fixed)
- qwen3.5-27b-claude: 92.2% → ~96-98% (+3-4 failures fixed)

The 100% models demonstrate that perfect tool selection is achievable with the current tool set, suggesting that description improvements should focus on helping weaker models match the performance of stronger ones.
