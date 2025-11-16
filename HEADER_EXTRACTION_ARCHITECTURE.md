# Header Extraction Architecture for compile_commands.json Support

## Overview

This document describes the architecture for extracting C++ symbols from header files when analyzing projects using `compile_commands.json`. The approach leverages libclang's translation unit parsing to extract symbols from both source files and their included project headers in a single pass, using a "first-win" strategy to avoid redundant processing.

## Core Assumptions

### Assumption 1: Consistent Header Analysis (CRITICAL)

**Statement:** For a given version of `compile_commands.json`, analyzing a header file will produce identical results regardless of which source file includes it.

**Rationale:**
- In well-structured C++ projects, headers should provide consistent declarations
- The same compilation flags from `compile_commands.json` ensure consistent preprocessing
- This assumption is safe for the primary use case: answering questions about code structure

**Implications:**
- We can use only the header file path as the deduplication key
- Once a header is processed by any source file, subsequent sources can skip it
- Significant performance improvement for headers included by many sources

**Edge Cases (Documented but Accepted):**
- Headers that behave differently based on which source includes them (via macros or include guards) may not be fully captured
- This is considered poor C++ practice and acceptable to miss for our use case
- If needed in the future, we can add validation mode to detect such cases

### Assumption 2: compile_commands.json Stability

**Statement:** When `compile_commands.json` changes, all header tracking should be reset and headers re-analyzed.

**Rationale:**
- Different compilation flags may change preprocessor state
- Different include paths may resolve headers differently
- Changes to compilation database represent significant project configuration changes

**Implementation:**
- Hash `compile_commands.json` on analyzer startup
- Compare with cached hash
- If mismatch detected, clear all header processing tracking

## Architecture Components

### Component 1: Thread-Safe Header Processing Tracker

A lightweight tracker that coordinates which headers have been processed to prevent redundant work.

**Data Structure:**

```python
class HeaderProcessingTracker:
    """
    Thread-safe tracker using only header path as key.
    Assumes: same compile_commands.json version → same header parsing results
    """

    def __init__(self):
        self._lock = Lock()

        # Track: header_path -> file_hash when it was processed
        # We keep hash to detect when header file changes
        self._processed: Dict[str, str] = {}  # path -> file_hash

        # Headers currently being processed (prevents race conditions)
        self._in_progress: Set[str] = set()
```

**Key Methods:**

1. `try_claim_header(header_path: str, current_file_hash: str) -> bool`
   - **First-Win Logic:** Returns `True` if this caller should process the header
   - Returns `False` if already processed or being processed
   - **Automatic Invalidation:** If header file hash changed, re-processes it
   - Thread-safe via lock

2. `mark_completed(header_path: str, file_hash: str)`
   - Marks header as fully processed
   - Stores file hash for change detection
   - Removes from in-progress set

3. `invalidate_header(header_path: str)`
   - Removes header from tracking (for external invalidation)
   - Next analysis will re-process it

4. `clear_all()`
   - Clears all tracking
   - Used when `compile_commands.json` changes

### Component 2: Compile Commands Version Tracking

Detects when `compile_commands.json` changes and resets header tracking accordingly.

**Implementation:**

```python
class CppAnalyzer:
    def __init__(self, project_path: str):
        # ... existing init ...

        self.header_tracker = HeaderProcessingTracker()

        # Track compile_commands.json version
        self.compile_commands_hash = self._calculate_compile_commands_hash()

        # Restore state from cache or reset if version changed
        self._restore_or_reset_header_tracking()

    def _calculate_compile_commands_hash(self) -> str:
        """Hash of compile_commands.json file"""
        cc_path = os.path.join(self.project_path, "compile_commands.json")
        if os.path.exists(cc_path):
            return hashlib.md5(open(cc_path, 'rb').read()).hexdigest()
        return ""

    def _restore_or_reset_header_tracking(self):
        """
        Restore header tracking from cache, or reset if compile_commands changed
        """
        tracker_cache = os.path.join(self.cache_dir, "header_tracker.json")

        if os.path.exists(tracker_cache):
            with open(tracker_cache) as f:
                data = json.load(f)

            cached_cc_hash = data.get("compile_commands_hash", "")

            if cached_cc_hash == self.compile_commands_hash:
                # Same compile_commands version - restore tracking
                self.header_tracker._processed = data.get("processed_headers", {})
                print(f"Restored {len(self.header_tracker._processed)} processed headers from cache")
            else:
                # compile_commands.json changed - start fresh
                print("compile_commands.json changed - resetting header tracking")
                self.header_tracker.clear_all()

        # Save current state
        self._save_header_tracking()
```

