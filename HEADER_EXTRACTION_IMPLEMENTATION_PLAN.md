# Header Extraction Implementation Plan

This document provides a detailed, step-by-step implementation plan for the header extraction feature described in `HEADER_EXTRACTION_ARCHITECTURE.md`.

## Implementation Phases

### Phase 0: Requirements Documentation Update

**Objective:** Update all requirements and specification documents to reflect the header extraction feature and architectural decisions.

#### Task 0.1: Update REQUIREMENTS.md
- [ ] Add new section: "Header Extraction from compile_commands.json"
- [ ] Document feature requirements:
  - [ ] FR-HE-01: Extract C++ symbols from project headers included by source files
  - [ ] FR-HE-02: Use first-win strategy to avoid redundant header processing
  - [ ] FR-HE-03: Track compile_commands.json version and reset on changes
  - [ ] FR-HE-04: Support nested includes (headers including headers)
  - [ ] FR-HE-05: Filter out system headers and external dependencies
  - [ ] FR-HE-06: Persist header tracking state across analyzer restarts
  - [ ] FR-HE-07: Invalidate and re-process headers when file content changes
  - [ ] FR-HE-08: Thread-safe header processing for concurrent source analysis

- [ ] Document non-functional requirements:
  - [ ] NFR-HE-01: Performance improvement of 5-10× for projects with shared headers
  - [ ] NFR-HE-02: Thread-safe concurrent processing
  - [ ] NFR-HE-03: Cache persistence across restarts
  - [ ] NFR-HE-04: Backward compatibility with existing caches

- [ ] Document assumptions:
  - [ ] ASSUMPTION-HE-01: Headers produce consistent symbols across different sources with same compile_commands.json
  - [ ] ASSUMPTION-HE-02: compile_commands.json changes require full header re-analysis
  - [ ] ASSUMPTION-HE-03: Header path is sufficient identifier (no per-compile-args tracking)

- [ ] Document constraints and limitations:
  - [ ] CONSTRAINT-HE-01: Headers with macro-dependent behavior may not be fully captured
  - [ ] CONSTRAINT-HE-02: No cross-source validation of header consistency
  - [ ] CONSTRAINT-HE-03: No runtime monitoring of compile_commands.json changes

**Dependencies:** None

**Testing:** None (documentation only)

---

#### Task 0.2: Update COMPILE_COMMANDS_INTEGRATION.md
- [ ] Add section: "Header File Analysis"
- [ ] Document how headers are discovered:
  - [ ] libclang automatically parses all included headers in translation unit
  - [ ] AST traversal extracts symbols from both source and project headers
  - [ ] System headers and external dependencies are filtered out

- [ ] Document first-win strategy:
  - [ ] First source file to include a header extracts its symbols
  - [ ] Subsequent sources skip extraction for that header
  - [ ] Deduplication based on header file path
  - [ ] Performance benefits for shared headers

- [ ] Document compile_commands.json versioning:
  - [ ] Hash of compile_commands.json tracked in cache
  - [ ] Changes to compilation database trigger full header re-analysis
  - [ ] User action required: restart analyzer after modifying compile_commands.json

- [ ] Document header change detection:
  - [ ] File hash tracking for each processed header
  - [ ] Automatic re-processing when header content changes
  - [ ] Invalidation on next source file analysis

- [ ] Add usage examples:
  - [ ] Example 1: Project with shared headers (Common.h included by multiple sources)
  - [ ] Example 2: Nested includes (Header A includes Header B)
  - [ ] Example 3: Header modification workflow

**Dependencies:** Task 0.1 (for consistency)

**Testing:** None (documentation only)

---

#### Task 0.3: Update DEVELOPMENT.md
- [ ] Add section: "Header Extraction Architecture"
- [ ] Document key architectural decisions:
  - [ ] Decision: Use first-win strategy instead of re-extraction
  - [ ] Decision: Track by header path only, not by compile args
  - [ ] Decision: No cross-source validation (document rationale)
  - [ ] Decision: No runtime monitoring of compile_commands.json
  - [ ] Decision: Reset all tracking on compile_commands.json change

