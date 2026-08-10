# Agent Architecture Guide

Read this file before making architectural changes or when you need to understand the high-level design, key decisions, and critical code locations.

## High-Level Component Structure

```
┌────────────────────────────────────────────────┐
│         MCP Client (Claude Desktop, etc.)      │
└───────────────────┬────────────────────────────┘
                    │ MCP Protocol (stdio/http/sse)
┌───────────────────▼────────────────────────────┐
│       cpp_mcp_server.py (10 MCP Tools)         │
│  Entry point, tool definitions, validation     │
└───────────────────┬────────────────────────────┘
                    │
┌───────────────────▼────────────────────────────┐
│            CppAnalyzer (core engine)           │
│  • Project indexing & incremental analysis     │
│  • Symbol extraction & query handling          │
│  • Multi-process parallel parsing              │
│  • compile_commands.json integration           │
└─┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬───┘
  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │
  │  │  │  │  │  │  │  │  │  │  │  │  │  │  └─ ErrorTracking
  │  │  │  │  │  │  │  │  │  │  │  │  │  └──── ProjectIdentity
  │  │  │  │  │  │  │  │  │  │  │  │  └───────── RegexValidator
  │  │  │  │  │  │  │  │  │  │  │  └──────────── ArgumentSanitizer
  │  │  │  │  │  │  │  │  │  │  └─────────────── StateManager
  │  │  │  │  │  │  │  │  │  └────────────────── IncrementalAnalyzer
  │  │  │  │  │  │  │  │  └───────────────────── ChangeScanner
  │  │  │  │  │  │  │  └──────────────────────── CompileCommandsDiffer
  │  │  │  │  │  │  └─────────────────────────── DependencyGraph
  │  │  │  │  │  └────────────────────────────── HeaderTracker
  │  │  │  │  └───────────────────────────────── CompileCommandsManager
  │  │  │  └──────────────────────────────────── SearchEngine
  │  │  └─────────────────────────────────────── CallGraphAnalyzer
  │  └────────────────────────────────────────── CacheManager
  │                                              └─ SQLiteCacheBackend (FTS5)
  └───────────────────────────────────────────── FileScanner
```

Refactored into packages:
- `_mcp/` — MCP server, tool registry, and consolidated tools
- `_indexing/` — indexing orchestration, pipeline, refresh, worker pool
- `_symbols/` — symbol model, extraction, parser port
- `_compilation/` — libclang parsing, compile commands, compilation environment
- `_search/` — query engine, search engine, call graph, hierarchy, dependency graph
- `_persistence/` — SQLite backend, repositories, cache manager, project identity, header tracker
- `_incremental/` — incremental analysis and change scanning
- `_core/` — shared utilities, file scanner, concurrency, cancellation
- `composition_root.py` — dependency wiring
- `cpp_analyzer.py` — thin public facade

## Architecture Hotspots

Most changes will touch one of these areas:

- `clang_index_mcp/_mcp/cpp_mcp_server.py`: MCP server entry point and tool dispatch.
- `clang_index_mcp/_mcp/consolidated_tools.py`: public MCP tool schemas (10 consolidated tools).
- `clang_index_mcp/_mcp/tool_handlers/*.py`: internal tool handlers.
- `clang_index_mcp/cpp_analyzer.py`: thin facade over the analyzer.
- `clang_index_mcp/composition_root.py`: dependency wiring.
- `clang_index_mcp/_indexing/indexing_orchestrator.py`: full-project indexing flow.
- `clang_index_mcp/_indexing/indexing_pipeline.py`: single-file indexing pipeline.
- `clang_index_mcp/_symbols/symbol_extractor.py`: symbol extraction coordination.
- `clang_index_mcp/_compilation/clang_symbol_parser.py`: libclang AST traversal.
- `clang_index_mcp/_search/call_graph.py`, `clang_index_mcp/_search/call_graph_service.py`: SQLite-backed call graph storage and queries.
- `clang_index_mcp/_persistence/sqlite_cache_backend.py`: schema management, SQLite tuning, and persistence behavior.
- `clang_index_mcp/_persistence/schema.sql`: database schema.
- `clang_index_mcp/_incremental/incremental_analyzer.py`: change detection and incremental refresh behavior.
- `clang_index_mcp/_compilation/compile_commands_manager.py`: compile_commands.json loading and lookup.
- `clang_index_mcp/_persistence/header_tracker.py`: header deduplication logic.