**Cache Structure:**

```json
// cache/header_tracker.json
{
  "compile_commands_hash": "abc123def456...",
  "processed_headers": {
    "/project/include/MyClass.h": "file_hash_1",
    "/project/include/Helper.h": "file_hash_2",
    "/project/src/internal/Util.h": "file_hash_3"
  }
}
```

### Component 3: Enhanced AST Traversal with First-Win Extraction

Modifies the translation unit processing to extract symbols from both source and project headers in a single pass.

**Key Insight:** When libclang parses a source file, it creates a translation unit (TU) containing the complete AST for the source AND all included headers. We traverse this AST once, extracting symbols from:
1. The source file itself (always)
2. Project headers (only if not already processed - first-win)

**Implementation:**

```python
def _index_translation_unit(self, tu, source_file: str) -> Dict:
    """
    Process TU with first-win header extraction.

    Traverses the entire AST, extracting symbols from:
    - Source file: always
    - Project headers: only if not already processed (first-win)
    - System/external headers: never
    """
    processed_files = set()
    skipped_headers = set()
    headers_to_extract = set()

    def should_extract_from_file(file_path: str) -> bool:
        """
        Determine if we should extract symbols from this file.

        Returns:
            True: Extract symbols from this file
            False: Skip symbol extraction (already done or non-project file)
        """
        if file_path == source_file:
            return True  # Always extract from source

        # Cached decision within this TU
        if file_path in headers_to_extract:
            return True
        if file_path in skipped_headers:
            return False

        # Calculate current file hash
        file_hash = self._calculate_file_hash(file_path)

        # Try to claim header (first-win)
        if self.header_tracker.try_claim_header(file_path, file_hash):
            headers_to_extract.add(file_path)
            return True
        else:
            # Another source already processed this header
            skipped_headers.add(file_path)
            return False

    def traverse_cursor(cursor):
        """Recursively traverse AST, extracting symbols from project files"""

        if cursor.location.file:
            file_path = str(cursor.location.file.name)

            # Only process project files (not system headers or external dependencies)
            if self._is_project_file(file_path):
                # Check if we should extract from this file
                if should_extract_from_file(file_path):
                    processed_files.add(file_path)

                    # Extract symbol (expensive operation - only done once per header!)
                    symbol = self._extract_symbol(cursor, file_path)
                    if symbol:
                        self._add_with_dedup(symbol)
                # else: skip extraction (header already processed by another source)

        # Always traverse children (AST may contain cursors from multiple files)
        for child in cursor.get_children():
            traverse_cursor(child)

    # Perform single-pass AST traversal
    traverse_cursor(tu.cursor)

    # Mark all newly processed headers as completed
    for header in headers_to_extract:
        file_hash = self._calculate_file_hash(header)
        self.header_tracker.mark_completed(header, file_hash)

    # Persist tracker state periodically
    self._save_header_tracking()

    return {
        "source_file": source_file,
        "processed": list(processed_files),  # Files we extracted symbols from
        "skipped": list(skipped_headers)     # Headers already processed by others
    }
```

### Component 4: USR-Based Symbol Deduplication

While headers are processed only once via first-win, we still apply USR-based deduplication as a safety mechanism.

**Rationale:**
- Headers may define inline functions, templates, or constants that appear in multiple files
- USR (Unified Symbol Resolution) provides unique identifier for each C++ entity
- Deduplication ensures symbol appears only once in global indexes

**Implementation:**

