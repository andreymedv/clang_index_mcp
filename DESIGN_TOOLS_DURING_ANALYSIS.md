# Architectural Design: MCP Tools During Analysis

## Executive Summary

This document provides an architectural design for enabling MCP tools to execute safely and effectively during the C++ project indexing/analysis phase. The current implementation has a race condition that allows tools to execute on incomplete data. This design proposes a comprehensive solution that provides:

1. **Safe concurrent access** to partially-indexed data
2. **Progress visibility** for users and tools
3. **Graceful degradation** with clear feedback about incomplete results
4. **Performance optimization** through incremental indexing

---

## 1. Current State Analysis

### 1.1 Current Behavior

**File:** `mcp_server/cpp_mcp_server.py` (lines 430-438)

```python
# Re-initialize analyzer with new path
global analyzer, analyzer_initialized
analyzer = CppAnalyzer(project_path)
analyzer_initialized = True  # ❌ Set BEFORE indexing starts!

# Start indexing in the background
indexed_count = analyzer.index_project(force=False, include_dependencies=True)  # ⏱️ BLOCKS here

return [TextContent(type="text", text=f"Set project directory to: {project_path}\n...")]
```

**File:** `mcp_server/cpp_analyzer.py` (lines 974-1160)

```python
def index_project(self, force: bool = False, include_dependencies: bool = True) -> int:
    """Index all C++ files in the project"""
    # ... synchronous blocking implementation
    with executor_class(max_workers=self.max_workers) as executor:
        # Submit all files for parallel parsing
        for i, future in enumerate(as_completed(future_to_file)):
            # Wait for each future to complete (BLOCKING)
            result = future.result()
            # ... merge results ...
    return indexed_count  # Only returns when ALL files are indexed
```

### 1.2 Problems Identified

| Problem | Impact | Severity |
|---------|--------|----------|
| **Race Condition** | `analyzer_initialized = True` before indexing completes, allowing tools to execute on partial data | 🔴 High |
| **Misleading Comment** | Code says "Start indexing in the background" but actually blocks | 🟡 Medium |
| **No Progress API** | Tools have no way to check indexing status or progress | 🟡 Medium |
| **No Partial Result Warnings** | Tools return incomplete data without indicating it's partial | 🔴 High |
| **GIL Contention** | If using threads, tool requests compete with indexing for GIL | 🟡 Medium |

### 1.3 Current Flow Diagram

```
Client Request: set_project_directory
         ↓
    Create analyzer
         ↓
analyzer_initialized = True ← Tools become "available"
         ↓
    index_project() starts (BLOCKS)
         ↓
    [While indexing is blocking...]
         ↓
    Concurrent Tool Request → Passes initialization check ✓
         ↓                          ↓
    ... indexing ...         Returns INCOMPLETE results ❌
         ↓
    indexing completes
         ↓
    Return success message
```

---

## 2. Design Goals

### 2.1 Functional Requirements

1. **FR1**: Tools SHALL be able to execute during indexing with clear indication of completeness
2. **FR2**: Tools SHALL return accurate results based on currently-indexed data
3. **FR3**: System SHALL provide progress information (files indexed, completion percentage)
4. **FR4**: System SHALL distinguish between "indexing", "partial", and "complete" states
5. **FR5**: Large projects SHALL support incremental indexing without blocking all operations

### 2.2 Non-Functional Requirements

1. **NFR1**: Indexing performance SHALL NOT degrade by more than 10%
2. **NFR2**: Tool response time SHALL be ≤ 100ms for cached queries
3. **NFR3**: Memory overhead for synchronization SHALL be ≤ 5% of total index size
4. **NFR4**: API SHALL be backward compatible with existing MCP tool interface
5. **NFR5**: Solution SHALL work with both ThreadPoolExecutor and ProcessPoolExecutor

---

## 3. Proposed Architecture

### 3.1 State Machine for Analyzer

Introduce a proper state management system:

```python
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from threading import Lock, Event
from typing import Optional

class AnalyzerState(Enum):
    """Analyzer lifecycle states"""
    UNINITIALIZED = "uninitialized"      # No project set
    INITIALIZING = "initializing"         # Analyzer created, preparing to index
    INDEXING = "indexing"                 # Actively indexing files
    INDEXED = "indexed"                   # Indexing complete, ready for queries
    REFRESHING = "refreshing"             # Incremental refresh in progress
    ERROR = "error"                       # Indexing failed

@dataclass
class IndexingProgress:
    """Real-time indexing progress"""
    total_files: int
    indexed_files: int
    failed_files: int
    cache_hits: int
    current_file: Optional[str]
    start_time: datetime
    estimated_completion: Optional[datetime]

    @property
    def completion_percentage(self) -> float:
        return (self.indexed_files / self.total_files * 100) if self.total_files > 0 else 0.0

    @property
    def is_complete(self) -> bool:
        return self.indexed_files + self.failed_files >= self.total_files

class AnalyzerStateManager:
    """Thread-safe state management for analyzer"""

    def __init__(self):
        self._state = AnalyzerState.UNINITIALIZED
        self._lock = Lock()
        self._indexed_event = Event()  # Signals when indexing completes
        self._progress: Optional[IndexingProgress] = None

    @property
    def state(self) -> AnalyzerState:
        with self._lock:
            return self._state

    def transition_to(self, new_state: AnalyzerState):
        with self._lock:
            old_state = self._state
            self._state = new_state

            if new_state == AnalyzerState.INDEXED:
                self._indexed_event.set()
            elif new_state == AnalyzerState.INDEXING:
                self._indexed_event.clear()

            diagnostics.debug(f"State transition: {old_state.value} -> {new_state.value}")

    def wait_for_indexed(self, timeout: Optional[float] = None) -> bool:
        """Wait until indexing completes (or timeout)"""
        return self._indexed_event.wait(timeout)

    def update_progress(self, progress: IndexingProgress):
        with self._lock:
            self._progress = progress

    def get_progress(self) -> Optional[IndexingProgress]:
        with self._lock:
            return self._progress

    def is_ready_for_queries(self) -> bool:
        """Check if analyzer can handle queries (even partial)"""
        with self._lock:
            return self._state in (AnalyzerState.INDEXING, AnalyzerState.INDEXED, AnalyzerState.REFRESHING)

    def is_fully_indexed(self) -> bool:
        with self._lock:
            return self._state == AnalyzerState.INDEXED
```

### 3.2 Enhanced Query Results with Metadata

Add metadata to all tool responses indicating data completeness:

```python
from typing import TypedDict, Any, List
from enum import Enum

class QueryCompletenessStatus(Enum):
    COMPLETE = "complete"           # Query executed on fully indexed data
    PARTIAL = "partial"             # Query executed during indexing (incomplete)
    STALE = "stale"                 # Query executed on outdated data (needs refresh)

class QueryMetadata(TypedDict):
    """Metadata about query execution context"""
    status: str  # QueryCompletenessStatus value
    indexed_files: int
    total_files: int
    completion_percentage: float
    timestamp: str
    warning: Optional[str]

class EnhancedQueryResult:
    """Wrapper for query results with metadata"""

    def __init__(self, data: Any, metadata: QueryMetadata):
        self.data = data
        self.metadata = metadata

    def to_json(self) -> dict:
        return {
            "data": self.data,
            "metadata": self.metadata
        }

    @staticmethod
    def create_from_state(data: Any, state_manager: AnalyzerStateManager) -> 'EnhancedQueryResult':
        """Create result with current state metadata"""
        progress = state_manager.get_progress()

        if state_manager.is_fully_indexed():
            status = QueryCompletenessStatus.COMPLETE
            warning = None
        else:
            status = QueryCompletenessStatus.PARTIAL
            warning = "Results are incomplete - indexing in progress"

        metadata: QueryMetadata = {
            "status": status.value,
            "indexed_files": progress.indexed_files if progress else 0,
            "total_files": progress.total_files if progress else 0,
            "completion_percentage": progress.completion_percentage if progress else 0.0,
            "timestamp": datetime.now().isoformat(),
            "warning": warning
        }

        return EnhancedQueryResult(data, metadata)
```

### 3.3 Async Background Indexing

Convert blocking indexing to truly asynchronous background task:

```python
import asyncio
from concurrent.futures import Future
from typing import Callable, Optional

class BackgroundIndexer:
    """Manages background indexing with async support"""

    def __init__(self, analyzer: 'CppAnalyzer', state_manager: AnalyzerStateManager):
        self.analyzer = analyzer
        self.state_manager = state_manager
        self._indexing_task: Optional[asyncio.Task] = None

    async def start_indexing(
        self,
        force: bool = False,
        include_dependencies: bool = True,
        progress_callback: Optional[Callable[[IndexingProgress], None]] = None
    ) -> int:
        """Start background indexing (non-blocking)"""

        if self._indexing_task and not self._indexing_task.done():
            raise RuntimeError("Indexing already in progress")

        self.state_manager.transition_to(AnalyzerState.INDEXING)

        # Run synchronous index_project in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()

        try:
            indexed_count = await loop.run_in_executor(
                None,  # Use default executor
                self._index_with_progress,
                force,
                include_dependencies,
                progress_callback
            )

            self.state_manager.transition_to(AnalyzerState.INDEXED)
            return indexed_count

        except Exception as e:
            self.state_manager.transition_to(AnalyzerState.ERROR)
            diagnostics.error(f"Indexing failed: {e}")
            raise

    def _index_with_progress(
        self,
        force: bool,
        include_dependencies: bool,
        progress_callback: Optional[Callable[[IndexingProgress], None]]
    ) -> int:
        """Wrapper that reports progress during indexing"""

        # Monkey-patch the analyzer's progress reporting to update state
        original_index = self.analyzer.index_project

        def wrapped_index(f: bool, i: bool) -> int:
            # This runs in the executor thread
            # We'll use a progress callback that's thread-safe
            return original_index(f, i)

        return wrapped_index(force, include_dependencies)

    def is_indexing(self) -> bool:
        return self._indexing_task is not None and not self._indexing_task.done()

    async def wait_for_completion(self, timeout: Optional[float] = None):
        """Wait for indexing to complete"""
        if self._indexing_task:
            await asyncio.wait_for(self._indexing_task, timeout=timeout)
```

### 3.4 Modified MCP Server Flow

Update `cpp_mcp_server.py` to use new architecture:

```python
# Global state
analyzer: Optional[CppAnalyzer] = None
state_manager = AnalyzerStateManager()
background_indexer: Optional[BackgroundIndexer] = None

@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    global analyzer, state_manager, background_indexer

    try:
        if name == "set_project_directory":
            project_path = arguments["project_path"]

            # Validation...

            # Initialize analyzer
            state_manager.transition_to(AnalyzerState.INITIALIZING)
            analyzer = CppAnalyzer(project_path)
            background_indexer = BackgroundIndexer(analyzer, state_manager)

            # Start indexing in background (truly non-blocking)
            asyncio.create_task(
                background_indexer.start_indexing(
                    force=False,
                    include_dependencies=True
                )
            )

            # Return immediately
            return [TextContent(
                type="text",
                text=f"Set project directory to: {project_path}\n"
                     f"Indexing started in background. Use 'get_indexing_status' to check progress.\n"
                     f"Tools are available but will return partial results until indexing completes."
            )]

        # All other tools - check if ready for queries
        if not state_manager.is_ready_for_queries():
            return [TextContent(
                type="text",
                text="Error: Project directory not set or analyzer in error state. "
                     "Please use 'set_project_directory' first."
            )]

        # Execute tool with metadata
        if name == "search_classes":
            project_only = arguments.get("project_only", True)
            results = analyzer.search_classes(arguments["pattern"], project_only)

            # Wrap with metadata
            enhanced_result = EnhancedQueryResult.create_from_state(results, state_manager)
            return [TextContent(type="text", text=json.dumps(enhanced_result.to_json(), indent=2))]

        # ... similar for other tools ...

        elif name == "get_indexing_status":
            # New tool for checking indexing progress
            progress = state_manager.get_progress()
            status_data = {
                "state": state_manager.state.value,
                "is_fully_indexed": state_manager.is_fully_indexed(),
                "progress": {
                    "total_files": progress.total_files if progress else 0,
                    "indexed_files": progress.indexed_files if progress else 0,
                    "failed_files": progress.failed_files if progress else 0,
                    "completion_percentage": progress.completion_percentage if progress else 0.0,
                    "current_file": progress.current_file if progress else None
                } if progress else None
            }
            return [TextContent(type="text", text=json.dumps(status_data, indent=2))]

        elif name == "wait_for_indexing":
            # New tool to wait for indexing to complete
            timeout = arguments.get("timeout", 60.0)
            completed = state_manager.wait_for_indexed(timeout)

            if completed:
                progress = state_manager.get_progress()
                return [TextContent(
                    type="text",
                    text=f"Indexing complete! Indexed {progress.indexed_files} files."
                )]
            else:
                return [TextContent(
                    type="text",
                    text=f"Timeout waiting for indexing (waited {timeout}s). Use 'get_indexing_status' to check progress."
                )]
```

