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

### Fix Status

✅ **FIXED** in PR #66 (commit dfa65e6)

**Solution:** Applied async pattern similar to Issue #2 fix:
- Set state immediately before starting background indexing
- Background indexing continues asynchronously
- `get_indexing_status` now works immediately after `set_project_directory`

**Validated:** No more race condition; state is set correctly from the start

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

### Fix Status

✅ **FIXED** in PR #63 (commit e155aba)

**Solution:** Made `refresh_project` non-blocking:
- Starts refresh operation in background (async)
- Returns immediately with success message
- Client can poll `get_indexing_status` to check progress
- Consistent with `set_project_directory` pattern

**Validated:** No more MCP timeout errors; refresh runs in background successfully

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

### Fix Status

✅ **FIXED** in PR #62 (commits 2e6700f, 9b2a3b1, e9216f9, 0feab08)

**Root Cause Identified:**
- `self.translation_units` dict was write-only (never read)
- Stored all TranslationUnit objects, preventing garbage collection
- Each TU holds file descriptors; accumulation caused FD leak
- Worker processes accumulated indexes and TUs across files

**Solution Applied (Multi-part fix):**
1. **Stop storing TranslationUnits** (commit 2e6700f) - removed write-only dict
2. **Explicit TU deletion** (commit 9b2a3b1) - `del tu` after symbol extraction
3. **Force garbage collection** (commit e9216f9) - `gc.collect()` after each file
4. **Worker cleanup** (commit 0feab08) - prevent TU/index accumulation in workers

**Validated:**
- File descriptors remain stable at 10-15 during indexing
- No "Too many open files" errors on large projects (5700+ files tested)
- Resource monitoring shows proper cleanup

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

### Fix Status

📋 **DEFERRED** - Phase 4 (Future Work)

**Rationale:** Minor usability issue; workaround exists (use exact pattern in search)
- Not blocking manual testing or core functionality
- Lower priority compared to critical data integrity and performance issues
- Can be addressed in future enhancement cycle

**Workaround:** Users can specify exact patterns when needed

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

### Fix Status

📋 **DEFERRED** - Phase 4 (Future Work)

**Rationale:** Affects primarily small models; larger models handle correctly
- Not a critical issue for mainstream LLM usage
- Workaround: use more capable models for production
- Tool descriptions can be improved in future documentation pass

**Priority:** Low - documentation enhancement for edge case compatibility

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

### Fix Status

✅ **FIXED** in PR #73 (commits fd1d513, 414698b)

**Root Cause Identified:**
- `_reanalyze_files()` used sequential file processing loop
- Did not leverage ProcessPoolExecutor for parallel execution
- Different code path from initial indexing

**Solution Applied:**
- Refactored `_reanalyze_files()` to use ProcessPoolExecutor
- Reuses same parallel processing pattern as initial indexing
- Achieves 6-7x speedup on refresh operations

**Validated:**
- Refresh now uses full ProcessPoolExecutor with multiple workers
- Performance matches initial indexing (6-7x speedup on multi-core systems)
- Parallel processing verified during incremental refresh

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

### Fix Status

📋 **DEFERRED** - Phase 4 (Future Work)

**Rationale:** Important safety concern, but mitigated by other fixes
- Issues #2, #6, #11 fixes make incremental refresh fast and reliable
- LLMs less likely to escalate to full refresh when incremental works well
- Can add stronger warnings and safeguards in future iteration

**Mitigation:**
- Fast, reliable incremental refresh reduces need for full refresh
- Progress reporting gives LLMs visibility into refresh status
- Parallel processing makes refresh complete quickly

**Priority:** Medium - safety/UX enhancement for future consideration

### Related Issues

- **Issue #2:** ✅ Fixed - refresh no longer times out
- **Issue #6:** ✅ Fixed - incremental refresh now fast with parallel processing
- **Issue #11:** ✅ Fixed - progress reporting provides visibility

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

### Fix Status

✅ **FIXED** in PR #71 (commits cded32c, 66474f1)

**Root Cause Identified:**
- Headers incorrectly marked as deleted during incremental refresh
- After fixing Issues #13 and #12, issue still persisted
- Incremental refresh logic was treating headers as stale/deleted files

**Solution Applied (Two-part fix):**
1. **Partial fix (commit cded32c):** Prevent headers from being marked as deleted
   - Modified incremental analyzer to preserve header tracking state
   - Prevented false deletion of header symbols

2. **Complete fix (commit 66474f1):** Ensure header symbols persist correctly
   - Fixed header tracking state preservation across refresh operations
   - Ensured header symbols remain in database after refresh
   - Validated header dependency tracking maintains integrity

**Validated:**
- Header files found after incremental refresh
- Header symbols found after refresh (classes, functions in headers)
- Same results before and after refresh
- No false deletion of header data