```python
def _add_with_dedup(self, symbol_info):
    """
    Add symbol to indexes with USR-based deduplication.

    If symbol with same USR already exists, update metadata only.
    Otherwise, add to all indexes.
    """
    usr = symbol_info.usr

    if usr in self.usr_index:
        # Symbol already exists - just update metadata if needed
        existing = self.usr_index[usr]

        # Track which files define this symbol
        if symbol_info.file_path not in existing.get('defined_in_files', []):
            existing.setdefault('defined_in_files', []).append(symbol_info.file_path)

        return False  # Not added (duplicate)
    else:
        # New symbol - add to all indexes
        self._add_to_indexes(symbol_info)
        return True  # Added
```

## Workflow Examples

### Example 1: Initial Project Indexing

**Scenario:** Index a project with:
- `src/main.cpp` includes `include/Common.h`, `include/Utils.h`
- `src/test.cpp` includes `include/Common.h`
- `src/helper.cpp` includes `include/Utils.h`, `include/Internal.h`

**Execution:**

1. **index_file("src/main.cpp")**
   - Parse with libclang → TU contains: main.cpp, Common.h, Utils.h
   - Traverse AST:
     - main.cpp symbols → extract (is source file)
     - Common.h symbols → `try_claim()` → **wins** → extract
     - Utils.h symbols → `try_claim()` → **wins** → extract
   - `mark_completed("Common.h", hash1)`
   - `mark_completed("Utils.h", hash2)`
   - Result: 3 files processed

2. **index_file("src/test.cpp")**
   - Parse with libclang → TU contains: test.cpp, Common.h
   - Traverse AST:
     - test.cpp symbols → extract (is source file)
     - Common.h symbols → `try_claim()` → **loses** (already processed) → **SKIP**
   - No work done for Common.h!
   - Result: 1 file processed, 1 file skipped

3. **index_file("src/helper.cpp")**
   - Parse with libclang → TU contains: helper.cpp, Utils.h, Internal.h
   - Traverse AST:
     - helper.cpp symbols → extract (is source file)
     - Utils.h symbols → `try_claim()` → **loses** → **SKIP**
     - Internal.h symbols → `try_claim()` → **wins** → extract
   - `mark_completed("Internal.h", hash3)`
   - Result: 2 files processed, 1 file skipped

**Performance:**
- Without first-win: 8 file analyses (3 sources + 5 header instances)
- With first-win: 7 file analyses (3 sources + 4 unique headers)
- For headers included by many sources, savings are dramatic

### Example 2: Header File Modification

**Scenario:** User modifies `include/Common.h`

**Execution:**

1. **Refresh detection:** File watcher detects change to Common.h

2. **Next source file that includes Common.h is indexed** (e.g., main.cpp refresh):
   - Calculate new hash for Common.h → `hash1_new`
   - `try_claim_header("Common.h", hash1_new)`
   - Tracker compares: stored hash `hash1` ≠ current hash `hash1_new`
   - Returns `True` → **re-extract symbols**
   - Update tracker: `processed["Common.h"] = hash1_new`

3. **Subsequent sources** (e.g., test.cpp refresh):
   - `try_claim_header("Common.h", hash1_new)`
   - Hash matches → returns `False` → **skip**

**Result:** Modified header re-processed exactly once, then skipped by others.

### Example 3: compile_commands.json Update

**Scenario:** User modifies build configuration, regenerates `compile_commands.json`

**Execution:**

1. **Analyzer restart** (or explicit rebuild):
   - `_calculate_compile_commands_hash()` → `new_hash`
   - Load `header_tracker.json` → cached hash = `old_hash`
   - Compare: `new_hash ≠ old_hash`
   - **Action:** `header_tracker.clear_all()`
   - Log: "compile_commands.json changed - resetting header tracking"

2. **All headers re-indexed:**
   - First source to include each header wins
   - Full re-analysis with new compilation flags
   - New tracker state saved with `new_hash`

## Design Decisions

### Decision 1: No Cross-Source Symbol Validation

**Question:** Should we validate that the same header produces identical symbols when included from different sources?

**Decision:** **NO** - We do not implement cross-source validation.

**Rationale:**
- Adds complexity and performance overhead
- Violates the core assumption that headers are consistent
- If this assumption is violated, it indicates poor C++ practice
- The use case (code questions) tolerates minor inconsistencies

