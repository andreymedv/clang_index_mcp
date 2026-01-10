# Concurrent Access Error Fix - Analysis and Implementation Plan

## Problem Description

**Error**: `dictionary changed size during iteration`

**When it occurs**: When calling MCP tools (e.g., `search_symbols`) during active indexing

**Root cause**:
- SearchEngine iterates over shared index dictionaries (`class_index`, `function_index`, `file_index`)
- During indexing, CppAnalyzer modifies these dictionaries in background threads
- Python raises `RuntimeError: dictionary changed size during iteration` when dict is modified during iteration

---

## Current Architecture

### Threading Model
```
Main Thread (MCP Server)
├─ User calls search_symbols()
│  └─ SearchEngine iterates over self.class_index.items()  ❌ NO LOCK
│
└─ Background Thread (IndexingThread)
   └─ Modifies self.class_index with self.index_lock ✅ HAS LOCK
```

**Problem**: SearchEngine reads indexes WITHOUT lock, while indexing thread modifies them WITH lock.

### Root Cause Code Locations

**File**: `mcp_server/search_engine.py`
- **Line 213**: `for name, infos in self.class_index.items():`
- **Line 326**: `for file_path, infos in self.file_index.items():`
- **Line 358**: `for name, infos in self.function_index.items():`
- **Line 443**: `for name, func_infos in self.function_index.items():`

All iterate over dictionaries WITHOUT lock protection.

**File**: `mcp_server/cpp_analyzer.py`
- **Line 238**: `SearchEngine(class_index, function_index, file_index, usr_index)`
  - SearchEngine created WITHOUT passing `index_lock`
- **Line 197**: `self.index_lock = threading.RLock()`
  - Lock exists but not shared with SearchEngine

---

## Solution Design

### Option 1: Pass Lock to SearchEngine (RECOMMENDED)

**Approach**: Share `index_lock` with SearchEngine and wrap all iterations in `with lock:`

**Advantages**:
- ✅ Proper synchronization (no race conditions)
- ✅ Minimal performance impact (lock only during iteration)
- ✅ Clean architecture (SearchEngine knows about thread safety)
- ✅ Consistent with existing code patterns

**Disadvantages**:
- Requires API change (SearchEngine constructor)
- All iterations must use lock (multiple code changes)

**Implementation**:
```python
# cpp_analyzer.py
self.search_engine = SearchEngine(
    self.class_index,
    self.function_index,
    self.file_index,
    self.usr_index,
    index_lock=self.index_lock  # NEW PARAMETER
)

# search_engine.py
class SearchEngine:
    def __init__(self, class_index, function_index, file_index, usr_index, index_lock):
        self.class_index = class_index
        self.function_index = function_index
        self.file_index = file_index
        self.usr_index = usr_index
        self.index_lock = index_lock  # Store lock

    def search_classes(self, ...):
        results = []
        with self.index_lock:  # LOCK DURING ITERATION
            for name, infos in self.class_index.items():
                for info in infos:
                    # ... process results
        return results
```

### Option 2: Snapshot Dictionary Items Before Iteration

**Approach**: Create list copy of dict.items() before iterating

**Advantages**:
- ✅ No API changes
- ✅ Simpler implementation

**Disadvantages**:
- ❌ Creates copy on every query (memory overhead)
- ❌ Snapshot may become stale during iteration
- ❌ Less efficient for large indexes

**Implementation**:
```python
# search_engine.py
def search_classes(self, ...):
    results = []
    # Create snapshot before iteration
    items_snapshot = list(self.class_index.items())  # Copy
    for name, infos in items_snapshot:
        for info in infos:
            # ... process results
    return results
```

**Not recommended** - less efficient and doesn't prevent partial reads.

### Option 3: Return Incomplete Results with Warning

**Approach**: Catch exception and return partial results

**Disadvantages**:
- ❌ Doesn't solve root cause
- ❌ Users get inconsistent results
- ❌ Silent data corruption

**Not recommended**.

---

## Recommended Solution: Option 1

**Pass `index_lock` to SearchEngine and protect all iterations.**

### Implementation Tasks

#### Task 1: Update SearchEngine Constructor
**File**: `mcp_server/search_engine.py`