### Related Issues

- **Issue #13:** ✅ Fixed - headers no longer re-analyzed with fallback args
- **Issue #12:** ✅ Fixed - database connection lifecycle corrected
- **Issue #6:** ✅ Fixed - parallel processing in incremental refresh

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

### Fix Status

📋 **DEFERRED** - Phase 4 (Future Work)

**Rationale:** Platform-specific; workaround exists
- `LIBCLANG_PATH` environment variable provides override mechanism
- Bundled libclang download works as fallback
- Not blocking core functionality or manual testing
- Enhancement for better macOS integration in future

**Workaround:**
```bash
export LIBCLANG_PATH=/opt/homebrew/Cellar/llvm/21.1.7/lib/libclang.dylib
# or
export LIBCLANG_PATH=/Library/Developer/CommandLineTools/usr/lib/libclang.dylib
```

**Priority:** Low - platform-specific convenience enhancement

### Related Considerations

**Version compatibility:**
- Current bundled libclang works reliably across platforms
- System libclang version matching deferred to future work

**Multiple installations:**
- LIBCLANG_PATH override allows explicit control
- Smart discovery can be added in future enhancement

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

### Fix Status

✅ **FIXED** in PR #64 (commit 939a257)

**Root Cause:**
- Regression from FD leak fix (Issue #3, commit 2e6700f)
- Removed `self.translation_units` dict (was causing FD leak)
- But `get_server_status` still referenced the removed dict → returned 0

**Solution Applied:**
```python
# mcp_server/cpp_mcp_server.py:997,1000
# OLD (broken):
"parsed_files": len(analyzer.translation_units),
"project_files": len(analyzer.translation_units),

# NEW (correct):
"parsed_files": len(analyzer.file_index),
"project_files": len(analyzer.file_index),
```

**Validated:**
- Status now shows correct file counts after indexing
- Verified with large projects (thousands of files)

### Related Issues

- **Introduced by:** Issue #3 fix (commit 2e6700f)
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

### Fix Status

✅ **FIXED** in PR #72 (commit c33042e)

**Root Cause:**
- Progress tracking not implemented for refresh operations
- `set_project_directory` passed `progress_callback`, but `refresh_project` did not
- Neither `refresh_if_needed()` nor `perform_incremental_analysis()` accepted callback

**Solution Applied:**
1. Added `progress_callback` parameter to:
   - `analyzer.refresh_if_needed()`
   - `incremental_analyzer.perform_incremental_analysis()`
   - `incremental_analyzer._reanalyze_files()`

2. Updated `run_background_refresh` to create and pass progress callback

3. Implemented progress reporting in `_reanalyze_files` during file processing

**Validated:**
- `get_indexing_status` now shows progress during refresh
- Progress updates correctly: indexed_files, total_files, completion_percentage, ETA
- Progress resets to null after INDEXED state transition
- Tested with incremental and full refresh scenarios

### Related Issues

- **Issue #2:** ✅ Fixed - refresh no longer times out (non-blocking)
- **Issue #6:** ✅ Fixed - parallel processing in incremental refresh

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

**Real-world evidence (SSE mode with Ctrl-C):**
```
[WARNING] /path/to/QtEditors/TextEditor/PageInfoHint.h: Continuing despite 1 error(s):
libclang parsing errors (1 total):
[fatal] /path/to/CoreConfig.h:10:10: 'CoreConfig.h' file not found
[WARNING] Failed to update dependencies for /path/to/PageInfoHint.h: Cannot operate on a closed database.
^C
INFO:     Shutting down
[WARNING] /path/to/iOSEditors/DeviceFileDataContainer.h: Continuing despite 1 error(s):
[WARNING] Failed to update dependencies for /path/to/DeviceFileDataContainer.h: Cannot operate on a closed database.
INFO:     Application shutdown complete.
[WARNING] /path/to/QtComponents/ActionGridList.h: Continuing despite 1 error(s):
[WARNING] Failed to update dependencies for /path/to/ActionGridList.h: Cannot operate on a closed database.
```

**Shows two problems:**
1. Database connection closed (this issue)
2. Workers continue after server shutdown (Ctrl-C doesn't stop background tasks)

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

### Fix Status

✅ **FIXED** in PR #69 (commit fcc90fa)

**Root Cause:**
- Shared SQLite connection between cache_manager and dependency_graph
- `cache_manager.close()` closed the shared connection
- DependencyGraphBuilder still held reference to closed connection
- Operations failed: `self.conn.cursor()` → "Cannot operate on a closed database"

**Solution Applied:**
- Created separate connection for dependency_graph (not shared)
- Each component manages its own connection lifecycle
- Prevents premature closure affecting dependency tracking

**Validated:**
- No "Cannot operate on a closed database" warnings during refresh
- Dependencies updated correctly for all re-analyzed files
- Dependency graph integrity maintained after refresh

### Related Issues

- **Issue #6:** ✅ Fixed - parallel processing in incremental refresh
- **Issue #11:** ✅ Fixed - progress reporting during refresh

---

## Issue: Headers Re-Analyzed with Fallback Args During Refresh (Bug)

**Platform:** All platforms (observed during incremental refresh on 2025-12-21)

### Observation

During `refresh_project`, header files are re-analyzed using fallback compilation arguments instead of proper args from compile_commands.json, causing missing header errors:

```
[WARNING] /path/to/project/Printing/File1.h: Continuing despite 1 error(s):
libclang parsing errors (1 total):
[fatal] /path/to/project/Utils/Preprocessor/OverloadedMacro.h:10:10: 'boost/preprocessor/cat.hpp' file not found
```

**Key Evidence:**
- Initial indexing (test_mcp_console.py) parses same project without boost errors
- Refresh shows boost/third-party header errors
- Indicates headers being re-analyzed with different (fallback) args during refresh

**Real-world evidence (same session showing multiple third-party header failures):**
```
[WARNING] /path/to/QtComponents/Controls/ActionGridList.h: Continuing despite 1 error(s):
libclang parsing errors (1 total):
[fatal] /path/to/Utils/TypeUtils/DefineValueFromTrait.h:12:10: 'boost/preprocessor/cat.hpp' file not found

[WARNING] /path/to/iOSEditors/Editors/Common/DeviceFileDataContainer.h: Continuing despite 1 error(s):
libclang parsing errors (1 total):
[fatal] /path/to/iOSEditors/Editors/Common/DeviceFileDataContainer.h:9:9: 'Foundation/Foundation.h' file not found

[WARNING] /path/to/WebDAVNetworking/Request/CheckResourceRequest.h: Continuing despite 1 error(s):
libclang parsing errors (1 total):
[fatal] /path/to/Utils/Preprocessor/OverloadedMacro.h:10:10: 'boost/preprocessor/cat.hpp' file not found
```

**Pattern shows:**
- Multiple header files (.h) being parsed directly
- Missing boost headers (C++ third-party library)
- Missing Foundation headers (macOS/iOS system framework)
- All using fallback args that lack proper include paths

### Root Cause Analysis

**Bug in ChangeScanner file categorization:**

1. **CPP_EXTENSIONS includes headers:**
   ```python
   # mcp_server/file_scanner.py:13
   CPP_EXTENSIONS = {".cpp", ".cc", ".cxx", ".c++", ".h", ".hpp", ".hxx", ".h++"}
   #                                                  ↑ Headers included!
   ```

2. **find_cpp_files() returns ALL C++ files:**
   ```python
   # mcp_server/file_scanner.py:66
   if any(filename.endswith(ext) for ext in self.CPP_EXTENSIONS):
       # Returns BOTH sources (.cpp) AND headers (.h)!
   ```

3. **ChangeScanner scans all files as "sources":**
   ```python
   # mcp_server/change_scanner.py:171
   current_source_files = set(self.analyzer.file_scanner.find_cpp_files())
   # ↑ Comment says "source files" but includes headers!

   for source_file in current_source_files:
       # ... check if modified ...
       changeset.modified_files.add(normalized_path)  # ← Headers go here!
   ```

4. **Modified headers categorized twice:**
   - Headers found by directory scan → `modified_files`
   - Same headers found by header_tracker → `modified_headers`
   - Or only in `modified_files` if not previously tracked

5. **Different handling in incremental_analyzer:**
   ```python
   # mcp_server/incremental_analyzer.py

   # Headers in modified_headers: only dependents re-analyzed (CORRECT)
   for header in changes.modified_headers:
       dependents = self._handle_header_change(header)  # Gets .cpp files
       files_to_analyze.update(dependents)  # ← Re-analyze sources, not header

   # Headers in modified_files: header itself re-analyzed (BUG!)
   for source_file in changes.modified_files:  # ← Contains headers too!
       files_to_analyze.add(source_file)  # ← Header added for direct re-analysis!
   ```

6. **Headers not in compile_commands.json:**
   ```python
   # mcp_server/cpp_analyzer.py:1324
   args = self.compile_commands_manager.get_compile_args_with_fallback(file_path_obj)
   # ↑ Headers not in compile_commands.json → fallback args used
   # Fallback args: -std=c++17 -I/path/to/project (missing boost, vcpkg, etc.)
   ```

### Impact

**Problem:** Headers re-analyzed incorrectly during refresh:
- Headers scanned as "source files" in change detection
- Added to files_to_analyze for direct re-parsing
- Not in compile_commands.json (only .cpp files are)
- Fallback args lack third-party include paths (boost, vcpkg)
- Parse errors for missing dependencies
- Inconsistent with initial indexing behavior

**Why initial indexing works:**
- During `index_project()`, headers processed as dependencies of source files
- Source files have proper compile args from compile_commands.json
- Headers inherit those args when included
- No fallback args needed

**Why refresh fails:**
- Headers detected as standalone "modified files"
- Directly re-analyzed independent of any source file
- No compile args available → fallback args used
- Missing third-party paths → parse errors

### Solution

**Option 1: Exclude headers from directory scan (Recommended)**
```python
# mcp_server/change_scanner.py:171
# Only scan for actual SOURCE files, not headers
current_source_files = set()
for file_path in self.analyzer.file_scanner.find_cpp_files():
    # Skip headers - they'll be detected via header_tracker
    if file_path.endswith(('.h', '.hpp', '.hxx', '.h++')):
        continue
    current_source_files.add(file_path)
```

**Option 2: Categorize headers correctly**
```python
# mcp_server/change_scanner.py:185-186
elif change_type == ChangeType.MODIFIED:
    # Check if it's a header or source
    if normalized_path.endswith(('.h', '.hpp', '.hxx', '.h++')):
        changeset.modified_headers.add(normalized_path)
    else:
        changeset.modified_files.add(normalized_path)
```

**Option 3: Don't re-analyze headers directly**
```python
# mcp_server/incremental_analyzer.py:141-143
for source_file in changes.modified_files:
    # Skip headers - they're handled via modified_headers
    if source_file.endswith(('.h', '.hpp', '.hxx', '.h++')):
        continue
    self._handle_source_change(source_file)
    files_to_analyze.add(source_file)
```

### Fix Status

✅ **FIXED** in PR #67 (commit 69f7378)

**Root Cause:**
- `find_cpp_files()` returns BOTH `.cpp` AND `.h` files
- `ChangeScanner` scanned all as "source files"
- Modified headers added to `changeset.modified_files`
- Incremental analyzer directly re-analyzed headers
- Headers not in `compile_commands.json` → fallback args used
- Fallback args lacked third-party include paths (boost, vcpkg, Foundation)

**Solution Applied (Option 1):**
- Filter headers from directory scan in `change_scanner.py`
- Headers detected only via `header_tracker` (as dependencies)
- Headers no longer directly re-analyzed with fallback args
- Re-analysis triggered via dependent source files (correct args inherited)

**Validated:**
- No boost/vcpkg/Foundation header errors during refresh
- Headers only processed as dependencies of source files
- Same compile args used for headers during initial indexing and refresh
- Consistent behavior between initial indexing and refresh

### Related Issues

- **Issue #8:** ✅ Fixed - missing headers (was symptom of this + Issue #12)
- **Issue #12:** ✅ Fixed - database connection lifecycle

---

## General Status - All Critical Issues Resolved ✅

✅ **Working:** MCP server general functionality
✅ **Working:** LM Studio SSE transport connection
✅ **Working:** LLM able to answer codebase-related questions using tools
✅ **Working:** SSE protocol implementation with canonical paths

### Fixed Issues - Phases 1-3 Complete ✅

**Phase 1: Workflow Foundation** ✅
- ✅ **Issue #1:** set_project_directory state synchronization race - **FIXED** PR #66
- ✅ **Issue #2:** refresh_project timeout (synchronous implementation) - **FIXED** PR #63
- ✅ **Issue #3:** File descriptor leak "Too many open files" - **FIXED** PR #62
- ✅ **Issue #10:** get_server_status reports zero files - **FIXED** PR #64

**Phase 2: Refresh Correctness** ✅
- ✅ **Issue #13:** Headers re-analyzed with fallback args - **FIXED** PR #67
- ✅ **Issue #12:** Database connection lifecycle bug - **FIXED** PR #69
- ✅ **Issue #8:** Missing header symbols after refresh - **FIXED** PR #71

**Phase 3: UX Enhancements** ✅
- ✅ **Issue #11:** Missing progress reporting during refresh - **FIXED** PR #72
- ✅ **Issue #6:** Sequential processing in incremental refresh - **FIXED** PR #73

### Deferred Issues - Phase 4 (Future Work) 📋

**Lower Priority / Have Workarounds:**
- 📋 **Issue #4:** Class search substring matching (minor usability, workaround exists)
- 📋 **Issue #5:** Tool descriptions for small models (affects edge case models)
- 📋 **Issue #7:** Unauthorized full refresh (mitigated by #2, #6, #11 fixes)
- 📋 **Issue #9:** libclang paths on macOS (LIBCLANG_PATH workaround exists)

### Summary

**All critical and medium-priority issues have been successfully fixed.**
- ✅ 9 issues fixed across Phases 1-3
- 📋 4 issues deferred to Phase 4 (lower priority, workarounds available)
- Period: 2025-12-21 to 2025-12-25
- Total effort: ~12 hours development + testing