**Documented For Future:**
If validation becomes necessary, we can add an optional `--validate-headers` mode that:
- Extracts symbols from headers in all inclusion contexts
- Compares USR sets
- Warns if differences detected
- Helps identify problematic headers with context-dependent behavior

### Decision 2: No Runtime Monitoring of compile_commands.json

**Question:** Should we watch `compile_commands.json` for changes during analyzer runtime?

**Decision:** **NO** - Only check on analyzer startup.

**Rationale:**
- Changes to `compile_commands.json` during analysis are rare
- Typically happens during build system reconfiguration
- Users can restart analyzer or trigger manual rebuild
- Simplifies implementation

**User Guidance:**
- Document: "If you modify compile_commands.json, restart the analyzer or rebuild the index"
- Consider adding explicit rebuild command: `rebuild_index()`

### Decision 3: Header Path as Sole Identifier

**Question:** Should we include compile args hash in the header tracking key?

**Decision:** **NO** - Use only header file path.

**Rationale:**
- Assumes `compile_commands.json` provides consistent compilation context
- When compile database changes, we reset everything via hash tracking
- Dramatically simplifies tracking and caching
- Enables maximum deduplication efficiency

**Trade-off Accepted:**
- If same header has different compile args in different entries (rare), we use first-encountered context
- Acceptable for code analysis use case

## Cache and Persistence

### Header Tracker Cache

**Location:** `{cache_dir}/header_tracker.json`

**Format:**
```json
{
  "version": "1.0",
  "compile_commands_hash": "abc123...",
  "processed_headers": {
    "/absolute/path/to/Header1.h": "file_hash_1",
    "/absolute/path/to/Header2.h": "file_hash_2"
  }
}
```

**Lifecycle:**
- **Created:** On first analysis run
- **Updated:** After each source file analysis (periodic saves)
- **Invalidated:** When `compile_commands.json` hash changes
- **Restored:** On analyzer startup (if hash matches)

### Per-Source Cache Enhancement

Extend existing per-file cache to track header extraction:

```json
// files/{source_hash}.json
{
  "version": "1.3",
  "file_path": "/project/src/main.cpp",
  "file_hash": "def456...",
  "compile_args_hash": "ghi789...",
  "symbols": [...],

  "headers_extracted": {
    "include/MyClass.h": "hash1",
    "include/Helper.h": "hash2"
  },
  "headers_skipped": [
    "include/Common.h"
  ]
}
```

**Benefits:**
- Helps understand which source "owns" extraction for which headers
- Useful for debugging and diagnostics
- Can optimize cache invalidation

## Performance Characteristics

### Time Complexity

- **Without header extraction:** O(n) where n = number of source files
- **With naive header extraction:** O(n × h) where h = average headers per source
- **With first-win optimization:** O(n + u) where u = number of unique headers
- **Speedup:** For headers included by k sources: k× reduction in processing

### Space Complexity

- **Header tracker memory:** O(u) where u = unique project headers
- **Tracker cache on disk:** Minimal (few KB for typical projects)
- **No increase in symbol storage:** Deduplication ensures each symbol stored once

### Benchmark Estimates

For a project with:
- 1,000 source files
- 500 unique project headers
- Average 10 headers included per source

**Without optimization:**
- Process 1,000 sources + 10,000 header instances = 11,000 file analyses

**With first-win:**
- Process 1,000 sources + 500 unique headers = 1,500 file analyses
- **7.3× reduction in processing**

## Error Handling and Edge Cases

### Edge Case 1: Concurrent Source Analysis

**Scenario:** Multiple threads/processes analyzing different sources simultaneously

**Handling:**
- `try_claim_header()` uses lock for thread-safety
- First thread to claim header wins
- Other threads skip and continue
- **Safe:** No duplicate extraction, no race conditions

### Edge Case 2: Header File Deleted

**Scenario:** Header file removed from project

**Handling:**
- `_calculate_file_hash()` raises error for non-existent file
- Caught by caller, logged as warning
- Header remains in tracker (stale entry)
- **Acceptable:** Will be removed on next `compile_commands.json` change or manual cache clear