### 3.5 New MCP Tools

Add two new tools to support the new capabilities:

```python
@server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        # ... existing tools ...

        Tool(
            name="get_indexing_status",
            description="Get real-time status of project indexing. Returns state (uninitialized/indexing/indexed/error), progress (files indexed/total, completion percentage), and whether tools will return complete or partial results. Use this to check if indexing is complete before running queries on large projects.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),

        Tool(
            name="wait_for_indexing",
            description="Block until indexing completes or timeout is reached. Use this when you need complete results and want to wait for indexing to finish. Returns success when indexing completes, or timeout error if it takes too long. Timeout defaults to 60 seconds.",
            inputSchema={
                "type": "object",
                "properties": {
                    "timeout": {
                        "type": "number",
                        "description": "Maximum time to wait in seconds (default: 60.0)",
                        "default": 60.0
                    }
                },
                "required": []
            }
        )
    ]
```

---

## 4. Enhanced CppAnalyzer Integration

### 4.1 Progress Reporting from index_project()

Modify `CppAnalyzer.index_project()` to report progress in real-time:

```python
def index_project(
    self,
    force: bool = False,
    include_dependencies: bool = True,
    progress_callback: Optional[Callable[[IndexingProgress], None]] = None
) -> int:
    """Index all C++ files in the project with progress reporting"""

    start_time = time.time()
    files = self._find_cpp_files(include_dependencies=include_dependencies)

    if not files:
        return 0

    indexed_count = 0
    cache_hits = 0
    failed_count = 0

    # Initialize progress
    progress = IndexingProgress(
        total_files=len(files),
        indexed_files=0,
        failed_files=0,
        cache_hits=0,
        current_file=None,
        start_time=datetime.now(),
        estimated_completion=None
    )

    with executor_class(max_workers=self.max_workers) as executor:
        # ... submit futures ...

        for i, future in enumerate(as_completed(future_to_file)):
            file_path = future_to_file[future]

            # Update current file being processed
            progress.current_file = file_path

            try:
                result = future.result()
                # ... process result ...

                if success:
                    indexed_count += 1
                    progress.indexed_files = indexed_count
                    if was_cached:
                        cache_hits += 1
                        progress.cache_hits = cache_hits
                else:
                    failed_count += 1
                    progress.failed_files = failed_count

                # Calculate ETA
                processed = i + 1
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                eta_seconds = (len(files) - processed) / rate if rate > 0 else 0
                progress.estimated_completion = datetime.now() + timedelta(seconds=eta_seconds)

                # Report progress via callback
                if progress_callback:
                    progress_callback(progress)

            except Exception as exc:
                diagnostics.error(f"Error indexing {file_path}: {exc}")
                failed_count += 1
                progress.failed_files = failed_count

    return indexed_count
```

### 4.2 Thread-Safe Read Operations

Ensure all query methods in `CppAnalyzer` are thread-safe for concurrent access during indexing:

```python
class CppAnalyzer:

    def search_classes(self, pattern: str, project_only: bool = True) -> List[dict]:
        """Thread-safe class search with read lock"""
        with self.index_lock:  # Read lock (current implementation uses single lock)
            # Make a snapshot of the current index
            class_snapshot = {k: list(v) for k, v in self.class_index.items()}

        # Process snapshot outside lock (no lock contention)
        results = []
        regex = re.compile(pattern)

        for class_name, symbols in class_snapshot.items():
            if regex.search(class_name):
                for symbol in symbols:
                    if not project_only or symbol.is_project:
                        results.append(symbol.to_dict())

        return results
```

