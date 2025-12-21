# Manual Testing Observations - LM Studio Integration

## Test Session 1 - Linux (2025-12-18)
**Platform:** Linux (6.14.0-37-generic)
**Test Environment:** LM Studio with SSE transport
**MCP Server Version:** After PR #60 merge (canonical MCP paths)
**Issues Found:** #1, #2, #3

## Test Session 2 - macOS (2025-12-19)
**Platform:** macOS
**Test Environment:** LM Studio with SSE transport, Qwen3-4B model
**MCP Server Version:** docs/lm-studio-compatibility branch
**Issues Found:** #4, #5, #6, #7, #8, #9

## Issue: Race Condition in set_project_directory Status

**Platform:** Linux (observed during initial LM Studio testing)

### Observation

When calling `set_project_directory` followed immediately by `get_indexing_status`, the second call reports that the project directory is not set, even though the first call succeeded.

### Reproduction Steps

1. Call `set_project_directory` with path `/path/to/your/cpp/project`
   - **Result:** Success message returned:
     ```
     Set project directory to: /path/to/your/cpp/project
     Indexing started in background. Auto-refresh enabled.
     Use 'get_indexing_status' to check progress.
     Tools are available but will return partial results until indexing completes.
     ```

2. Immediately call `get_indexing_status`
   - **Result:** Error message:
     ```
     Error: Project directory not set. Please use 'set_project_directory' first
     with the path to your C++ project.
     ```

3. Wait a few seconds and call `get_indexing_status` again
   - **Result:** Success with status:
     ```json
     {
       "state": "indexed",
       "is_fully_indexed": true,
       "is_ready_for_queries": true,
       "progress": null
     }
     ```

### Analysis

**Symptom:** Setting project directory does not change MCP server state immediately, but only after some amount of background work has been completed.

**Impact:** This behavior is inappropriate because:
- The `set_project_directory` response indicates success
- Immediate status queries contradict this success message
- Creates confusion for users/LLMs about whether the operation succeeded
- Race condition between setting state and background indexing initialization

### Investigation Status

⏸️ **PENDING** - Awaiting user request to begin analysis

### Next Steps (When Approved)

1. Look for possible solutions in the codebase
2. Discuss solution options
3. Make implementation choice
4. Implement the fix

---

## Issue: refresh_project Times Out (Synchronous Implementation)

**Platform:** Linux (observed during initial LM Studio testing)

### Observation

When calling `refresh_project`, the tool call times out with MCP error -32001. While the LLM is waiting for response, the server appears to be analyzing source files synchronously.

### Reproduction Steps

1. Server reports no files processed (or empty results)
2. LLM calls `refresh_project` with `incremental: true`
   - **Result:** Timeout error:
     ```
     Tool call failed for refresh_project()
     Arguments: incremental: true
     Errors: MCP error -32001: Request timed out
     ```

3. Observe server logs during the timeout period
   - **Observation:** Server is actively analyzing/indexing source files

### Analysis

**Symptom:** `refresh_project` tool is implemented as a synchronous call that waits until refresh finishes before returning.

**Impact:** This behavior is inappropriate because:
- Tool calls timeout before large project refresh completes
- Blocks the LLM from receiving a response or doing other work
- Server is doing work but client times out waiting
- Similar to `set_project_directory`, refresh should be asynchronous

**Expected Behavior:**
- `refresh_project` should start the refresh in background
- Return immediately with a success message
- Client can poll `get_indexing_status` to check progress
- Similar pattern to how `set_project_directory` claims to work

### Investigation Status

⏸️ **PENDING** - Awaiting user request to begin analysis

### Next Steps (When Approved)

1. Examine `refresh_project` implementation in the codebase
2. Compare with `set_project_directory` implementation
3. Discuss solution options (background task, async return)
4. Make implementation choice
5. Implement the fix

---

## Issue: File Descriptor Leak - "Too many open files"

**Platform:** Linux (does NOT occur on macOS)

### Observation

After indexing some amount of source files, the server starts repeatedly displaying "Too many open files" errors and fails to process subsequent files.

### Reproduction Steps

1. Start indexing a large project (e.g., ProjectName with ~5700+ files)
2. After processing some files, repeated errors appear:
   ```
   Failed to log parse error: [Errno 24] Too many open files:
   '/path/to/cplusplus_mcp/.mcp_cache/ProjectName_311d55a2494feeda/parse_errors.jsonl'
   ```

3. Parse errors for various files:
   ```
   [ERROR] Failed to parse /path/to/project/dir/subdir/File1.h
   [ERROR]   Error: TranslationUnitLoadError: Error parsing translation unit.
   [WARNING] Failed to re-analyze: /path/to/project/dir/SomeFile.h
   ```

4. Pattern repeats for multiple files

### Analysis

**Symptom:** `[Errno 24] Too many open files` - system limit on open file descriptors exhausted.

**Impact:** This is a critical issue because:
- Prevents indexing from completing on large projects
- File descriptor leak accumulates during processing
- Parse errors cascade as no more files can be opened
- Even logging parse errors fails due to the leak
- Server becomes unable to process files correctly

**Suspected Root Cause:**
- File handles not being closed properly after processing
- Possible locations:
  - libclang TranslationUnit not being disposed
  - Cache files (parse_errors.jsonl) not closed
  - SQLite connections not closed
  - Log file handles accumulating
- Leak occurs during parallel file processing

**Error Context:**
- Using fallback compilation args (compile_commands.json not found)
- Processing with `-std=c++17` flag
- Error occurs in multi-process indexing mode

**Platform-Specific Behavior:**
- ❌ **Linux:** Issue reproduces consistently on Linux host
- ✅ **macOS:** Issue does NOT occur on Mac with same codebase
- **Possible explanations:**
  - Different file descriptor limits between platforms (macOS typically allows more open files)
  - Linux system `ulimit -n` may be lower (check with `ulimit -n`)
  - Potential package/library differences between Linux and macOS versions
  - Possible bug in Linux-specific dependencies

### Investigation Status

⏸️ **PENDING** - Awaiting user request to begin analysis

### Next Steps (When Approved)

