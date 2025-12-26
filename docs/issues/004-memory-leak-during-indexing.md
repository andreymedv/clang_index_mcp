# [004] Memory Leak During Large Project Indexing

**Category:** Bug
**Priority:** High
**Status:** Proposed
**Date Identified:** 2025-12-26
**Estimated Effort:** 1-2 weeks
**Complexity:** Complex

---

## Problem Statement

During indexing of large C++ projects (~8000+ files), the MCP server exhibits severe memory leak leading to system exhaustion, swap thrashing, and complete unresponsiveness. The main process memory consumption grows to 70-94 GB RSS with worker processes each consuming 1-1.5 GB, ultimately exhausting system memory and swap space.

### Current Behavior

**Symptoms observed during manual testing:**

1. **Memory Growth**:
   - Main process RSS: 71-94 GB
   - Worker processes: 1.0-1.5 GB each (32 workers on 32-core system)
   - RssAnon (anonymous memory): 94 GB+ in main process
   - System AnonPages: 113 GB system-wide

2. **System Thrashing**:
   - Available memory dropped from ~126 GB to ~6 GB
   - Swap usage: 47.4 GB / 61.0 GB (nearly full)
   - Processes in 'D' state (uninterruptible I/O)
   - System completely unresponsive

3. **Server Unresponsiveness**:
   - SSE server stops responding to requests
   - Indexing progress stalls at ~92% (7770/8389 files)
   - Multiple Ctrl-C attempts ignored for >1 minute
   - Server continues indexing even after shutdown signal

4. **Timing**:
   - Occurred during refresh after previous indexing was cancelled
   - ~4282 files from cache (55%), ~3500 files parsed
   - Parsing rate decreased from initial 4-5 files/sec to <3 files/sec

**Test Environment:**
- **System**: Linux, 32 cores, 126 GB RAM, 61 GB swap
- **Project**: Large C++ codebase (~8389 files, dependencies include boost, Qt, vcpkg)
- **Transport**: SSE on port 8080
- **Operation**: Refresh after Ctrl-C interrupt of previous indexing

**Platform-Specific Observation:**
- **Linux**: Memory leak observed (70-94 GB)
- **macOS**: No memory leak observed with same commit and similar testing
- **Implication**: Issue may be Linux-specific or related to platform differences in Python/libclang behavior

### Expected/Desired Behavior

1. **Memory Usage**:
   - Main process should use <10 GB for large projects
   - Worker processes should maintain stable memory (cleared after each batch)
   - No continuous memory growth during indexing
   - Memory released after worker task completion

2. **Responsiveness**:
   - Server remains responsive to health checks during indexing
   - Ctrl-C handled cleanly within 1-2 seconds
   - Progress continues at consistent rate

3. **Resource Management**:
   - Available system memory remains stable
   - No swap usage for normal operations
   - File descriptors remain stable at ~10-15 per process

---

## Technical Analysis

### Memory Profile of Main Process

From `pmap -x` and `/proc/meminfo`:

```
VmRSS:     94 GB     (Resident Set Size)
RssAnon:   94 GB     (Anonymous memory - heap allocations)
VmData:   119 GB     (Data segment size)
VmSwap:    25 GB     (Swapped out memory)

Mapping Type         Size        Notes
=====================================
[anon] mappings    ~110 GB      Python heap, libclang data
symbols.db mmap     262 MB      SQLite database
Worker heaps       ~40 GB       32 workers × ~1.2 GB average
```

### Key Observations

1. **Massive Anonymous Memory**: 94 GB RssAnon indicates heap allocations not being freed
2. **Worker Memory Duplication**: Each of 32 workers consuming 1-1.5 GB (total ~40 GB)
3. **Cache Hit Rate**: 55% cache hits but still parsing 3500+ files
4. **Parse Errors Present**: libclang errors logged but processing continues (expected behavior)

### Hypothesized Root Causes

Based on memory analysis and codebase review:

#### 1. **TranslationUnit/AST Retention in Main Process**
- ASTs or symbol data from worker processes may be accumulating in main process
- Result collection from workers may hold references to large data structures
- ProcessPoolExecutor result queue may not be properly consumed/cleared