- [ ] Document design patterns used:
  - [ ] Thread-safe tracker with Lock-based coordination
  - [ ] Closure-based filtering (should_extract_from_file callback)
  - [ ] USR-based symbol deduplication
  - [ ] Hash-based change detection (both files and config)

- [ ] Document future enhancement opportunities:
  - [ ] Optional: Cross-source validation mode
  - [ ] Optional: Header dependency graph tracking
  - [ ] Optional: Runtime compile_commands.json monitoring
  - [ ] Optional: Per-compile-args header tracking (for edge cases)

- [ ] Add reference to `HEADER_EXTRACTION_ARCHITECTURE.md` for full details

**Dependencies:** Task 0.1, Task 0.2 (for consistency)

**Testing:** None (documentation only)

---

#### Task 0.4: Update README.md (User-Facing Summary)
- [ ] Add brief mention of header extraction feature in main features list
- [ ] Add note in compile_commands.json section:
  - [ ] "Automatically analyzes headers included by source files"
  - [ ] "Optimized to process each header only once, even if included by multiple sources"
  - [ ] "Restart analyzer after modifying compile_commands.json for best results"

- [ ] Add FAQ entry (if FAQ section exists):
  - [ ] Q: "Are header files analyzed?"
  - [ ] A: "Yes, project headers are automatically analyzed when included by source files..."

**Dependencies:** Task 0.1, Task 0.2 (for consistency)

**Testing:** None (documentation only)

---

### Phase 1: Core Infrastructure Setup

**Objective:** Implement the foundational components for header tracking and compile_commands.json versioning.

#### Task 1.1: Create HeaderProcessingTracker Class
- [ ] Create new file `mcp_server/header_tracker.py`
- [ ] Implement `HeaderProcessingTracker` class with:
  - [ ] `__init__()` method with Lock, `_processed` dict, `_in_progress` set
  - [ ] `try_claim_header(header_path, current_file_hash)` method
    - [ ] Check if header already processed with same hash → return False
    - [ ] Check if file hash changed → remove old entry, continue
    - [ ] Check if currently in progress → return False
    - [ ] Claim header by adding to `_in_progress` → return True
    - [ ] All operations protected by lock
  - [ ] `mark_completed(header_path, file_hash)` method
    - [ ] Remove from `_in_progress`
    - [ ] Add to `_processed` with hash
    - [ ] Protected by lock
  - [ ] `invalidate_header(header_path)` method
    - [ ] Remove from both `_processed` and `_in_progress`
    - [ ] Protected by lock
  - [ ] `clear_all()` method
    - [ ] Clear both `_processed` and `_in_progress`
    - [ ] Protected by lock
  - [ ] `is_processed(header_path, file_hash)` method (for queries)
  - [ ] `get_processed_count()` method (for diagnostics)

**Dependencies:** None

**Testing:**
- [ ] Unit test: Basic claim/complete cycle
- [ ] Unit test: Hash-based invalidation (file changed)
- [ ] Unit test: Concurrent claim attempts (thread safety)
- [ ] Unit test: clear_all() functionality

---

#### Task 1.2: Add Compile Commands Hash Tracking to CppAnalyzer
- [ ] In `mcp_server/cpp_analyzer.py`, add to `__init__()`:
  - [ ] Import `HeaderProcessingTracker` from `header_tracker`
  - [ ] Initialize `self.header_tracker = HeaderProcessingTracker()`
  - [ ] Add `self.compile_commands_hash = ""`
  - [ ] Call new method `self._calculate_compile_commands_hash()`
  - [ ] Call new method `self._restore_or_reset_header_tracking()`