1. Check system file descriptor limits on Linux: `ulimit -n`
2. Compare with macOS limits to confirm platform difference
3. Monitor file descriptor usage during indexing: `lsof -p <pid> | wc -l`
4. Identify all file/resource opening points in codebase
5. Check for missing close/dispose calls
6. Review context managers and cleanup handlers
7. Check libclang TranslationUnit lifecycle
8. Review SQLite connection pooling
9. Review log file handling
10. Test with file descriptor monitoring tools
11. Consider temporary workaround: increase ulimit if appropriate
12. Implement proper resource cleanup (permanent fix)
13. Add resource leak detection in tests

---

## Issue: Class Search Uses Substring Matching by Default

**Platform:** macOS (observed during LM Studio testing)

### Observation

When the LLM invokes tools to find a class with a given name (e.g., `search_classes`), the MCP server uses the provided name as a substring pattern, returning all entities that contain the requested class name as a substring.

### Impact

**Problem:** Substring matching by default can result in huge result lists that are not useful:
- Searching for class "Item" returns: "Item", "ItemList", "ItemManager", "MenuItemWidget", etc.
- Searching for class "View" returns: "View", "ViewManager", "ListView", "TreeView", "ReviewPanel", etc.
- Large projects may have dozens or hundreds of matches for common substring patterns

**User Expectation:** When searching for a specific class name, users typically expect:
1. Exact match by default (find "Item" → returns only "Item")
2. Substring/pattern matching only when explicitly using wildcards (find "*Item*" → returns all containing "Item")

### Current Behavior

```
search_classes(name="View")
→ Returns: View, ViewManager, ListView, TreeView, ReviewPanel, PreviewWidget, ...
```

### Desired Behavior

```
search_classes(name="View")
→ Returns: View (exact match only)

search_classes(name="*View*")
→ Returns: View, ViewManager, ListView, TreeView, ReviewPanel, PreviewWidget, ...
```

### Recommendation

Modify search tool behavior:
- Use exact name matching by default when no wildcards present
- Enable substring/pattern matching only when wildcards (`*`, `?`) are explicitly specified in the search pattern
- This aligns with user expectations and reduces noise in results

### Investigation Status

⏸️ **PENDING** - Awaiting user request to begin analysis

### Next Steps (When Approved)

1. Review current search implementation in `search_engine.py`
2. Identify where substring matching is applied
3. Implement wildcard detection logic
4. Modify search to use exact match when no wildcards present
5. Update tool documentation to reflect new behavior
6. Add tests for exact match vs pattern matching

---

## Issue: Tool Description May Encourage Incorrect Filename-to-Classname Assumptions

**Platform:** macOS (observed during LM Studio testing with Qwen3-4B)

### Observation

A small LLM model (Qwen3-4B) invoked `search_classes` with `name='SomeName'` and `file='File0.h'` in response to the user question: "what classes are defined in File0.h?". The model appears to be assuming that:
- The file name is related to the class name
- It should search for class "SomeName" within file "File0.h"

**Correct approach should be:**
- `search_classes(pattern='.*', file_name='File0.h')` - list ALL classes in that file
- OR `find_in_file(file_path='File0.h', pattern='.*')` - list ALL symbols in that file

### Root Cause Analysis

Examined tool descriptions in `cpp_mcp_server.py` and found subtle issues:

**1. Example filename suggests name correlation:**
```python
"file_name": {
    "description": "... (e.g., 'MyClass.h', 'utils.cpp') ..."
}
```
The example `'MyClass.h'` subtly implies that header files are typically named after the classes they contain. Small models may infer: `File0.h` → contains class `SomeName` or `PFX_SomeName`.

**2. Missing "list all" guidance:**
Neither `search_classes` nor `find_in_file` explicitly explains how to list ALL symbols in a file:
- No mention that `pattern='.*'` can be used to match everything
- No example showing "list all classes in specific file" use case

**3. No explicit disclaimer:**
The descriptions don't state that C++ file names and class names are NOT necessarily related (unlike some languages like Java where they must match).

### Impact

**Problem:** Small/weak LLM models may make incorrect assumptions:
- Assume file `Foo.h` contains class `Foo`
- Search for wrong class name instead of listing all classes
- Miss the actual classes defined in the file
- User gets incomplete or wrong results

**Affected Models:** More likely to affect smaller models (e.g., Qwen3-4B) that rely heavily on examples and subtle cues in descriptions.

### Current Tool Description Issues

**search_classes tool - file_name parameter (line 211-214):**
```python
"file_name": {
    "type": "string",
    "description": "Optional: Filter results to only symbols defined in files matching this name. Works with any file type (.h, .cpp, .cc, etc.). Accepts multiple formats: absolute path, relative to project root, or filename only (e.g., 'MyClass.h', 'utils.cpp'). Uses 'endswith' matching, so partial paths work if they uniquely identify the file.",
},
```

**search_functions tool - file_name parameter (line 238-241):**
```python
"file_name": {
    "type": "string",
    "description": "Optional: Filter results to only symbols defined in files matching this name. Works with any file type (.h, .cpp, .cc, etc.). Accepts multiple formats: absolute path, relative to project root, or filename only (e.g., 'MyClass.h', 'utils.cpp'). Uses 'endswith' matching, so partial paths work if they uniquely identify the file.",
},
```

### Recommendation

**1. Use neutral filename examples:**
- ❌ AVOID: `'MyClass.h'` (implies class name correlation)
- ✅ USE: `'network.h'`, `'handlers.cpp'`, `'utils.h'` (generic, no implied correlation)

**2. Add "list all" guidance to pattern parameters:**
```python
"pattern": {
    "type": "string",
    "description": "Class/struct name pattern to search for. Supports regular expressions (e.g., 'My.*Class' matches MyBaseClass, MyDerivedClass, etc.). **To list ALL classes**, use '.*' pattern. Combine with file_name parameter to list all classes in a specific file.",
},
```

**3. Add explicit disclaimer about C++ naming conventions:**
Add note to file_name parameter:
```
Note: In C++, file names do not necessarily match class names (unlike Java). A single file may contain multiple classes, and class names may differ from the file name.
```