---

## 5. Alternative Design: Read-Write Locks

For more advanced optimization, use read-write locks to allow concurrent reads:

```python
from threading import Lock, Condition

class ReadWriteLock:
    """Read-write lock allowing multiple readers or single writer"""

    def __init__(self):
        self._readers = 0
        self._writers = 0
        self._read_ready = Condition(Lock())
        self._write_ready = Condition(Lock())

    def acquire_read(self):
        self._read_ready.acquire()
        try:
            while self._writers > 0:
                self._read_ready.wait()
            self._readers += 1
        finally:
            self._read_ready.release()

    def release_read(self):
        self._read_ready.acquire()
        try:
            self._readers -= 1
            if self._readers == 0:
                self._read_ready.notify_all()
        finally:
            self._read_ready.release()

    def acquire_write(self):
        self._write_ready.acquire()
        try:
            while self._writers > 0 or self._readers > 0:
                self._write_ready.wait()
            self._writers += 1
        finally:
            self._write_ready.release()

    def release_write(self):
        self._write_ready.acquire()
        try:
            self._writers -= 1
            self._write_ready.notify_all()
            self._read_ready.acquire()
            self._read_ready.notify_all()
            self._read_ready.release()
        finally:
            self._write_ready.release()

# Usage in CppAnalyzer:
class CppAnalyzer:
    def __init__(self, project_root: str):
        # ... existing init ...
        self.index_lock = ReadWriteLock()  # Replace threading.Lock()

    def search_classes(self, pattern: str, project_only: bool = True) -> List[dict]:
        self.index_lock.acquire_read()
        try:
            # Query logic (multiple queries can run concurrently)
            results = self._search_classes_impl(pattern, project_only)
        finally:
            self.index_lock.release_read()
        return results

    def _merge_symbols_from_file(self, symbols: List[SymbolInfo]):
        self.index_lock.acquire_write()
        try:
            # Modification logic (exclusive access)
            for symbol in symbols:
                self.class_index[symbol.name].append(symbol)
        finally:
            self.index_lock.release_write()
```

---

## 6. Implementation Phases

### Phase 1: Fix Critical Race Condition (Quick Win)
**Estimated effort:** 2 hours

1. Move `analyzer_initialized = True` to AFTER `index_project()` completes
2. Add warning comment about blocking behavior
3. Test that tools cannot execute during indexing

```python
# Quick fix in cpp_mcp_server.py
analyzer = CppAnalyzer(project_path)
# Don't set initialized yet!

indexed_count = analyzer.index_project(force=False, include_dependencies=True)

# Only now mark as initialized
analyzer_initialized = True
```

### Phase 2: Add State Management (1-2 days)
1. Implement `AnalyzerStateManager` class
2. Integrate state transitions into `CppAnalyzer`
3. Update `cpp_mcp_server.py` to use state checks instead of boolean flag
4. Add `get_indexing_status` tool
5. Add unit tests for state machine

### Phase 3: Implement Background Indexing (2-3 days)
1. Implement `BackgroundIndexer` class
2. Convert `index_project()` to support progress callbacks
3. Update MCP server to use async indexing
4. Add `wait_for_indexing` tool
5. Test concurrent tool execution during indexing

### Phase 4: Add Query Metadata (1-2 days)
1. Implement `EnhancedQueryResult` wrapper
2. Update all tool handlers to include metadata
3. Add warning messages for partial results
4. Update tool documentation

### Phase 5: Optimize with Read-Write Locks (Optional, 2-3 days)
1. Implement `ReadWriteLock` class
2. Replace `threading.Lock()` with `ReadWriteLock` in `CppAnalyzer`
3. Update all index access to use read/write locks appropriately
4. Benchmark performance improvement

---

## 7. Testing Strategy

### 7.1 Unit Tests