```python
class SearchEngine:
    def __init__(
        self,
        class_index: Dict[str, List[SymbolInfo]],
        function_index: Dict[str, List[SymbolInfo]],
        file_index: Dict[str, List[SymbolInfo]],
        usr_index: Dict[str, SymbolInfo],
        index_lock: threading.RLock,  # NEW PARAMETER
    ):
        self.class_index = class_index
        self.function_index = function_index
        self.file_index = file_index
        self.usr_index = usr_index
        self.index_lock = index_lock  # Store lock
```

#### Task 2: Update CppAnalyzer to Pass Lock
**File**: `mcp_server/cpp_analyzer.py` (line ~238)

```python
# Initialize search engine
self.search_engine = SearchEngine(
    self.class_index,
    self.function_index,
    self.file_index,
    self.usr_index,
    self.index_lock  # Pass lock
)
```

#### Task 3: Protect search_classes() Iteration
**File**: `mcp_server/search_engine.py` (line ~210-253)

```python
def search_classes(self, pattern, project_only=True, file_name=None):
    results = []

    with self.index_lock:  # ADD LOCK
        # Iterate all classes and use qualified pattern matching
        for name, infos in self.class_index.items():
            for info in infos:
                # ... existing logic
                results.append({...})

    return results
```

#### Task 4: Protect search_functions() Iterations
**File**: `mcp_server/search_engine.py` (lines ~326, ~358)

**Location 1**: File index iteration (line ~326)
```python
if file_name:
    with self.index_lock:  # ADD LOCK
        for file_path, infos in self.file_index.items():
            # ... existing logic
```

**Location 2**: Function index iteration (line ~358)
```python
else:
    with self.index_lock:  # ADD LOCK
        for name, infos in self.function_index.items():
            # ... existing logic
```

#### Task 5: Protect get_class_info() Iteration
**File**: `mcp_server/search_engine.py` (line ~443)

```python
def get_class_info(self, class_name):
    # ... existing code

    methods = []
    with self.index_lock:  # ADD LOCK
        for name, func_infos in self.function_index.items():
            for func_info in func_infos:
                if func_info.parent_class == class_name:
                    methods.append({...})

    return {...}
```

#### Task 6: Protect get_function_signature() Access
**File**: `mcp_server/search_engine.py` (line ~493)

```python
def get_function_signature(self, function_name, class_name=None):
    signatures = []

    with self.index_lock:  # ADD LOCK
        for info in self.function_index.get(function_name, []):
            # ... existing logic

    return signatures
```

---

## Testing Plan

### Test 1: Concurrent Access Test

**Goal**: Verify no RuntimeError during concurrent indexing and queries

```python
def test_concurrent_search_during_indexing():
    """Test that search operations work during active indexing."""
    analyzer = CppAnalyzer(test_project_dir)

    # Start indexing in background thread
    indexing_thread = threading.Thread(target=analyzer.index_project)
    indexing_thread.start()

    # Query repeatedly while indexing
    for _ in range(100):
        results = analyzer.search_classes("")  # Empty pattern = all classes
        # Should not raise RuntimeError
        assert isinstance(results, list)

    indexing_thread.join()
```

### Test 2: Thread Safety Stress Test

**Goal**: Heavy concurrent load test

```python
def test_thread_safety_stress():
    """Stress test with multiple concurrent queries during indexing."""
    analyzer = CppAnalyzer(large_project_dir)

    # Start indexing
    indexing_thread = threading.Thread(target=analyzer.index_project)
    indexing_thread.start()

    # Multiple query threads
    def query_repeatedly():
        for _ in range(50):
            analyzer.search_classes("View")
            analyzer.search_functions("process")
            analyzer.search_symbols("")

    query_threads = [threading.Thread(target=query_repeatedly) for _ in range(10)]
    for t in query_threads:
        t.start()

    for t in query_threads:
        t.join()

    indexing_thread.join()
```

### Test 3: Lock Performance Impact

**Goal**: Verify lock doesn't significantly slow down queries