**4. Provide clear "list all in file" examples in tool descriptions:**
Main description should include example:
```
Example: To list all classes in a specific file, use pattern='.*' with file_name='yourfile.h'
```

### Investigation Status

⏸️ **PENDING** - Awaiting user request to begin analysis

### Next Steps (When Approved)

1. Update `search_classes` tool description:
   - Change file_name examples from `'MyClass.h'` to neutral examples
   - Add "list all" guidance to pattern parameter
   - Add C++ naming convention disclaimer
   - Add example for "list all classes in file" use case

2. Update `search_functions` tool description:
   - Apply same changes as search_classes

3. Update `find_in_file` tool description:
   - Add explicit "list all" guidance

4. Test with small models (if possible):
   - Verify improved descriptions reduce incorrect assumptions
   - Check if models now use `pattern='.*'` for "list all" queries

5. Update tool documentation/examples

---

## Issue: Incremental Re-Analysis Uses Fewer Subprocesses Than Initial Indexing

**Platform:** macOS (observed during LM Studio testing)

### Observation

When re-analyzing changed files (incremental refresh), the system appears to use fewer subprocesses/threads compared to the initial full indexing. This results in slower performance for incremental updates than necessary.

### Evidence

**Initial indexing:**
- Uses full ProcessPoolExecutor with multiple worker processes
- Parallel processing provides 6-7x speedup on multi-core systems
- Fast completion on large batches of files

**Incremental re-analysis (refresh_project with incremental=true):**
- Appears to use fewer subprocesses or possibly single-threaded execution
- Noticeably slower than expected for the number of changed files
- Does not match the parallelism of initial indexing

### Comparison with Reference Implementation

The `scripts/test_mcp_console.py` script demonstrates proper parallel execution for both cases:
- Initial indexing: uses full parallelism
- Incremental refresh: should use same parallelism

### Impact

**Problem:** Slower incremental updates than necessary:
- Changed file re-analysis takes longer than it should
- Wastes CPU resources (cores sitting idle)
- Poor user experience when frequently refreshing during development
- Doesn't scale well to projects with many modified files

**Expected Behavior:**
- Incremental re-analysis should use the same number of worker processes as initial indexing
- Small file counts (1-5 files) can use fewer workers
- Larger batches (10+ files) should use full parallelism

### Investigation Areas

**Possible root causes:**
1. `refresh_project` implementation may not pass file list to parallel processing properly
2. Incremental analyzer may process files sequentially instead of batching
3. Different code path for re-analysis vs initial indexing
4. ProcessPoolExecutor not being reused or recreated with fewer workers
5. Synchronous processing in incremental update path

**Key files to examine:**
- `mcp_server/cpp_analyzer.py` - `refresh_project()` method
- `mcp_server/incremental_analyzer.py` - re-analysis implementation
- `scripts/test_mcp_console.py` - reference implementation showing proper parallelism

### Investigation Status

⏸️ **PENDING** - Awaiting user request to begin analysis

### Next Steps (When Approved)

1. Examine `refresh_project()` implementation in `cpp_analyzer.py`
2. Compare with initial indexing code path
3. Check how changed files are passed to parallel processing
4. Review `incremental_analyzer.py` for sequential processing
5. Verify ProcessPoolExecutor usage in incremental path
6. Compare with `test_mcp_console.py` to identify differences
7. Implement parallel processing for incremental re-analysis
8. Add performance metrics to measure improvement
9. Test with various numbers of changed files (1, 10, 100, 1000)

---

## Issue: LLM May Trigger Full Refresh Without User Confirmation (Dangerous Behavior)

**Platform:** macOS (observed during LM Studio testing with Qwen3-4B)

### Observation

Qwen3-4B exhibited the following behavior when unable to find a requested class:
1. User asked to find a specific class
2. LLM couldn't find it in search results
3. LLM called `refresh_project(incremental=true)` to ensure no files were missed
4. Still couldn't find the class after incremental refresh
5. **LLM then called `refresh_project(force_full=true)` without asking user**

### Why This Is Problematic

**Critical issue:** Full refresh is an expensive, time-consuming operation that should NEVER be triggered automatically by LLM without explicit user permission.