```python
# test_state_manager.py
def test_state_transitions():
    sm = AnalyzerStateManager()
    assert sm.state == AnalyzerState.UNINITIALIZED

    sm.transition_to(AnalyzerState.INDEXING)
    assert not sm.is_fully_indexed()
    assert sm.is_ready_for_queries()

    sm.transition_to(AnalyzerState.INDEXED)
    assert sm.is_fully_indexed()

def test_wait_for_indexed():
    sm = AnalyzerStateManager()
    sm.transition_to(AnalyzerState.INDEXING)

    # Timeout should occur
    assert not sm.wait_for_indexed(timeout=0.1)

    sm.transition_to(AnalyzerState.INDEXED)
    assert sm.wait_for_indexed(timeout=0.1)
```

### 7.2 Integration Tests

```python
# test_tools_during_indexing.py
async def test_tools_during_indexing():
    """Verify tools can execute during indexing with partial results"""

    # Start indexing (background)
    await set_project_directory("/path/to/large/project")

    # Check status immediately (should be INDEXING)
    status = await get_indexing_status()
    assert status["state"] == "indexing"
    assert status["progress"]["completion_percentage"] < 100

    # Execute query during indexing
    results = await search_classes("MyClass")
    assert results["metadata"]["status"] == "partial"
    assert results["metadata"]["warning"] is not None

    # Wait for completion
    await wait_for_indexing(timeout=300)

    # Query again (should be complete)
    results = await search_classes("MyClass")
    assert results["metadata"]["status"] == "complete"
    assert results["metadata"]["completion_percentage"] == 100
```

### 7.3 Performance Tests

```python
def test_concurrent_query_performance():
    """Benchmark concurrent queries during indexing"""

    analyzer = CppAnalyzer("/large/project")
    state_manager = AnalyzerStateManager()

    # Start indexing in background thread
    indexing_thread = Thread(target=analyzer.index_project)
    indexing_thread.start()

    # Hammer with concurrent queries
    start = time.time()
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(analyzer.search_classes, ".*")
            for _ in range(100)
        ]
        results = [f.result() for f in futures]

    query_time = time.time() - start

    indexing_thread.join()

    # Queries should complete reasonably fast even during indexing
    assert query_time < 10.0, f"Concurrent queries took {query_time}s (too slow)"
```

---

## 8. Migration Plan

### 8.1 Backward Compatibility

The design maintains full backward compatibility:

- Existing tools continue to work without changes
- New `metadata` field is added to responses (non-breaking)
- New tools (`get_indexing_status`, `wait_for_indexing`) are additive
- Clients that don't check metadata still get correct data (just no completeness info)

### 8.2 Client Migration Path

**Old Client Behavior (still works):**
```python
# Client doesn't check metadata
await set_project_directory("/path")
# Wait arbitrarily
await asyncio.sleep(60)
results = await search_classes("MyClass")
# Use results (may be incomplete if waited too short)
```

**New Client Behavior (recommended):**
```python
# Client uses new status API
await set_project_directory("/path")

# Option 1: Wait for completion
await wait_for_indexing(timeout=300)
results = await search_classes("MyClass")

# Option 2: Poll status
while True:
    status = await get_indexing_status()
    if status["is_fully_indexed"]:
        break
    await asyncio.sleep(1)

# Option 3: Use partial results with awareness
results = await search_classes("MyClass")
if results["metadata"]["status"] == "partial":
    print(f"Warning: Results are {results['metadata']['completion_percentage']:.1f}% complete")
```

---

## 9. Performance Analysis

### 9.1 Expected Impact

| Metric | Current | Phase 1 | Phase 3 | Phase 5 |
|--------|---------|---------|---------|---------|
| **Indexing Speed** | Baseline | Same | -5% | -3% |
| **Query Latency (no contention)** | Baseline | Same | Same | Same |
| **Query Latency (during indexing)** | ❌ Undefined | ❌ Blocked | +20% | +5% |
| **Concurrent Query Throughput** | ❌ N/A | ❌ N/A | 10x | 50x |
| **Memory Overhead** | Baseline | +0% | +2% | +5% |

### 9.2 Bottleneck Analysis

**Current Bottleneck:** GIL contention between indexing threads and query execution

