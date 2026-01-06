# Memory Analysis Phase 3: Worker Process Memory Consumption

**Date:** 2025-12-31
**Project:** LargeProject (8389 files, 49.8 MB compile_commands.json)
**System:** 32-core CPU, ProcessPoolExecutor with 32 workers

---

## Executive Summary

**CRITICAL FINDING:** Each worker process consumes **~1.1-1.4 GB** of memory, resulting in **~40 GB total memory** usage during indexing with 32 workers.

This is the dominant memory hotspot and should be the primary focus of Phase 3 optimization.

---

## Memory Measurements

### Process-Level Memory Usage

| Component | Memory Usage | Notes |
|-----------|--------------|-------|
| Main process | ~457 MB | Coordinator, receives symbols from workers |
| Each worker | 1.1-1.4 GB | 32 workers on 32-core system |
| **TOTAL** | **~38-40 GB** | Verified via htop system-wide usage |

**Note:** Total system memory usage during test was ~38 GB (htop), confirming the measurements. Some shared memory pages between workers may reduce effective usage slightly, but the per-process RSS indicates each worker truly allocates ~1.2 GB.

### Memory Timeline (First 3 minutes)

| Time | RSS (Main) | Peak | Phase |
|------|------------|------|-------|
| 0s | 24 MB | 172 MB | Initial |
| 10s | 179 MB | 345 MB | Parsing compile_commands.json |
| 60s | 258 MB | 395 MB | Loading cache |
| 120s | 339 MB | 469 MB | Creating workers |
| 191s | 448 MB | 579 MB | Workers initialized |

After workers are fully initialized, each consumes 1+ GB.

---

## Root Cause Analysis

### Why Each Worker Uses 1+ GB

Each worker process creates a full `CppAnalyzer` instance that includes:

1. **CompileCommandsManager** (~150-300 MB per worker)
   - Parses 49.8 MB compile_commands.json
   - Stores 8389 command entries in memory
   - Creates `file_to_command_map` dictionary
   - With 32 workers: **32 × 200 MB = 6.4 GB** wasted on duplicates

2. **libclang Index** (~100-200 MB per worker)
   - Each worker calls `Index.create()`
   - Holds translation unit metadata
   - Persistent across file processing

3. **SQLite CacheManager** (~50-100 MB per worker)
   - Opens database connection
   - Maintains WAL and shared memory
   - Schema metadata

4. **Header Tracker & Dependency Graph** (~50 MB per worker)
   - Header processing state
   - Dependency graph structures

5. **Temporary symbol data during parsing** (~500-700 MB per worker)
   - TranslationUnit AST
   - Symbol extraction buffers
   - Call graph analysis data

### Code Location

Worker initialization: `mcp_server/cpp_analyzer.py:96-98`

```python
if _worker_analyzer is None:
    _worker_analyzer = CppAnalyzer(project_root, config_file, skip_schema_recreation=True)
```

CppAnalyzer.__init__ creates:
- `CompileCommandsManager` (line 282-284)
- `Index.create()` (line 207)
- `CacheManager` (line 256-258)
- `HeaderProcessingTracker` (line 287)
- `DependencyGraphBuilder` (line 294-298)

---

## Optimization Recommendations

### Priority 1: Shared CompileCommands (Estimated Savings: ~6 GB)

**Problem:** Each of 32 workers parses and stores the same compile_commands.json.

**Solution:** Share compile commands data between workers via shared memory or IPC.

**Options:**

1. **Manager-based sharing** (Recommended)
   - Use `multiprocessing.Manager` to share `file_to_command_map` dict
   - Main process parses once, workers access shared dict
   - Implementation: ~50 lines of code change

   ```python
   # In main process before spawning workers:
   manager = multiprocessing.Manager()
   shared_commands = manager.dict(compile_commands_manager.file_to_command_map)

   # Pass to workers via args
   ```

2. **Memory-mapped file**
   - Serialize commands to mmap file
   - Workers load from shared memory
   - More complex but lower overhead