Treat the following behaviors as critical unless the task explicitly requires changing them:

- Translation units must be cleaned up promptly to avoid file descriptor leaks.
- SQLite PRAGMAs must be applied on every connection.
- Call graph data should remain SQLite-backed rather than duplicated in memory.
- Incremental analysis and compile_commands invalidation must remain correct.
- Header deduplication and multi-process parsing are major performance features; do not casually regress them.

## Key Architectural Decisions

**1. Multi-Process Parallelism (ProcessPoolExecutor)**
- Bypasses Python's GIL for true parallelism on multi-core systems
- Each worker process gets isolated memory space (no shared state)
- 6-7x speedup on 4+ core systems
- Worker function: `process_file_worker()` (module-level for pickling)
- Uses the `spawn` multiprocessing start method for fork safety

**2. Header Deduplication (First-Win Strategy)**
- When using compile_commands.json, headers included by multiple sources are processed once
- First source file to include a header "claims" it via `HeaderProcessingTracker`
- 5-10x performance improvement for commonly-included headers
- Identity tracked by header path only (not compile args)
- See `clang_index_mcp/_persistence/header_tracker.py`

**3. Incremental Analysis Architecture**
- Tracks file changes via MD5 hashing (content-based, platform-independent)
- Builds dependency graphs to cascade header changes to dependent sources
- Detects compile_commands.json changes and re-analyzes affected files
- Provides 30-300x speedup for partial refreshes
- See `clang_index_mcp/_incremental/incremental_analyzer.py`, `clang_index_mcp/_incremental/change_scanner.py`

**4. Resource Management and File Descriptor Handling**
- **CRITICAL:** TranslationUnit objects are deleted immediately after symbol extraction
- `del tu` + `gc.collect()` forces cleanup of libclang C++ resources (file descriptors)
- Worker processes clean up indexes after each file to prevent memory accumulation
- Singleton analyzer per worker process (not per file) reduces SQLite connections
- File descriptors remain stable at ~10-15 during indexing (tested with 5700+ files)
- **Historical Issue:** self.translation_units dict was removed (write-only, caused 516+ FD leak)
- See `clang_index_mcp/_indexing/indexing_pipeline.py` (`SingleFileIndexingPipeline._finalize_index_success()`) for explicit TU deletion
- See `clang_index_mcp/worker_bootstrap.py` (`process_file_worker()`) for worker cleanup
- See `clang_index_mcp/_persistence/header_tracker.py`

**5. SQLite Cache with FTS5**
- Symbol storage in SQLite with full-text search (2-5ms for 100K symbols)
- WAL mode for concurrent multi-process access
- Automatic VACUUM, OPTIMIZE, and ANALYZE maintenance
- Cache per project configuration: (source_dir, config_file) → unique cache dir
- See `clang_index_mcp/_persistence/sqlite_cache_backend.py`, `clang_index_mcp/_persistence/schema.sql`

**6. Compile Commands Integration**
- Parses compile_commands.json for accurate per-file compilation arguments
- Binary caching (.mcp_cache/<project>/compile_commands/<hash>.cache) for 10-100x faster startup
- Optional orjson for 3-5x faster JSON parsing (pip install .[performance])
- Fallback to hardcoded args if compile_commands.json not found
- See `clang_index_mcp/_compilation/compile_commands_manager.py`

**7. No Runtime Monitoring of compile_commands.json**
- Only checked on analyzer startup (not during runtime)
- Users must restart analyzer after modifying compilation database
- Trade-off: simplicity vs convenience (config changes are rare)

**8. Header Tracking Cache Optimization**
- Header tracking state saved once at end of indexing (not per-file)
- Eliminates race conditions in multi-process mode (was causing ~5000 writes for large projects)
- Cached as header_tracker.json in project cache directory
- Includes compile_commands.json hash for invalidation on config changes
- See `clang_index_mcp/_persistence/header_tracker.py` and `clang_index_mcp/_persistence/cache_orchestrator.py` (`save_header_tracking()`)

**9. libclang Error Recovery**
- Leverages libclang's built-in error recovery for non-fatal parse errors
- Files with syntax/semantic errors continue processing, extract partial symbols from usable AST
- Only TranslationUnitLoadError (no TU created) causes true failure
- Errors logged as warnings, cached with error_message for diagnostics
- Provides 90%+ symbol extraction vs 0% for files with minor issues
- See `clang_index_mcp/_indexing/indexing_pipeline.py` (`SingleFileIndexingPipeline.index_file()`) for error handling