#### 2. **Worker Memory Not Cleared Between Tasks**
- Workers parse multiple files without proper cleanup between tasks
- No `maxtasksperchild` limit set on ProcessPoolExecutor
- Python heap fragmentation in long-lived workers

#### 3. **Incomplete Result Consumption**
- Main process may be accumulating all results before processing
- Result queue growing unbounded during parallel execution
- Symbols/metadata duplicated between workers and main process

#### 4. **SQLite Cache Write Buffering**
- Large batch of symbols buffered before write
- In-memory symbol accumulation before cache flush
- WAL mode may buffer changes extensively

#### 5. **Fork-on-Write Memory Duplication**
- ProcessPoolExecutor using 'fork' method duplicates copy-on-write pages
- Modified data in workers (even temporary) duplicates memory
- libclang internal structures modified after fork

---

## Impact Assessment

**User Impact:**
- **Critical on Linux**: Large projects (>5000 files) become unusable
- **System Impact**: Can crash/freeze entire system due to OOM
- **Data Risk**: Interrupted indexing may corrupt cache
- **Accessibility**: Blocks usage on enterprise codebases
- **Platform Specificity**: Linux users severely impacted, macOS users unaffected

**Development Impact:**
- **Testing**: Cannot test with realistic large projects
- **Validation**: Performance testing requires frequent system reboots
- **CI/CD**: Cannot run in resource-constrained environments

**Business Impact:**
- **Adoption Barrier**: Enterprise users cannot use tool
- **Reputation**: "Memory hog" perception
- **Scalability Ceiling**: Hard limit on project size

---

## Diagnostic Data Points

### Process States
```
Main process:  'D' state (uninterruptible I/O)
Worker count:  32 processes (matching CPU count)
Worker state:  Mix of 'S' (sleeping) and 'R' (running)
```

### Memory Growth Pattern
```
Progress: 7770/8389 files (92%)
- Success: 7584 files
- Failed:  186 files
- Cache:   4282 files (55%)
- Rate:    2.9-4.5 files/sec (degrading)
```

### Sample Log Output (sanitized)
```
Progress: 7770/8389 files (92%) - Success: 7584 - Failed: 186 - Cache: 4282 (55%)
[WARNING] /path/to/project/Module/SourceFile.cpp: Continuing despite 3 error(s):
libclang parsing errors (3 total):
[error] /path/to/project/Module/Header.h:18:1: unknown type name 'MACRO_NAME'
```

**Note**: Parse errors are expected behavior (libclang error recovery) and not the cause of memory leak.

---

## Proposed Solutions

### Option 1: Add maxtasksperchild to ProcessPoolExecutor (Quick Fix)

**Concept**: Limit worker lifetime to prevent memory accumulation

**Implementation**:
```python
# In cpp_analyzer.py ProcessPoolExecutor creation
executor = ProcessPoolExecutor(
    max_workers=num_workers,
    maxtasksperchild=1  # Respawn worker after each file
)
```

**Pros:**
- Simple one-line change
- Forces memory cleanup after each task
- Proven pattern for long-running workers

**Cons:**
- Process spawn overhead
- May slow down indexing
- Treats symptom, not root cause

**Estimated Effort:** 1 day
**Risk Level:** Low

---

### Option 2: Implement Chunked Result Processing

**Concept**: Process results in batches instead of accumulating all

**Implementation**:
1. Modify `index_all_files()` to process results incrementally
2. Write symbols to cache after each batch (e.g., 100 files)
3. Clear result queue regularly
4. Add explicit GC calls between batches

**Pros:**
- Reduces main process memory footprint
- More responsive during indexing
- Allows progress persistence

**Cons:**
- More complex implementation
- Need to handle partial cache writes
- SQLite transaction overhead

**Estimated Effort:** 3-5 days
**Risk Level:** Medium

---

### Option 3: Profile and Fix Specific Memory Leak

**Concept**: Use memory profiler to identify exact leak source

**Implementation**:
1. Add `memory_profiler` instrumentation to worker functions
2. Use `tracemalloc` to track allocations
3. Identify specific data structures not being freed
4. Add explicit cleanup code