**Consequences of unauthorized full refresh:**
- **Large projects:** Can take 30-60+ minutes to complete (e.g., 5700+ file project)
- **Resource intensive:** High CPU usage, blocks other work
- **Wasteful:** Often unnecessary - class might not exist, or user made a typo
- **User frustration:** Unexpected long wait time, no way to cancel easily
- **Server load:** Ties up the MCP server for extended period
- **May timeout:** Could hit MCP timeout limits (Issue #2)

**User expectations:**
- Incremental refresh: reasonable automatic fallback (fast, low impact)
- **Full refresh: requires explicit user approval** (slow, high impact)

### Current Tool Description

The `refresh_project` tool description does NOT clearly warn against automatic full refresh:

```python
"force_full": {
    "type": "boolean",
    "description": "If true, forces a complete re-indexing of all files, ignoring the cache. Use this only after major configuration changes or when you suspect cache corruption. Default is false (use incremental refresh when available).",
    "default": False,
}
```

**Problems with current description:**
- Uses weak language: "Use this only..." (not enforced)
- Doesn't mention time/resource cost
- Doesn't explicitly forbid automatic invocation
- No mention of requiring user permission

### Recommendation

**Multi-layered protection approach:**

**1. Code-level safeguard (strongest protection):**
```python
# Add user confirmation requirement for force_full=true
if force_full and not user_confirmed:
    return TextContent(
        type="text",
        text="Full refresh requires user confirmation due to high cost. "
             "Please ask the user: 'This will re-index the entire project, "
             "which may take 30-60+ minutes on large codebases. Continue?'"
    )
```

**2. Improve tool description (LLM guidance):**
```python
"force_full": {
    "type": "boolean",
    "description": "If true, forces complete re-indexing of ALL files (ignoring cache). "
                   "**WARNING: EXTREMELY EXPENSIVE** - can take 30-60+ minutes on large projects. "
                   "**NEVER use automatically** - ALWAYS ask user for explicit permission first. "
                   "Only use after: (1) user explicitly approves, AND (2) major config changes "
                   "or suspected cache corruption. Default is false.",
    "default": False,
}
```

**3. Add explicit prohibition in main tool description:**
Add to `refresh_project` main description:
```
**CRITICAL: If you consider using force_full=true, you MUST ask the user for permission first.
Do NOT invoke full refresh automatically - it can take 30-60+ minutes on large projects.**
```

**4. Alternative: Remove force_full parameter entirely:**
- Make full refresh a separate tool: `force_full_refresh` with scary name
- Require explicit user intent to use the dangerous tool
- Main `refresh_project` tool only does incremental (safe)

**5. Add helper workflow guidance:**
When class not found after incremental refresh, LLM should:
```
1. Suggest user check spelling of class name
2. Suggest using pattern='.*' to list all classes
3. Suggest checking if class exists in external dependencies (project_only=false)
4. Suggest examining specific files with find_in_file
5. **ONLY IF** user explicitly requests: offer full refresh with time warning
```

### Affected Models

**High risk:** Small models (Qwen3-4B, etc.) that follow "try harder" strategies without understanding cost
**Medium risk:** Mid-size models that might escalate too aggressively
**Low risk:** Large models (GPT-4, Claude) that better understand user permission requirements

### Investigation Status

⏸️ **PENDING** - Awaiting user request to begin analysis

### Next Steps (When Approved)

1. **Immediate:** Update tool description with strong warnings
2. **Code safeguard:** Add user confirmation check for force_full=true
3. **Alternative design:** Consider separate tool for full refresh
4. **Add guidance:** Help LLMs with better workflow when class not found
5. **Test with models:** Verify safeguards prevent unauthorized full refresh
6. **Documentation:** Update examples showing proper permission workflow
7. **Consider:** Add cooldown/rate limiting for full refresh (prevent repeated calls)
8. **Consider:** Add --dry-run mode to estimate full refresh time before executing

### Related Issues

- **Issue #2:** refresh_project timeout - full refresh exacerbates this problem
- **Issue #6:** Incremental refresh performance - if incremental was faster, LLMs might not escalate to full

---

## Issue: Database Missing Header Files and Header Symbols After Refresh

**Platform:** macOS (observed during LM Studio testing)

### Observation

After performing a refresh operation (either incremental or full - unclear which), the database appeared to lose critical information:
1. **Header files not found:** Requests to find exact header files returned no match
2. **Header symbols not found:** Classes and other symbols defined in header files returned no match

### Evidence

**Symptoms:**
- Search for known header files: no results
- Search for classes that are defined in headers: no results
- Suggests either:
  - Headers were not indexed during refresh
  - Header data was deleted but not re-added
  - Database corruption during refresh operation

### Severity

**Critical data integrity issue:**
- Headers contain most critical declarations in C++ projects (classes, APIs, etc.)
- Missing header symbols makes the MCP server nearly useless
- User cannot find classes, functions, or any header-defined symbols
- Appears to be a regression from previous state (symbols were found before refresh)

### Possible Root Causes

**1. Header deduplication gone wrong:**
- First-win header strategy (mcp_server/header_tracker.py) may be broken
- Headers might be skipped during refresh
- Header tracking state not properly restored from cache

**2. Refresh operation bug:**
- Incremental refresh may delete header symbols without re-adding them
- Full refresh may skip headers entirely
- Database transaction not properly committed

**3. File scanner issue:**
- Headers not being discovered during refresh
- File patterns excluding .h files
- Header files not being passed to parallel processing

**4. Compile commands integration:**
- When using compile_commands.json, only .cpp files are listed
- Headers included by .cpp files should be tracked via dependencies
- Header tracking may be broken after refresh

**5. Database corruption:**
- Related to Issue #3 (file descriptor leak)?
- SQLite database corrupted during refresh operation
- Header symbols table/index damaged

**6. Cache invalidation issue:**
- Header symbols marked for deletion but not re-indexed
- Dependency graph tracking headers incorrectly
- ChangeScanner/CompileCommandsDiffer not detecting header changes

### Investigation Areas

**Key questions to answer:**
1. Are header files present in `file_index` after refresh?
2. Are header symbols present in `class_index` and `function_index`?
3. Does `diagnose_cache.py` show header file entries?
4. Does SQLite database contain header file paths?
5. Are headers being passed to `_process_file_worker()`?
6. Is header_tracker.json cache file valid after refresh?
7. Does the issue occur after incremental refresh, full refresh, or both?

**Files to examine:**
- `mcp_server/cpp_analyzer.py` - refresh_project(), index_project()
- `mcp_server/incremental_analyzer.py` - header handling during incremental refresh
- `mcp_server/header_tracker.py` - header deduplication logic
- `mcp_server/file_scanner.py` - header file discovery
- `mcp_server/sqlite_cache_backend.py` - header symbol storage

### Reproduction Steps Needed

1. Index a project with header files
2. Verify headers and symbols are found (baseline)
3. Modify some files (for incremental refresh test)
4. Call `refresh_project(incremental=true)`
5. Try to find header files and header symbols
6. Document whether they're missing

Then repeat with:
1. Call `refresh_project(force_full=true)`
2. Try to find header files and header symbols
3. Document whether they're missing

### Investigation Status

⏸️ **PENDING** - Awaiting user request to begin analysis

### Next Steps (When Approved)

1. **Reproduce the issue:**
   - Set up test project with headers
   - Perform refresh operations
   - Verify header symbols disappear

2. **Diagnose database state:**
   - Run `scripts/diagnose_cache.py` after refresh
   - Check if headers exist in database
   - Count header vs source file entries

3. **Add debug logging:**
   - Log which files are being processed during refresh
   - Log header tracking state
   - Log database operations on header symbols

4. **Examine code paths:**
   - Trace refresh_project() execution
   - Check if headers are passed to indexing pipeline
   - Verify header_tracker state preservation

5. **Fix root cause:**
   - Ensure headers are properly indexed during refresh
   - Fix header tracking if broken
   - Add test to prevent regression

6. **Add integration test:**
   - Test that verifies header symbols persist after refresh
   - Test incremental and full refresh separately

### Related Issues

- **Issue #3:** File descriptor leak - could cause database corruption affecting headers
- **Issue #6:** Incremental refresh performance - may have different code path that breaks headers
- **Issue #7:** Unauthorized full refresh - if users trigger this, they might hit this bug

---

## Issue: Hardcoded libclang Paths Don't Match Common macOS Installations

**Platform:** macOS

### Observation

The current hardcoded paths for finding system libclang on macOS do not match common installation locations. On the test system, libclang is available at:

**Available system installations:**
- **Xcode Command Line Tools:** `/Library/Developer/CommandLineTools/usr/lib/libclang.dylib`
- **Homebrew (Apple Silicon):** `/opt/homebrew/Cellar/llvm/21.1.7/lib/libclang.dylib`

**Current behavior:**
- System libclang not detected at these locations
- Falls back to downloading and using bundled libclang version
- Downloads to `lib/macos/lib/libclang.dylib`

### Why This Matters

**Problems with current approach:**

1. **Unnecessary downloads:** Users already have libclang installed via Xcode/Homebrew
2. **Version mismatch:** Bundled version may not match user's system clang/compiler
3. **Disk space:** Duplicate libclang installation wastes disk space
4. **Maintenance overhead:** Need to keep bundled libclang updated
5. **Compatibility:** System libclang matches the compiler user is actually using

**Benefits of using system libclang:**
- Guaranteed compatibility with user's C++ toolchain
- Always up-to-date with system updates
- No download time
- Smaller package size
- Uses same version as user's compiler

### Current Implementation

**Likely location of hardcoded paths:**
- `scripts/download_libclang.py` - download script
- `mcp_server/cpp_analyzer.py` - libclang initialization
- Possibly other files that set `LIBCLANG_PATH`

**Existing mechanism:**
- Environment variable: `LIBCLANG_PATH` (already supports user override)
- Fallback: bundled version in `lib/{platform}/lib/`

### Recommendation

**Multi-tiered approach for better libclang discovery:**

**1. Expand hardcoded search paths (short-term fix):**
```python
MACOS_SEARCH_PATHS = [
    # Existing paths (if any)

    # Xcode Command Line Tools
    "/Library/Developer/CommandLineTools/usr/lib/libclang.dylib",

    # Homebrew (Apple Silicon)
    "/opt/homebrew/lib/libclang.dylib",
    "/opt/homebrew/Cellar/llvm/*/lib/libclang.dylib",  # glob pattern

    # Homebrew (Intel)
    "/usr/local/lib/libclang.dylib",
    "/usr/local/Cellar/llvm/*/lib/libclang.dylib",  # glob pattern

    # MacPorts
    "/opt/local/libexec/llvm-*/lib/libclang.dylib",

    # System locations
    "/usr/lib/libclang.dylib",

    # Bundled (last resort)
    "lib/macos/lib/libclang.dylib",
]
```

**2. Smart discovery using system tools (better long-term):**

```bash
# Detect clang location and derive libclang path
clang_path=$(which clang)  # e.g., /usr/bin/clang
# Transform to lib path: /usr/lib/libclang.dylib

# Or use llvm-config if available
llvm-config --libdir  # gives /opt/homebrew/opt/llvm/lib
# Append /libclang.dylib

# Or use brew info
brew --prefix llvm  # gives /opt/homebrew/opt/llvm
# Append /lib/libclang.dylib
```

**3. Configuration file option:**
```json
// cpp-analyzer-config.json
{
  "libclang": {
    "path": "/opt/homebrew/Cellar/llvm/21.1.7/lib/libclang.dylib",
    "prefer_system": true,
    "fallback_to_bundled": true
  }
}
```

**4. Command line option:**
```bash
python -m mcp_server.cpp_mcp_server --libclang-path /path/to/libclang.dylib
```

**5. Priority order (recommended):**
```
1. LIBCLANG_PATH environment variable (explicit user override)
2. cpp-analyzer-config.json "libclang.path" (per-project config)
3. Command line --libclang-path (runtime override)
4. Smart discovery (which clang, llvm-config, brew --prefix llvm)
5. Hardcoded common paths (search list)
6. Bundled download (last resort)
```

**6. Add validation and diagnostics:**
```python
def find_libclang():
    """Find libclang with detailed logging."""
    sources = [
        ("env variable LIBCLANG_PATH", os.environ.get("LIBCLANG_PATH")),
        ("config file", config.get("libclang.path")),
        ("command line", args.libclang_path),
        ("system clang", discover_from_system_clang()),
        ("llvm-config", discover_from_llvm_config()),
        ("homebrew", discover_from_homebrew()),
        ("hardcoded paths", search_common_locations()),
        ("bundled", "lib/macos/lib/libclang.dylib"),
    ]

    for source_name, path in sources:
        if path and os.path.exists(path):
            logger.info(f"Found libclang via {source_name}: {path}")
            return path

    logger.error("libclang not found in any location")
    raise FileNotFoundError("libclang not found")
```

### Investigation Areas

**Files to examine:**
- `scripts/download_libclang.py` - current download logic
- `mcp_server/cpp_analyzer.py` - libclang loading
- `server_setup.sh` - setup script that calls download
- `scripts/test_installation.py` - installation verification

**Questions to answer:**
1. What are current hardcoded paths on macOS?
2. Where is libclang path discovery implemented?
3. Does LIBCLANG_PATH environment variable work correctly?
4. Can we use `ctypes.util.find_library("clang")`?
5. What version constraints exist (minimum libclang version)?

### Platform-Specific Considerations

**macOS:**
- Xcode Command Line Tools: `/Library/Developer/CommandLineTools/usr/lib/`
- Homebrew Apple Silicon: `/opt/homebrew/Cellar/llvm/*/lib/`
- Homebrew Intel: `/usr/local/Cellar/llvm/*/lib/`
- MacPorts: `/opt/local/libexec/llvm-*/lib/`

**Linux:**
- System packages: `/usr/lib/x86_64-linux-gnu/libclang-*.so.1`
- Custom builds: `/usr/local/lib/libclang.so`
- LLVM official: `/usr/lib/llvm-*/lib/libclang.so`

**Windows:**
- Visual Studio: `C:\Program Files\LLVM\bin\libclang.dll`
- Scoop/Chocolatey: various locations

### Investigation Status

⏸️ **PENDING** - Awaiting user request to begin analysis

### Next Steps (When Approved)

1. **Audit current implementation:**
   - Find all libclang path discovery code
   - Document current search order
   - Test current LIBCLANG_PATH env var support

2. **Implement smart discovery:**
   - Add `which clang` → derive lib path
   - Add `llvm-config --libdir` support
   - Add `brew --prefix llvm` support (macOS)
   - Add glob pattern matching for versioned paths

3. **Expand search paths:**
   - Add Xcode Command Line Tools path
   - Add Homebrew paths (both architectures)
   - Add MacPorts paths
   - Use glob patterns for version-specific paths

4. **Add configuration options:**
   - Support config file libclang.path
   - Add command line --libclang-path option
   - Document priority order

5. **Improve diagnostics:**
   - Log all search attempts
   - Show which source was used
   - Warn if using bundled vs system
   - Show version mismatch warnings

6. **Update documentation:**
   - Document all discovery methods
   - Show how to override
   - Explain priority order
   - Add troubleshooting guide

7. **Testing:**
   - Test on fresh macOS (Xcode only)
   - Test on Homebrew installation
   - Test with LIBCLANG_PATH override
   - Test with missing system libclang

### Related Considerations

**Version compatibility:**
- Minimum libclang version required?
- How to check version of discovered libclang?
- Should we enforce version constraints?

**Multiple installations:**
- What if multiple libclang versions found?
- Prefer newer vs older?
- Prefer system vs bundled?

**Error handling:**
- What if discovered libclang doesn't work?
- Fallback to next option?
- Clear error messages for user

---

## Issue: get_server_status Reports Zero Files After Successful Indexing

**Platform:** Linux (observed during manual testing on 2025-12-21)

### Observation

After successfully calling `set_project_directory` and completing indexing (verified by 45,639 classes and 211,367 functions indexed), `get_server_status` returns zero for file-related counts:

```json
{
  "analyzer_type": "python_enhanced",
  "call_graph_enabled": true,
  "usr_tracking_enabled": true,
  "compile_commands_enabled": true,
  "compile_commands_path": "/path/to/build/compile_commands.json",
  "compile_commands_cache_enabled": true,
  "parsed_files": 0,        // ← Should NOT be zero!
  "indexed_classes": 45639,
  "indexed_functions": 211367,
  "project_files": 0         // ← Should NOT be zero!
}
```

### Root Cause Analysis

**Bug introduced by file descriptor leak fix (commit 2e6700f):**

1. **What was removed:** The FD leak fix removed `self.translation_units` dict (it was write-only, causing file descriptor leaks)
2. **What wasn't updated:** `get_server_status` still references the removed dict:

```python
# mcp_server/cpp_mcp_server.py:997-1000
status.update({
    "parsed_files": len(analyzer.translation_units),    # ← Dict no longer exists!
    "indexed_classes": total_classes,
    "indexed_functions": total_functions,
    "project_files": len(analyzer.translation_units),   # ← Returns 0
})
```

3. **Why symbols still work:** Classes and functions are stored in `class_index` and `function_index`, which were NOT removed

### Evidence

```bash
# translation_units dict was removed:
$ git show 2e6700f
"CRITICAL FIX: Stop storing TranslationUnits - they're never used!"

# But get_server_status wasn't updated:
$ grep "translation_units" mcp_server/cpp_mcp_server.py
    "parsed_files": len(analyzer.translation_units),
    "project_files": len(analyzer.translation_units),
```

### Impact

**Problem:** Misleading/incorrect status information:
- Users cannot determine how many files were processed
- Status tool provides incomplete information
- Creates confusion about indexing completion
- Could affect debugging and diagnostics

**Expected Behavior:**
- `parsed_files` should show actual count of files processed
- `project_files` should show total files in project
- Counts should match reality (thousands of files for large projects)

### Solution

**Simple fix - use `file_index` instead:**

```python
# mcp_server/cpp_mcp_server.py:997-1000
status.update({
    "parsed_files": len(analyzer.file_index),      # Files with extracted symbols
    "indexed_classes": total_classes,
    "indexed_functions": total_functions,
    "project_files": len(analyzer.file_index),     # Same count
})
```

### Investigation Status

⏸️ **DOCUMENTED** - Ready for fix in separate PR

### Next Steps

1. Create separate PR to fix `get_server_status` counts
2. Update lines 997 and 1000 in `mcp_server/cpp_mcp_server.py`
3. Change `len(analyzer.translation_units)` to `len(analyzer.file_index)`
4. Test with large project to verify correct counts
5. Consider adding test to prevent similar regressions

### Related Issues

- **Introduced by:** File descriptor leak fix (Issue #3, commit 2e6700f)
- **Not related to:** refresh_project timeout fix (Issue #2)
- **Affects:** All platforms (Linux, macOS, Windows)

---

## Issue: refresh_project Doesn't Report Progress During Refresh

**Platform:** All platforms (observed during manual testing on 2025-12-21)

### Observation

After calling `refresh_project`, the operation correctly runs in the background (non-blocking), but `get_indexing_status` returns `progress: null` during the entire refresh:

```json
{
  "state": "refreshing",
  "is_fully_indexed": false,
  "is_ready_for_queries": true,
  "progress": null          // ← No progress information during refresh!
}
```

### Comparison with Initial Indexing

**During initial indexing (set_project_directory):**
```json
{
  "state": "indexing",
  "is_fully_indexed": false,
  "is_ready_for_queries": true,
  "progress": {
    "indexed_files": 1234,
    "total_files": 5678,
    "completion_percentage": 21.7,
    "current_file": "/path/to/file.cpp",
    "eta_seconds": 45.2
  }
}
```

**During refresh (refresh_project):**
```json
{
  "state": "refreshing",
  "progress": null          // ← Missing!
}
```

### Root Cause Analysis

**Progress tracking not implemented for refresh operations:**

1. **Initial indexing has progress:**
   - `set_project_directory` → `BackgroundIndexer.start_indexing()`
   - Passes `progress_callback` to `analyzer.index_project()`
   - `index_project()` periodically calls `progress_callback(progress)`
   - Callback updates `state_manager._progress`

2. **Refresh operations lack progress:**
   - `refresh_project` → `run_background_refresh()` (async function)
   - Calls `analyzer.refresh_if_needed()` or `incremental_analyzer.perform_incremental_analysis()`
   - **Neither function accepts progress_callback parameter**
   - **Neither function reports progress**
   - State transitions to REFRESHING but `_progress` stays null

### Evidence

```python
# mcp_server/cpp_analyzer.py:2158
def refresh_if_needed(self) -> int:
    # No progress_callback parameter!
    # No progress reporting during execution

# mcp_server/incremental_analyzer.py:89
def perform_incremental_analysis(self) -> AnalysisResult:
    # No progress_callback parameter!
    # Returns AnalysisResult at end, but no intermediate progress
```

### Impact

**Problem:** Poor user experience during refresh:
- Users cannot monitor refresh progress
- No visibility into how many files are being processed
- No ETA for completion
- Inconsistent with initial indexing experience
- Users must wait without feedback (especially for large refreshes)

**Expected Behavior:**
- Refresh should report progress similar to initial indexing
- Show files processed, total files, completion percentage
- Provide ETA for long-running refreshes
- Update progress periodically during execution

### Solution

**Requires architectural changes:**

1. **Add progress callback support to refresh methods:**
   ```python
   # cpp_analyzer.py
   def refresh_if_needed(self, progress_callback=None) -> int:
       # Report progress during file processing

   # incremental_analyzer.py
   def perform_incremental_analysis(self, progress_callback=None) -> AnalysisResult:
       # Report progress during re-analysis
   ```

2. **Update run_background_refresh to use progress callback:**
   ```python
   async def run_background_refresh():
       state_manager.transition_to(AnalyzerState.REFRESHING)

       def progress_callback(progress: IndexingProgress):
           state_manager.update_progress(progress)

       # Pass callback to refresh methods
       result = await loop.run_in_executor(
           None,
           lambda: incremental_analyzer.perform_incremental_analysis(
               progress_callback=progress_callback
           )
       )
   ```

3. **Modify _reanalyze_files to report progress:**
   ```python
   # incremental_analyzer.py:_reanalyze_files
   def _reanalyze_files(self, files: Set[str], progress_callback=None) -> int:
       total = len(files)
       for idx, file_path in enumerate(files):
           # ... process file ...
           if progress_callback:
               progress_callback(IndexingProgress(
                   indexed_files=idx+1,
                   total_files=total,
                   current_file=file_path,
                   # ... other fields
               ))
   ```

### Investigation Status

⏸️ **DOCUMENTED** - Enhancement for future work

### Next Steps

1. Add progress_callback parameter to:
   - `analyzer.refresh_if_needed()`
   - `incremental_analyzer.perform_incremental_analysis()`
   - `incremental_analyzer._reanalyze_files()`

2. Update run_background_refresh to create and pass progress callback

3. Implement progress reporting in _reanalyze_files sequential loop

4. Test with various refresh scenarios:
   - Incremental refresh (few files)
   - Full refresh (many files)
   - Force full refresh

5. Ensure progress resets to null after INDEXED state transition

### Related Issues

- **Issue #2:** refresh_project timeout (RESOLVED - now non-blocking)
- **Issue #6:** Sequential processing in incremental refresh (affects progress reporting)
- **Enhancement:** This issue is about visibility, not performance

### Priority

**Medium - UX Enhancement:**
- Refresh works correctly (non-blocking)
- Progress reporting would improve user experience
- Especially important for large projects with slow refreshes
- Not critical for functionality

---

## Issue: Database Connection Error During Refresh - "Cannot operate on a closed database"

**Platform:** All platforms (observed during incremental refresh on 2025-12-21)

### Observation

During `refresh_project` execution, warnings appear indicating SQLite database operations fail:

```
[WARNING] Failed to update dependencies for /path/to/project/File1.h: Cannot operate on a closed database.
[WARNING] Failed to update dependencies for /path/to/project/File2.h: Cannot operate on a closed database.
```

### Root Cause Analysis

**Shared database connection with mismatched lifecycle:**

1. **Connection sharing setup:**
   ```python
   # mcp_server/cpp_analyzer.py:270
   if hasattr(self.cache_manager.backend, "conn"):
       self.dependency_graph = DependencyGraphBuilder(self.cache_manager.backend.conn)
   ```
   - DependencyGraphBuilder shares the same SQLite connection as cache backend

2. **Connection closing:**
   ```python
   # mcp_server/cpp_analyzer.py:310
   self.cache_manager.close()
   ```
   - Closes the shared connection

3. **Stale reference:**
   ```python
   # mcp_server/dependency_graph.py:173
   self.conn.cursor()  # ← Tries to use closed connection!
   ```
   - DependencyGraphBuilder still holds reference to closed connection
   - Operations fail with SQLite error

### When This Occurs

**Triggered during incremental refresh:**
- Sequential file re-analysis in `_reanalyze_files()`
- Each file calls `index_file()` which tries to update dependencies
- If cache manager closed between files, dependency updates fail
- Non-fatal: caught and logged as warning at `cpp_analyzer.py:1291`

### Evidence

```python
# mcp_server/cpp_analyzer.py:1286-1291
if self.dependency_graph is not None:
    try:
        includes = self.dependency_graph.extract_includes_from_tu(tu, source_file)
        self.dependency_graph.update_dependencies(source_file, includes)  # ← Fails!
    except Exception as e:
        diagnostics.warning(f"Failed to update dependencies for {source_file}: {e}")
        # ← Logs "Cannot operate on a closed database"
```

### Impact

**Problem:** Dependency tracking incomplete after refresh:
- Files re-analyzed successfully (symbols extracted)
- But dependency graph not updated for those files
- Incremental refresh on next run may miss cascading header changes
- Could cause stale symbol data to persist

**Expected Behavior:**
- Dependencies should be updated for all re-analyzed files
- Connection should remain open during entire refresh operation
- Or dependency graph should handle closed connection gracefully

### Solution Options

**Option 1: Keep connection open during refresh**
```python
# Don't close cache_manager until all operations complete
# Ensure connection lifecycle matches operation lifecycle
```

**Option 2: Separate dependency connection**
```python
# Create separate connection for dependency_graph
# Don't share connection with cache backend
self.dependency_graph = DependencyGraphBuilder(
    sqlite3.connect(db_path)  # Own connection
)
```

**Option 3: Check connection before use**
```python
# dependency_graph.py:update_dependencies
def update_dependencies(self, source_file: str, included_files: List[str]) -> int:
    if not self._is_connection_open():
        diagnostics.warning("Database connection closed, skipping dependency update")
        return 0
    # ... existing code
```

### Investigation Status

⏸️ **DOCUMENTED** - Database lifecycle management issue

### Next Steps

1. Trace cache_manager.close() calls during refresh
2. Determine when/why connection closes during operation
3. Choose solution approach (keep open vs separate connection)
4. Implement fix
5. Add test for dependency updates during incremental refresh
6. Verify no "closed database" errors after fix

### Related Issues

- **Issue #6:** Sequential processing in incremental refresh (where this error occurs)
- **Issue #11:** Missing progress reporting during refresh (same code path)

---

## Issue: Missing Third-Party Headers During Refresh (Expected Behavior)

**Platform:** All platforms (observed during refresh on 2025-12-21)

### Observation

During refresh, some files fail to parse with missing header errors:

```
libclang parsing errors (1 total):
[fatal] /path/to/project/Utils/Preprocessor/OverloadedMacro.h:10:10: 'boost/preprocessor/cat.hpp' file not found
```

### Analysis

**This is expected behavior, not a bug:**

1. **Files not in compile_commands.json:**
   - If a file isn't listed in compile_commands.json, fallback args are used
   - Fallback args are generic: `-std=c++17 -I/path/to/project`
   - Don't include project-specific third-party paths (boost, etc.)

2. **Why it happens during refresh:**
   - Incremental refresh may pick up files not tracked by build system
   - Header files are often not in compile_commands.json (only .cpp files)
   - When refreshing headers, fallback args used

3. **Error recovery:**
   - libclang continues parsing despite errors (partial AST extraction)
   - Symbols from parseable parts still extracted
   - See Issue #3 documentation: "Continue on parse errors"

### Evidence

```python
# mcp_server/cpp_analyzer.py:1324
args = self.compile_commands_manager.get_compile_args_with_fallback(file_path_obj)
# ↑ Uses fallback if file not in compile_commands.json

# mcp_server/cpp_analyzer.py:1507
"Using fallback compilation args - compile_commands.json may be needed"
```

### Impact

**Not a defect:**
- Partial symbol extraction still works (libclang error recovery)
- Errors logged for user awareness
- User can fix by ensuring files are in compile_commands.json
- Or by adding third-party include paths to config

**User action (if needed):**
- Regenerate compile_commands.json to include more files
- Or configure include paths in cpp-analyzer-config.json
- Or accept partial parsing for headers not in build

### Investigation Status

✅ **EXPECTED BEHAVIOR** - Not a bug, informational only

---

## General Status

✅ **Working:** MCP server general functionality
✅ **Working:** LM Studio SSE transport connection
✅ **Working:** LLM able to answer codebase-related questions using tools
✅ **Working:** SSE protocol implementation with canonical paths

### Issues Observed on Linux (Prioritized for Manual Testing)
🔴 **Issue #3 [PRIORITY 1 - HIGH]:** File descriptor leak - "Too many open files" during large project indexing
- **Blocks manual testing on Linux** - prevents indexing completion on large projects
- Does NOT occur on macOS (platform-specific)

⚠️ **Issue #2 [PRIORITY 2 - MEDIUM]:** refresh_project times out due to synchronous implementation
- Tool call times out with MCP error -32001
- Synchronous operation blocks testing workflow

⚠️ **Issue #1 [PRIORITY 3 - LOW]:** set_project_directory state synchronization race condition
- Race condition between setting state and background indexing
- Lower impact on manual testing workflow

⚠️ **Issue #10:** get_server_status reports zero files after successful indexing
- Regression from FD leak fix (commit 2e6700f)
- Simple 2-line fix: use `file_index` instead of removed `translation_units`
- Affects all platforms

⚠️ **Issue #11:** refresh_project doesn't report progress during refresh
- Progress stays null during REFRESHING state (inconsistent with initial indexing)
- UX enhancement - requires adding progress_callback support to refresh methods
- Medium priority (non-blocking, but affects user experience on large refreshes)

🔴 **Issue #12:** Database connection closed during refresh causes dependency tracking failures
- "Cannot operate on a closed database" errors during incremental refresh
- Shared SQLite connection between cache_manager and dependency_graph with mismatched lifecycle
- Dependencies not updated for re-analyzed files (could cause stale data on next refresh)
- Requires connection lifecycle fix or separate dependency connection

ℹ️ **Note:** Missing third-party header errors (e.g., boost) during refresh are expected behavior when files aren't in compile_commands.json (fallback args used)

### Issues Observed on macOS (LM Studio Testing)
⚠️ **Issue #4:** Class search uses substring matching by default (should use exact match)
⚠️ **Issue #5:** Tool descriptions may encourage incorrect filename-to-classname assumptions (affects small models)
⚠️ **Issue #6:** Incremental re-analysis uses fewer subprocesses than initial indexing (performance degradation)
🔴 **Issue #7:** LLM may trigger full refresh without user confirmation (CRITICAL - dangerous behavior)
🔴 **Issue #8:** Database missing header files and header symbols after refresh (CRITICAL - data integrity)
⚠️ **Issue #9:** Hardcoded libclang paths don't match common macOS installations (Xcode/Homebrew)