**10. AST Traversal Optimization (System Header Skipping)**
- Early exit from AST traversal when encountering non-project file cursors
- Skips traversing entire AST subtrees of system headers and external dependencies
- Provides 5-7x speedup on large projects (3.5 hours → ~30-60 minutes for 5700 files)
- Safe because: symbol extraction already filtered, dependency discovery uses tu.get_includes() API
- Only traverses AST nodes from project files and files with active call tracking
- See `clang_index_mcp/_compilation/clang_symbol_parser.py` (`ClangSymbolParser._process_cursor()`) for the early-exit optimization

**11. SQLite PRAGMAs:** Applied per-connection in `_set_connection_pragmas()` (WAL, 64MB cache, 256MB mmap). CRITICAL: must be applied to every connection — workers with `skip_schema_recreation=True` bypassed schema init and missed PRAGMAs (>8x perf regression). See `clang_index_mcp/_persistence/sqlite_cache_backend.py` (`SqliteCacheBackend._set_connection_pragmas()`).

**12. Call Graph in SQLite only:** No in-memory call_graph dicts (was ~2 GB RAM). Workers stream call_sites directly to SQLite; find_callers/find_callees query on-demand. See `clang_index_mcp/_search/call_graph.py`.

**13. Template-Mediated Calls:** `std::make_shared<T>()` tracked via template arg type extraction at parse time. `is_template_mediated: True` flag in find_callees results. See `clang_index_mcp/_compilation/clang_symbol_parser.py` (`ClangSymbolParser._extract_template_call_info()`).

## Critical Code Locations

- **MCP Server Entry Point:** `clang_index_mcp/_mcp/cpp_mcp_server.py`
- **Public Tool Schemas:** `clang_index_mcp/_mcp/consolidated_tools.py` (`list_tools_b()`)
- **Internal Tool Handlers:** `clang_index_mcp/_mcp/tool_handlers/*.py`
- **Analyzer Facade:** `clang_index_mcp/cpp_analyzer.py` (`CppAnalyzer`)
- **Dependency Wiring:** `clang_index_mcp/composition_root.py` (`CompositionRoot`)
- **Project Context / DI Container:** `clang_index_mcp/project_context.py` (`ProjectContext`)
- **Full-Project Indexing:** `clang_index_mcp/_indexing/indexing_orchestrator.py` (`ProjectIndexingOrchestrator`)
- **Single-File Indexing Pipeline:** `clang_index_mcp/_indexing/indexing_pipeline.py` (`SingleFileIndexingPipeline`)
- **Worker Pool:** `clang_index_mcp/_indexing/worker_pool.py` (`WorkerPoolManager`, executor lifecycle); worker-side entry point in `clang_index_mcp/worker_bootstrap.py` (`process_file_worker()`)
- **Symbol Extraction Coordination:** `clang_index_mcp/_symbols/symbol_extractor.py` (`SymbolExtractor.index_translation_unit()`)
- **AST Traversal:** `clang_index_mcp/_compilation/clang_symbol_parser.py` (`ClangSymbolParser._process_cursor()`)
- **Type Alias Extraction:** `clang_index_mcp/_symbols/alias_extractor.py` (`extract_alias_info()`)
- **Documentation Extraction:** `clang_index_mcp/_symbols/documentation_extractor.py` (`extract_documentation()`)
- **Virtual Method Indicators:** `clang_index_mcp/_compilation/clang_symbol_parser.py` (method indicator extraction in `_process_cursor()`)
- **Symbol Model:** `clang_index_mcp/_symbols/model/symbol_info.py` (`SymbolInfo`)
- **Symbol Index Store:** `clang_index_mcp/_symbols/symbol_index_store.py` (`SymbolIndexStore`)
- **Call Graph Analysis:** `clang_index_mcp/_search/call_graph.py`, `clang_index_mcp/_search/call_graph_service.py`
- **SQLite Backend:** `clang_index_mcp/_persistence/sqlite_cache_backend.py`
- **Schema:** `clang_index_mcp/_persistence/schema.sql` (v17.0)
- **Header Tracking:** `clang_index_mcp/_persistence/header_tracker.py` (`HeaderProcessingTracker`)
- **Incremental Logic:** `clang_index_mcp/_incremental/incremental_analyzer.py`
- **Compile Commands:** `clang_index_mcp/_compilation/compile_commands_manager.py`