```python
def test_lock_performance_impact():
    """Verify lock overhead is minimal."""
    analyzer = CppAnalyzer(project_dir)
    analyzer.index_project()  # Complete indexing first

    # Benchmark query performance
    start = time.time()
    for _ in range(1000):
        results = analyzer.search_classes("Config")
    elapsed = time.time() - start

    # Should still be fast (<1ms average)
    avg_time = elapsed / 1000
    assert avg_time < 0.001, f"Query too slow: {avg_time*1000}ms"
```

---

## Implementation Checklist

- [ ] **Task 1**: Update SearchEngine.__init__() to accept index_lock parameter
- [ ] **Task 2**: Update CppAnalyzer to pass index_lock when creating SearchEngine
- [ ] **Task 3**: Wrap search_classes() iteration with lock
- [ ] **Task 4**: Wrap search_functions() iterations (2 locations) with lock
- [ ] **Task 5**: Wrap get_class_info() iteration with lock
- [ ] **Task 6**: Wrap get_function_signature() iteration with lock
- [ ] **Task 7**: Add concurrent access test (test_concurrent_search_during_indexing)
- [ ] **Task 8**: Add thread safety stress test
- [ ] **Task 9**: Add performance impact test
- [ ] **Task 10**: Update documentation about thread safety guarantees
- [ ] **Task 11**: Run full test suite
- [ ] **Task 12**: Manual testing with real project during indexing

---

## Expected Outcomes

### Before Fix
```
User: search_symbols with pattern=""
Server: RuntimeError: dictionary changed size during iteration
Status: ❌ CRASH
```

### After Fix
```
User: search_symbols with pattern=""
Server: Returns partial results (symbols indexed so far)
Status: ✅ SUCCESS (may be incomplete but no crash)
```

### Performance Impact
- **Lock overhead**: ~0.001ms per query (negligible)
- **Query blocking**: User queries block indexing briefly (~1-10ms)
- **Indexing priority**: User queries have higher priority (acceptable trade-off)

---

## Alternative Considerations

### Why Not Use Read-Write Lock?
- Python doesn't have built-in RWLock (would need threading library extension)
- RLock is sufficient for our use case
- Query duration is very short (1-10ms), blocking is acceptable

### Why Not Make Indexes Immutable?
- Would require copying entire index on every modification (expensive)
- Current approach with lock is more efficient

### Why Not Use Queue-Based Architecture?
- Overengineering for this problem
- Lock-based approach is simpler and sufficient

---

## Documentation Updates

### Thread Safety Guarantees (to add to CLAUDE.md)

```markdown
## Thread Safety

**Concurrent Access**: The analyzer is thread-safe for concurrent reads and writes.

- **During Indexing**: User queries are allowed and will not crash
- **Locking Strategy**: Shared RLock protects all index operations
- **Performance**: Query operations may briefly block indexing (1-10ms)
- **Incomplete Results**: Queries during indexing return partial results (symbols indexed so far)

**Recommendations**:
- Use `wait_for_indexing()` if you need complete results
- Check `get_indexing_status()` to know if indexing is active
- Queries during indexing are safe but may return incomplete data
```

---

## Risk Assessment

### Risks
1. **Lock contention**: If many concurrent queries, may slow down indexing
   - **Mitigation**: Queries are fast (1-10ms), minimal impact
2. **Deadlock**: If lock used incorrectly
   - **Mitigation**: Use RLock (reentrant), careful code review
3. **Performance regression**: Lock overhead slows queries
   - **Mitigation**: Benchmark tests to verify <1ms impact

### Benefits
1. ✅ **No crashes**: Users can query during indexing safely
2. ✅ **Better UX**: Queries return partial results instead of errors
3. ✅ **Consistent**: Matches user expectations (priority to user queries)

---

## Timeline

- **Analysis**: ✅ Complete
- **Implementation**: 2-3 hours
- **Testing**: 1-2 hours
- **Documentation**: 1 hour
- **Total**: ~1 day

---

## Related Issues

- **GitHub Issue**: (to be created)
- **Priority**: P1 (user-facing crash)
- **Type**: Bug (race condition)

---

## References

- Python threading documentation: https://docs.python.org/3/library/threading.html#rlock-objects
- Dictionary iteration thread safety: https://docs.python.org/3/faq/library.html#what-kinds-of-global-value-mutation-are-thread-safe