**Phase 3 Solution:** Use ProcessPoolExecutor for indexing (bypass GIL) + async queries

**Phase 5 Solution:** Read-write locks allow N concurrent readers (no GIL contention for queries)

---

## 10. Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **Deadlock with read-write locks** | Low | High | Extensive testing, lock ordering documentation |
| **Memory growth with snapshots** | Medium | Medium | Limit snapshot size, use iterators instead |
| **Slower indexing due to progress reporting** | Low | Low | Make callbacks optional, batch updates |
| **Breaking change to existing clients** | Low | High | Maintain backward compatibility, version API |
| **Race condition in progress updates** | Medium | Low | Use atomic operations, lock progress object |

---

## 11. Future Enhancements

### 11.1 Streaming Results

For very large result sets, stream results as indexing progresses:

```python
async def search_classes_stream(pattern: str):
    """Async generator yielding results as they become available"""
    async for result in analyzer.search_classes_streaming(pattern):
        yield result
```

### 11.2 Incremental Indexing UI

Provide real-time feedback in MCP client:

```
Indexing: [████████░░░░░░░░░░░░] 42% (1,234 / 2,890 files)
Current: src/core/engine.cpp
ETA: 2m 15s
```

### 11.3 Priority Indexing

Index files by priority (e.g., project files first, dependencies later):

```python
await set_project_directory("/path", priority_mode="project_first")
# Project files indexed first -> queries return useful results quickly
```

---

## 12. Conclusion

This architectural design provides a comprehensive solution for enabling MCP tools to execute during analysis while maintaining correctness, performance, and backward compatibility. The phased implementation approach allows incremental deployment with immediate value from Phase 1's critical bug fix.

**Key Benefits:**
- ✅ Eliminates race condition and data corruption risk
- ✅ Provides transparency about data completeness
- ✅ Enables true background indexing for better UX
- ✅ Maintains backward compatibility
- ✅ Scales to very large codebases

**Recommended Implementation Order:**
1. **Phase 1** (immediate): Fix race condition
2. **Phase 2** (next sprint): Add state management
3. **Phase 3** (following sprint): Implement background indexing
4. **Phase 4** (continuous): Add metadata to results
5. **Phase 5** (optional): Optimize with read-write locks

---

## Appendix A: API Reference

### New Tool: `get_indexing_status`

**Request:**
```json
{
  "name": "get_indexing_status",
  "arguments": {}
}
```

**Response:**
```json
{
  "state": "indexing",
  "is_fully_indexed": false,
  "progress": {
    "total_files": 2890,
    "indexed_files": 1234,
    "failed_files": 12,
    "completion_percentage": 42.7,
    "current_file": "src/core/engine.cpp"
  }
}
```

### New Tool: `wait_for_indexing`

**Request:**
```json
{
  "name": "wait_for_indexing",
  "arguments": {
    "timeout": 300.0
  }
}
```

**Response (success):**
```json
{
  "status": "complete",
  "message": "Indexing complete! Indexed 2890 files."
}
```

**Response (timeout):**
```json
{
  "status": "timeout",
  "message": "Timeout waiting for indexing (waited 300s). Use 'get_indexing_status' to check progress."
}
```

### Enhanced Query Response Format

**All query tools now return:**
```json
{
  "data": [...],  // Actual query results
  "metadata": {
    "status": "partial",
    "indexed_files": 1234,
    "total_files": 2890,
    "completion_percentage": 42.7,
    "timestamp": "2025-11-17T10:30:45.123456",
    "warning": "Results are incomplete - indexing in progress"
  }
}
```

---

## Appendix B: Code Locations

| Component | File | Lines |
|-----------|------|-------|
| **Current race condition** | `mcp_server/cpp_mcp_server.py` | 430-438 |
| **Blocking index_project** | `mcp_server/cpp_analyzer.py` | 974-1160 |
| **Tool initialization check** | `mcp_server/cpp_mcp_server.py` | 441-442 |
| **Index lock** | `mcp_server/cpp_analyzer.py` | Multiple |
| **Progress reporting** | `mcp_server/cpp_analyzer.py` | 1096-1136 |