**Diagnostic Tools**:
```bash
# Memory profiling during indexing
python -m memory_profiler scripts/test_mcp_console.py

# Allocation tracking
python -X tracemalloc=5 -m mcp_server.cpp_mcp_server
```

**Pros:**
- Fixes root cause
- Proper long-term solution
- Educational for future issues

**Cons:**
- Time-consuming investigation
- May reveal multiple leak sources
- Requires profiling with large projects

**Estimated Effort:** 5-10 days
**Risk Level:** Medium

---

### Option 4: Use multiprocessing.shared_memory for Indexes

**Concept**: Avoid memory duplication by using shared memory

**Implementation**:
1. Create shared memory segments for symbol indexes
2. Workers write directly to shared memory
3. Main process reads from shared memory
4. Eliminates result queue accumulation

**Pros:**
- Dramatically reduces memory duplication
- Faster inter-process communication
- Scalable to very large projects

**Cons:**
- Significant architecture change
- Synchronization complexity
- Python 3.8+ required

**Estimated Effort:** 2 weeks
**Risk Level:** High

---

### Option 5: Hybrid Approach (Recommended)

**Concept**: Combine quick fixes with proper investigation

**Phase 1** (Immediate - 1-2 days):
- Add `maxtasksperchild=10` (moderate respawning)
- Add explicit `gc.collect()` in worker cleanup
- Reduce batch size for result processing

**Phase 2** (Short-term - 1 week):
- Add memory profiling instrumentation
- Identify specific leak sources
- Implement targeted fixes

**Phase 3** (Long-term - 2 weeks):
- Implement chunked result processing
- Add memory monitoring/alerts
- Optimize worker memory usage

**Pros:**
- Provides immediate relief
- Enables proper root cause analysis
- Incremental improvement
- Low risk at each phase

**Cons:**
- Requires multiple iterations
- May not fully solve issue in Phase 1

**Total Estimated Effort:** 2-3 weeks
**Risk Level:** Low (phased approach)

---

## Recommended Approach

### Primary Recommendation: **Option 5 (Hybrid Approach)**

**Rationale:**
1. Quick relief for users experiencing issue (Phase 1)
2. Proper investigation to find root cause (Phase 2)
3. Sustainable long-term fix (Phase 3)
4. De-risked through phased implementation
5. Each phase delivers value independently

### Implementation Strategy

**Phase 1: Immediate Mitigation** (Days 1-2)
- Add `maxtasksperchild=10` to ProcessPoolExecutor
- Add `gc.collect()` after batch processing
- Monitor memory with smaller batch sizes
- **Success Criteria**: Memory stays under 30 GB for large projects

**Phase 2: Root Cause Investigation** (Days 3-7)
- Set up `memory_profiler` on worker functions
- Add `tracemalloc` to main process
- Test with large project under profiling
- Identify top 3 memory allocation sources
- **Success Criteria**: Clear identification of leak location(s)

**Phase 3: Targeted Fixes** (Days 8-14)
- Implement fixes based on Phase 2 findings
- Add chunked result processing if needed
- Implement memory monitoring/alerts
- Add regression tests with memory limits
- **Success Criteria**:
  - Memory stays under 15 GB for 8000-file projects
  - No memory growth over time
  - Clean Ctrl-C handling

**Phase 4: Validation** (Days 15-21)
- Test with multiple large projects
- Long-running indexing tests (20K+ files)
- Memory leak regression tests
- Update documentation

---

## Code Investigation Targets

Based on existing architecture documentation:

### Critical Files to Investigate

1. **mcp_server/cpp_analyzer.py**:
   - Line 72-131: `_process_file_worker()` - Worker cleanup
   - Line 1648: TranslationUnit cleanup (already has `del tu` + `gc.collect()`)
   - Worker singleton pattern - potential accumulation
   - Result collection in `index_all_files()`

2. **Worker Process Pattern**:
   ```python
   # Current pattern (check if results accumulate)
   with ProcessPoolExecutor() as executor:
       results = list(executor.map(process_file, files))  # Accumulates ALL results
   ```