- [ ] Implement `_calculate_compile_commands_hash()` method:
  - [ ] Get compile_commands.json path from `self.config` or project root
  - [ ] If file exists, calculate MD5 hash of file contents
  - [ ] Return hash string (or empty string if file doesn't exist)
  - [ ] Handle file read errors gracefully

**Dependencies:** Task 1.1

**Testing:**
- [ ] Unit test: Hash calculation for existing compile_commands.json
- [ ] Unit test: Empty hash when file doesn't exist
- [ ] Unit test: Same file produces same hash
- [ ] Unit test: Modified file produces different hash

---

#### Task 1.3: Implement Header Tracker Persistence
- [ ] In `mcp_server/cpp_analyzer.py`, implement `_save_header_tracking()` method:
  - [ ] Create `header_tracker.json` path in cache directory
  - [ ] Acquire lock on `self.header_tracker`
  - [ ] Build data dict with:
    - [ ] `"version": "1.0"`
    - [ ] `"compile_commands_hash": self.compile_commands_hash`
    - [ ] `"processed_headers": dict(self.header_tracker._processed)`
    - [ ] `"timestamp": time.time()`
  - [ ] Write JSON to file with error handling
  - [ ] Log save success/failure

- [ ] Implement `_restore_or_reset_header_tracking()` method:
  - [ ] Check if `header_tracker.json` exists
  - [ ] If exists:
    - [ ] Load JSON data
    - [ ] Compare cached `compile_commands_hash` with current
    - [ ] If match: restore `_processed` dict, log "Restored N headers"
    - [ ] If mismatch: call `header_tracker.clear_all()`, log "compile_commands.json changed - resetting"
  - [ ] If doesn't exist: start fresh (no-op)
  - [ ] Call `_save_header_tracking()` to persist initial state

**Dependencies:** Task 1.2

**Testing:**
- [ ] Unit test: Save and restore with matching hash
- [ ] Unit test: Reset when hash changes
- [ ] Unit test: Graceful handling when cache file doesn't exist
- [ ] Unit test: Graceful handling of corrupted cache file

---

### Phase 2: AST Traversal Modifications

**Objective:** Modify the cursor processing logic to extract symbols from project headers using first-win strategy.

#### Task 2.1: Implement _is_project_file() Helper
- [ ] In `mcp_server/cpp_analyzer.py`, implement `_is_project_file(file_path)` method:
  - [ ] Convert file_path to absolute Path
  - [ ] Check if file is under `self.project_root`
  - [ ] Exclude files in `self.config.get_exclude_directories()`
  - [ ] Exclude files in `self.config.get_dependency_directories()` (unless config allows)
  - [ ] Return True if file is a project file, False otherwise
  - [ ] Add caching to avoid repeated path checks (optional optimization)

**Dependencies:** None (can be done in parallel with Phase 1)

**Testing:**
- [ ] Unit test: Files under project root return True
- [ ] Unit test: System headers return False
- [ ] Unit test: Excluded directories return False
- [ ] Unit test: Dependency directories return False (when not included)

---

#### Task 2.2: Add _calculate_file_hash() Helper
- [ ] In `mcp_server/cpp_analyzer.py`, implement `_calculate_file_hash(file_path)` method:
  - [ ] Use existing `CacheManager.get_file_hash()` or implement locally
  - [ ] Calculate MD5 hash of file contents
  - [ ] Cache results in `self.file_hashes` if not already present
  - [ ] Return hash string

**Dependencies:** None

**Testing:**
- [ ] Unit test: Calculate hash for existing file
- [ ] Unit test: Same file produces same hash
- [ ] Unit test: Modified file produces different hash
- [ ] Unit test: Non-existent file handling

---

#### Task 2.3: Refactor _process_cursor to Support Multi-File Extraction
- [ ] Modify `_process_cursor()` method signature to remove `file_filter` parameter (breaking change, handle carefully)
- [ ] Add new parameter: `should_extract_from_file: Callable[[str], bool]`
- [ ] Update cursor processing logic:
  - [ ] When `cursor.location.file` exists:
    - [ ] Get `file_path = str(cursor.location.file.name)`
    - [ ] Call `should_extract_from_file(file_path)` to check if we should extract
    - [ ] If False, continue to recurse but skip symbol extraction
    - [ ] If True, proceed with symbol extraction as before
  - [ ] Ensure all symbol extraction wraps the file path correctly
  - [ ] Update recursive calls to pass same `should_extract_from_file` callback

**Dependencies:** Task 2.1, Task 2.2

**Testing:**
- [ ] Unit test: Extract from source file when callback returns True
- [ ] Unit test: Skip header when callback returns False
- [ ] Unit test: Recurse into children regardless of callback result

---

#### Task 2.4: Implement _index_translation_unit() Method
- [ ] In `mcp_server/cpp_analyzer.py`, create new method `_index_translation_unit(tu, source_file)`:
  - [ ] Initialize tracking sets:
    - [ ] `processed_files = set()`
    - [ ] `skipped_headers = set()`
    - [ ] `headers_to_extract = set()`

  - [ ] Implement `should_extract_from_file(file_path)` closure:
    - [ ] If `file_path == source_file`: return True
    - [ ] If `file_path in headers_to_extract`: return True (cached decision)
    - [ ] If `file_path in skipped_headers`: return False (cached decision)
    - [ ] If not `_is_project_file(file_path)`: add to skipped, return False
    - [ ] Calculate `file_hash = _calculate_file_hash(file_path)`
    - [ ] Call `self.header_tracker.try_claim_header(file_path, file_hash)`:
      - [ ] If True: add to `headers_to_extract`, return True
      - [ ] If False: add to `skipped_headers`, return False

  - [ ] Call `self._process_cursor(tu.cursor, should_extract_from_file=should_extract_from_file)`

  - [ ] After traversal, mark completed headers:
    - [ ] For each header in `headers_to_extract`:
      - [ ] Get `file_hash = _calculate_file_hash(header)`
      - [ ] Call `self.header_tracker.mark_completed(header, file_hash)`

  - [ ] Call `self._save_header_tracking()` to persist state

  - [ ] Return dict with:
    - [ ] `"source_file": source_file`
    - [ ] `"processed": list(processed_files)`
    - [ ] `"skipped": list(skipped_headers)`

**Dependencies:** Task 2.3

**Testing:**
- [ ] Integration test: Source file always processed
- [ ] Integration test: First source to include header extracts it
- [ ] Integration test: Second source skips already-processed header
- [ ] Integration test: Project headers extracted, system headers skipped

---

#### Task 2.5: Modify index_file() to Use _index_translation_unit()
- [ ] In `index_file()` method, locate where `_process_cursor()` is called
- [ ] Replace the call with `result = self._index_translation_unit(tu, file_path)`
- [ ] Update logging/diagnostics to include:
  - [ ] Number of files processed (source + new headers)
  - [ ] Number of headers skipped (already processed)
- [ ] Ensure return values remain compatible with existing code
- [ ] Update any dependent code that expects old behavior

**Dependencies:** Task 2.4

**Testing:**
- [ ] Integration test: Single source file indexed correctly
- [ ] Integration test: Multiple sources sharing headers
- [ ] Integration test: Verify cache hit/miss behavior
- [ ] Regression test: Ensure existing functionality still works

---

### Phase 3: Symbol Deduplication Enhancements

**Objective:** Ensure USR-based deduplication handles multi-file symbol extraction correctly.

#### Task 3.1: Review and Update _add_symbol() Logic
- [ ] Locate where symbols are added to indexes (likely in `_process_cursor`)
- [ ] Verify USR is being calculated for all symbols
- [ ] Ensure symbols are checked against `self.usr_index` before adding
- [ ] If symbol USR already exists:
  - [ ] Optionally update metadata (e.g., add to `defined_in_files` list)
  - [ ] Skip adding to other indexes
- [ ] If symbol USR is new:
  - [ ] Add to `self.usr_index`
  - [ ] Add to `self.class_index` or `self.function_index` as appropriate
  - [ ] Add to `self.file_index`

**Dependencies:** Phase 2 completion

**Testing:**
- [ ] Unit test: Same symbol (by USR) from two files only added once
- [ ] Unit test: Different symbols added separately
- [ ] Unit test: Symbol metadata updated on duplicate

---

#### Task 3.2: Track Symbol Sources (Optional Enhancement)
- [ ] In `SymbolInfo` dataclass, add optional field:
  - [ ] `defined_in_files: List[str] = field(default_factory=list)`
- [ ] When adding symbol to `usr_index`:
  - [ ] Initialize `defined_in_files` with current file
- [ ] When encountering duplicate USR:
  - [ ] Append current file to `defined_in_files` if not already present
- [ ] Update `SymbolInfo.to_dict()` and `from_dict()` to handle new field

**Dependencies:** Task 3.1

**Testing:**
- [ ] Unit test: Single-file symbol has one entry in defined_in_files
- [ ] Unit test: Multi-file symbol (header) has multiple entries
- [ ] Unit test: Serialization/deserialization preserves defined_in_files

---

### Phase 4: Cache Structure Updates

**Objective:** Extend caching to track header extraction metadata for better diagnostics and invalidation.

#### Task 4.1: Extend Per-File Cache Format
- [ ] In `CacheManager.save_cache()` or per-file cache logic, add fields:
  - [ ] `"headers_extracted": {header_path: file_hash, ...}`
  - [ ] `"headers_skipped": [header_path, ...]`
- [ ] Update version string to indicate new format (e.g., "1.4")
- [ ] Ensure backward compatibility: old caches without these fields still load

- [ ] When caching a source file's results:
  - [ ] Store which headers were extracted (from `processed_files`)
  - [ ] Store which headers were skipped (from `skipped_headers`)

**Dependencies:** Task 2.4 (needs processed/skipped info)

**Testing:**
- [ ] Unit test: New cache format saves correctly
- [ ] Unit test: Old cache format loads without errors
- [ ] Integration test: Cache reload preserves header metadata

---

#### Task 4.2: Implement Cache Invalidation for Header Changes
- [ ] In file refresh logic (when a file changes), check:
  - [ ] If changed file is a header (not a source):
    - [ ] Call `self.header_tracker.invalidate_header(header_path)`
    - [ ] Log: "Header {header_path} changed, will be re-indexed"
  - [ ] If changed file is a source:
    - [ ] Normal invalidation logic (already exists)

**Dependencies:** Task 4.1

**Testing:**
- [ ] Integration test: Modify header file, verify re-indexing on next source analysis
- [ ] Integration test: Modify source file, verify normal re-indexing

---

### Phase 5: Testing

**Objective:** Comprehensive testing of the entire header extraction feature.

#### Task 5.1: Unit Tests for HeaderProcessingTracker
- [ ] Create `tests/test_header_tracker.py`
- [ ] Test basic claim/complete workflow
- [ ] Test first-win semantics (second claim fails)
- [ ] Test hash-based invalidation (file change detection)
- [ ] Test thread safety with concurrent claims
- [ ] Test clear_all() resets state
- [ ] Test is_processed() queries

**Dependencies:** Task 1.1

---

#### Task 5.2: Unit Tests for Compile Commands Versioning
- [ ] Add to existing test file or create new
- [ ] Test `_calculate_compile_commands_hash()`:
  - [ ] Hash calculation
  - [ ] Consistency (same file → same hash)
  - [ ] Change detection (modified file → different hash)
- [ ] Test `_restore_or_reset_header_tracking()`:
  - [ ] Restore when hash matches
  - [ ] Reset when hash changes
  - [ ] Graceful handling of missing/corrupted cache

**Dependencies:** Task 1.2, Task 1.3

---

#### Task 5.3: Integration Tests for Header Extraction
- [ ] Create test project with:
  - [ ] `main.cpp` including `Common.h`, `Utils.h`
  - [ ] `test.cpp` including `Common.h`
  - [ ] `helper.cpp` including `Utils.h`, `Internal.h`
  - [ ] Header files with simple classes/functions

- [ ] Test scenarios:
  - [ ] Index all three source files
  - [ ] Verify `Common.h` extracted only once (first-win)
  - [ ] Verify `Utils.h` extracted only once
  - [ ] Verify `Internal.h` extracted once
  - [ ] Verify symbols from all headers present in indexes
  - [ ] Verify USR deduplication (no duplicate symbols)
  - [ ] Modify `Common.h`, re-index, verify re-extraction
  - [ ] Restart analyzer, verify state restored from cache

**Dependencies:** Phase 2, Phase 3 completion

---

#### Task 5.4: Performance Benchmarking
- [ ] Create benchmark script:
  - [ ] Test project with many sources including common headers
  - [ ] Measure time without header extraction (baseline)
  - [ ] Measure time with header extraction but no first-win optimization
  - [ ] Measure time with full first-win optimization
  - [ ] Calculate and report speedup ratio

- [ ] Test with realistic scenarios:
  - [ ] 100 sources, 20 common headers
  - [ ] 1000 sources, 100 common headers
  - [ ] Verify expected performance improvements (5-10× for common headers)

**Dependencies:** All core functionality complete

---

#### Task 5.5: Thread Safety Tests
- [ ] Create test with concurrent indexing:
  - [ ] Multiple threads index different sources simultaneously
  - [ ] Sources share common headers
  - [ ] Verify no race conditions
  - [ ] Verify each header extracted exactly once
  - [ ] Verify no deadlocks or crashes

**Dependencies:** All core functionality complete

---

### Phase 6: Documentation and Polish

**Objective:** Update documentation, add code comments, and polish the implementation.

#### Task 6.1: Add Code Comments and Docstrings
- [ ] Add comprehensive docstring to `HeaderProcessingTracker` class
- [ ] Document the first-win assumption in class docstring
- [ ] Add docstrings to all new methods:
  - [ ] `_calculate_compile_commands_hash()`
  - [ ] `_restore_or_reset_header_tracking()`
  - [ ] `_save_header_tracking()`
  - [ ] `_is_project_file()`
  - [ ] `_calculate_file_hash()`
  - [ ] `_index_translation_unit()`
- [ ] Add inline comments explaining:
  - [ ] First-win logic in `should_extract_from_file()`
  - [ ] Hash-based invalidation in `try_claim_header()`
  - [ ] Why we reset on compile_commands.json change

**Dependencies:** All implementation complete

---

#### Task 6.2: Update User Documentation
- [ ] Update `README.md`:
  - [ ] Add section on header extraction feature
  - [ ] Explain automatic header analysis
  - [ ] Document performance benefits
  - [ ] Note about restarting after compile_commands.json changes

- [ ] Update `COMPILE_COMMANDS_INTEGRATION.md` (if exists):
  - [ ] Document header extraction behavior
  - [ ] Explain first-win strategy
  - [ ] Provide usage examples

- [ ] Create or update troubleshooting guide:
  - [ ] What to do if headers not being analyzed
  - [ ] How to force re-analysis (delete cache or modify compile_commands.json)
  - [ ] Performance tuning tips

**Dependencies:** Implementation complete

---

#### Task 6.3: Add Logging and Diagnostics
- [ ] Add INFO-level logging for:
  - [ ] "Restored N processed headers from cache"
  - [ ] "compile_commands.json changed - resetting header tracking"
  - [ ] "Indexed {source_file}: processed {N} files, skipped {M} headers"

- [ ] Add DEBUG-level logging for:
  - [ ] Each header claim attempt and result
  - [ ] Hash calculations
  - [ ] Cache save/restore operations

- [ ] Add diagnostic command or method:
  - [ ] `get_header_tracking_stats()` returning:
    - [ ] Number of headers tracked
    - [ ] List of processed headers with hashes
    - [ ] compile_commands.json hash

**Dependencies:** Implementation complete

---

#### Task 6.4: Add Configuration Options (Optional)
- [ ] In `cpp-analyzer-config.json`, add optional settings:
  - [ ] `"enable_header_extraction": true/false` (default: true)
  - [ ] `"validate_header_consistency": true/false` (default: false, for future use)
  - [ ] `"max_header_depth": N` (limit nested include depth, optional)

- [ ] Update `CppAnalyzerConfig` to support new options
- [ ] Document configuration options in `CONFIGURATION.md`

**Dependencies:** Implementation complete

---

### Phase 7: Integration and Final Testing

**Objective:** Ensure the feature integrates smoothly with existing functionality.

#### Task 7.1: Regression Testing
- [ ] Run full existing test suite
- [ ] Verify no regressions in:
  - [ ] Basic source file indexing
  - [ ] Class discovery
  - [ ] Function discovery
  - [ ] Symbol search
  - [ ] Cache hit/miss behavior
  - [ ] File refresh logic

**Dependencies:** All implementation and testing complete

---

#### Task 7.2: End-to-End Testing with Real Projects
- [ ] Test with small real project (e.g., example in repo)
- [ ] Test with medium-sized project (if available)
- [ ] Verify:
  - [ ] Headers are extracted
  - [ ] Symbols from headers are queryable
  - [ ] Performance is improved (faster subsequent indexing)
  - [ ] Cache persistence works across restarts

**Dependencies:** All implementation complete

---

#### Task 7.3: Manual Testing Scenarios
- [ ] Scenario 1: Fresh project indexing
  - [ ] Start with empty cache
  - [ ] Index project with compile_commands.json
  - [ ] Verify headers extracted
  - [ ] Check logs for "processed" vs "skipped" headers

- [ ] Scenario 2: Incremental updates
  - [ ] Modify a header file
  - [ ] Re-index (via refresh or manual)
  - [ ] Verify header re-extracted and symbols updated

- [ ] Scenario 3: compile_commands.json change
  - [ ] Modify compile_commands.json (add flag, change include path)
  - [ ] Restart analyzer
  - [ ] Verify header tracking reset
  - [ ] Verify full re-indexing occurs

- [ ] Scenario 4: Multi-threaded indexing
  - [ ] Index large project with parallel workers
  - [ ] Verify no crashes, deadlocks, or errors
  - [ ] Verify headers extracted exactly once

**Dependencies:** All implementation complete

---

## Implementation Order and Dependencies

### Phase 0 (Requirements Documentation)
**Must be done first:** Update all requirement docs before implementation starts.

### Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4
**Critical path:** Each code phase depends on the previous one.

### Phase 5 (Testing)
**Can start during Phase 2:** Write unit tests as you implement each component.

### Phase 6 (Code Documentation)
**Can be done in parallel with later phases:** Start documenting as you implement.

### Phase 7 (Final Testing)
**Must be done last:** After all implementation is complete.

## Estimated Effort

| Phase | Estimated Time | Complexity |
|-------|----------------|------------|
| Phase 0: Requirements Docs | 2-3 hours | Low |
| Phase 1: Core Infrastructure | 4-6 hours | Medium |
| Phase 2: AST Traversal | 6-8 hours | High |
| Phase 3: Deduplication | 2-3 hours | Low |
| Phase 4: Cache Updates | 3-4 hours | Medium |
| Phase 5: Testing | 8-10 hours | High |
| Phase 6: Code Documentation | 3-4 hours | Low |
| Phase 7: Final Testing | 4-6 hours | Medium |
| **Total** | **32-44 hours** | **Medium-High** |

## Risk Assessment

### High-Risk Items
1. **Thread Safety:** Concurrent access to header tracker must be bulletproof
   - Mitigation: Extensive thread safety tests, careful lock usage

2. **Performance Regression:** Poor implementation could slow down indexing
   - Mitigation: Performance benchmarks, profiling, optimization

3. **Cache Corruption:** Bugs could corrupt cache and break existing projects
   - Mitigation: Cache versioning, backward compatibility, validation

### Medium-Risk Items
1. **Breaking Changes:** Modifying `_process_cursor` signature could break things
   - Mitigation: Careful refactoring, comprehensive regression tests

2. **Edge Cases:** Symlinks, circular includes, unusual project structures
   - Mitigation: Edge case testing, graceful error handling

## Success Criteria

- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Regression tests show no failures
- [ ] Performance tests show expected speedup (5-10× for common headers)
- [ ] Thread safety tests pass without errors
- [ ] Documentation is complete and accurate
- [ ] Manual testing scenarios all succeed
- [ ] Code review completed and approved

## Notes

- **Incremental Implementation:** Each task should be committed separately for easier review and debugging
- **Test-Driven Development:** Write tests before or alongside implementation
- **Backward Compatibility:** Ensure old caches and configurations continue to work
- **Code Review:** Each phase should be reviewed before moving to the next
- **User Testing:** Get feedback from real users during Phase 7

## Open Questions for Review

1. Should we implement Task 3.2 (tracking symbol sources in `defined_in_files`)? Or defer to future?
2. Should we add configuration options in Task 6.4, or keep it simple initially?
3. What level of logging is appropriate? (INFO, DEBUG, or both?)
4. Should we create a separate diagnostic/stats tool for header tracking?
5. Do we need to handle any special cases for precompiled headers (PCH)?