3. **Reduce worker count**
   - Use `max_workers = cpu_count // 2` for large projects
   - Trade-off: slower indexing but 50% less memory

### Priority 2: Lazy Command Loading (Estimated Savings: ~3 GB)

**Problem:** Workers load ALL 8389 compile commands even though each only processes a few files.

**Solution:** Workers request compile args for specific files on-demand from main process.

**Implementation:**
- Main process maintains command lookup service
- Workers request args via queue/pipe for each file
- Higher IPC overhead but significant memory savings

### Priority 3: Limit Worker Count for Large Projects (Estimated Savings: ~20 GB)

**Problem:** 32 workers × 1.2 GB = 38.4 GB is excessive.

**Solution:** Dynamic worker count based on available memory.

```python
def calculate_max_workers(self, available_memory_gb):
    """Calculate optimal worker count based on memory."""
    memory_per_worker_gb = 1.2  # Empirical measurement
    memory_for_main_gb = 0.5
    safe_workers = int((available_memory_gb - memory_for_main_gb) / memory_per_worker_gb)
    return max(4, min(safe_workers, os.cpu_count() or 8))
```

For 16 GB RAM: `(16 - 0.5) / 1.2 = 12 workers` max

### Priority 4: Reduce libclang Index Memory

**Problem:** Each worker creates its own libclang Index.

**Solution:** Investigate if Index can be shared or if workers can use a lighter initialization.

**Research needed:**
- Can `Index` be serialized/pickled?
- Can workers reuse main process Index via shared memory?
- What's the minimum Index configuration for parsing?

### Priority 5: Stream Processing Instead of Batch

**Problem:** Workers extract all symbols at once, causing memory spikes.

**Solution:** Stream symbols back to main process incrementally.

---

## Quick Win: Reduce Default Worker Count

Add to `cpp_analyzer.py`:

```python
# In __init__ or index_project:
if compile_commands_count > 5000:  # Large project
    self.max_workers = min(self.max_workers, 8)
    diagnostics.info(f"Large project detected ({compile_commands_count} files), limiting workers to {self.max_workers}")
```

This provides immediate relief without architectural changes.

---

## Implementation Roadmap

### Phase 3a: Quick Wins (1-2 hours)

1. Add configurable `max_workers` limit in config file
2. Add memory-based worker count calculation
3. Log worker memory usage for monitoring

### Phase 3b: Shared CompileCommands (4-8 hours)

1. Create `SharedCompileCommandsManager` class
2. Use `multiprocessing.Manager` for sharing
3. Update worker initialization
4. Test with large projects

### Phase 3c: Lazy Loading (1-2 days)

1. Implement command request queue
2. Add IPC between main and workers
3. Benchmark IPC overhead
4. Fallback for small projects (keep current behavior)

---

## Testing Recommendations

1. **Memory monitoring during indexing:**
   ```bash
   watch -n 2 'ps aux | grep python | grep -v grep | awk "{sum+=\$6} END {print sum/1024\" MB\"}"'
   ```

2. **Per-worker memory tracking:**
   ```bash
   ps aux | grep python | grep memory_profile | awk '{print $2, $6/1024 " MB"}'
   ```

3. **Benchmark with different worker counts:**
   ```bash
   for workers in 4 8 16 32; do
       CPP_ANALYZER_MAX_WORKERS=$workers python scripts/archived/memory_profile_indexing.py
   done
   ```

---

## References

- Current memory optimization plan: `docs/MEMORY_OPTIMIZATION_PLAN.md`
- Phase 1 (completed): Task 2.1 + 2.2 (lazy call_sites, SQLite streaming)
- Phase 2 (completed): Task 1.2 (remove calls/called_by from SymbolInfo)
- Worker function: `mcp_server/cpp_analyzer.py:73-170`
- CppAnalyzer init: `mcp_server/cpp_analyzer.py:180-330`