3. **Symbol Collection**:
   - Check if symbols are duplicated between workers and main process
   - SQLite write buffering strategy
   - Cache write frequency

### Questions to Answer Through Profiling

1. Is memory growing in main process or workers?
2. Are worker processes properly releasing memory between tasks?
3. Is the result queue accumulating unbounded?
4. Are symbols duplicated in multiple data structures?
5. Is SQLite buffering symbols in memory before write?
6. **Why does this occur on Linux but not macOS?**
   - Python memory allocator differences (pymalloc vs system malloc)
   - libclang implementation differences between platforms
   - Linux fork() copy-on-write behavior vs macOS
   - Platform-specific ProcessPoolExecutor behavior

---

## Testing Requirements

### Memory Leak Tests

**Linux (Primary Target):**

1. **Baseline Test**:
   - Index 1000-file project, measure peak memory
   - Expected: <5 GB main process

2. **Large Project Test**:
   - Index 8000-file project, monitor memory growth
   - Expected: <15 GB main process, stable over time

3. **Repeated Refresh Test**:
   - Run 5 consecutive refreshes
   - Memory should not grow between runs

4. **Interrupt Recovery Test**:
   - Ctrl-C during indexing
   - Memory should be released within 5 seconds

**Cross-Platform Comparison:**

5. **Linux vs macOS Memory Profile**:
   - Run identical test on both platforms
   - Compare memory consumption patterns
   - Identify platform-specific differences

### Performance Regression Tests

- Indexing speed should not decrease by >20%
- Cache hit rate should remain stable
- First-time indexing time acceptable

---

## Decision Log

**2025-12-26**: Initial identification from manual testing (Linux)
- **Observation**: Memory leak causing system thrashing on 8000-file project (Linux only)
- **Platform**: Issue observed on Linux, NOT observed on macOS with same commit
- **Impact**: Critical on Linux - blocks large project usage
- **Decision**: Create issue document, prioritize investigation with focus on Linux-specific behavior
- **Next Steps**:
  1. Reproduce with memory profiling enabled on Linux
  2. Compare memory behavior between Linux and macOS
  3. Implement Phase 1 quick fixes
  4. Investigate platform-specific memory management differences

---

## References

**Related Documentation:**
- [CLAUDE.md](../../CLAUDE.md) - Architecture, resource management section
- [docs/CLAUDE_TESTING_GUIDE.md](../CLAUDE_TESTING_GUIDE.md) - Testing methodology
- [docs/MANUAL_TEST_OBSERVATIONS.md](../MANUAL_TEST_OBSERVATIONS.md) - Issue tracking

**Code References:**
- `mcp_server/cpp_analyzer.py:72-131` - Worker function and cleanup
- `mcp_server/cpp_analyzer.py:1648` - TranslationUnit deletion
- `mcp_server/cpp_analyzer.py:index_all_files()` - Result collection
- `mcp_server/sqlite_cache_backend.py` - Cache write operations

**External Resources:**
- [Python multiprocessing memory management](https://docs.python.org/3/library/multiprocessing.html#programming-guidelines)
- [libclang memory management](https://clang.llvm.org/doxygen/group__CINDEX__TRANSLATION__UNIT.html)
- [SQLite WAL mode](https://www.sqlite.org/wal.html)

**Related Issues:**
- Issue #3: File descriptor leak (FIXED) - similar resource management issue
- Issue #15 / docs/issues/005: Status reports zero files before refresh - observed in same testing session, may be related to state initialization

---

## Next Steps

1. **Immediate** (This week):
   - Reproduce issue with memory profiling enabled
   - Implement Phase 1 quick fixes
   - Test with large project

2. **Short-term** (Next 1-2 weeks):
   - Memory profiling investigation
   - Identify root cause(s)
   - Implement targeted fixes

3. **Long-term** (Next month):
   - Add memory regression tests to CI
   - Document memory usage expectations
   - Add memory monitoring to server

**Trigger Conditions** (when to escalate):
- Issue reproduces consistently
- Quick fixes don't reduce memory usage by 50%+
- Root cause investigation blocked

**Owner**: TBD (requires memory profiling expertise)