### Edge Case 3: Circular Includes

**Scenario:** Header A includes Header B, which includes Header A

**Handling:**
- libclang handles include guards automatically
- AST traversal visits each cursor once
- `try_claim_header()` called once per header
- **Safe:** No infinite loops, no duplicate processing

### Edge Case 4: Header Outside Project Root

**Scenario:** Project header located outside project directory (symlink, submodule)

**Handling:**
- `_is_project_file()` determines project membership
- Current implementation may need enhancement for complex project layouts
- **Action:** Ensure `_is_project_file()` handles absolute paths correctly

## Testing Strategy

### Unit Tests

1. **HeaderProcessingTracker Tests:**
   - Test `try_claim_header()` first-win logic
   - Test hash-based invalidation
   - Test thread-safety with concurrent claims

2. **Compile Commands Hash Tests:**
   - Test hash calculation
   - Test change detection
   - Test tracker reset on hash mismatch

3. **AST Traversal Tests:**
   - Test extraction from source file
   - Test extraction from headers (first-win)
   - Test skipping already-processed headers
   - Test `_is_project_file()` filtering

### Integration Tests

1. **Multi-Source Header Sharing:**
   - Create test project with shared headers
   - Index multiple sources
   - Verify header processed only once
   - Verify symbols present in indexes

2. **Header Modification:**
   - Index project
   - Modify header
   - Re-index source
   - Verify header re-processed
   - Verify updated symbols in indexes

3. **Compile Commands Change:**
   - Index with compile_commands.json v1
   - Modify compile_commands.json
   - Restart analyzer
   - Verify headers re-processed

### Performance Tests

1. **Benchmark header extraction overhead:**
   - Measure time with/without first-win optimization
   - Verify expected speedup ratio

2. **Memory usage:**
   - Monitor header tracker memory growth
   - Verify linear scaling with unique header count

## Future Enhancements

### Optional: Header Dependency Graph

Track which sources include which headers:

```python
class HeaderDependencyTracker:
    def __init__(self):
        self.source_to_headers: Dict[str, Set[str]] = {}
        self.header_to_sources: Dict[str, Set[str]] = {}
```

**Benefits:**
- Smarter cache invalidation (invalidate only affected sources)
- Dependency visualization
- Impact analysis for header changes

**Trade-off:** Additional complexity and memory

### Optional: Validation Mode

Add `--validate-headers` flag to check assumption:

```python
def validate_header_consistency(self, header_path: str):
    """
    Extract header symbols in multiple contexts and compare.
    Warn if differences detected.
    """
    # Extract from multiple sources that include this header
    # Compare USR sets
    # Report differences
```

### Optional: Incremental Update

Optimize re-indexing when single header changes:

- Detect which sources include changed header
- Re-index only those sources
- Skip unaffected sources

**Current approach:** Relies on first-win + lazy re-indexing (sufficient for now)

## Documentation Requirements

### Development Documentation

- **This file:** Comprehensive architecture reference
- **Code comments:** Document first-win logic, assumptions in implementation
- **Decision log:** Record why we chose simplified approach

### User Documentation

- **README section:** Explain header extraction behavior
- **Configuration guide:** How to trigger re-indexing
- **Troubleshooting:** What to do if `compile_commands.json` changes
- **Limitations:** Document the consistency assumption and edge cases

**Key user-facing notes:**
1. "Headers are analyzed in the context of their first including source file"
2. "If you modify compile_commands.json, restart the analyzer to ensure full re-indexing"
3. "For best results, maintain consistent header behavior across translation units"

## Summary

This architecture provides efficient header symbol extraction for `compile_commands.json`-based analysis through:

1. **First-win strategy:** Each header processed only once, massive performance savings
2. **Simplified tracking:** Header path as sole key, compile commands hash for versioning
3. **Safe assumptions:** Documented and acceptable for code analysis use case
4. **Automatic invalidation:** File hash and compile commands changes trigger re-processing
5. **Thread-safe:** Lock-based coordination for concurrent analysis

The approach balances **correctness**, **performance**, and **simplicity**, with clear documentation of trade-offs and future enhancement paths.
