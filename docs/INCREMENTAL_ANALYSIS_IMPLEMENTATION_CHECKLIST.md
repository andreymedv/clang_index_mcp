# Incremental Analysis Implementation Checklist

**Project**: C++ MCP Server - Incremental Analysis
**Started**: 2025-11-18
**Status**: In Progress

## Legend
- [ ] Not Started
- [x] Completed
- [~] In Progress
- [!] Blocked/Issue

---

## Phase 1: Foundation (Project Identity + Database Schema)

### 1.1 Project Identity System
- [x] Create `mcp_server/project_identity.py`
- [x] Implement `ProjectIdentity` class with hash computation
- [x] Add unit tests for `ProjectIdentity` in `tests/test_project_identity.py`
- [x] Run tests and verify all pass (21 tests, all passed)
- [x] Update `cache_manager.py` to accept ProjectIdentity
- [x] Add backward compatibility for old cache paths
- [x] Update `cpp_analyzer.py` constructor to use ProjectIdentity
- [x] Test cache directory creation with new identity system
- [x] Commit Phase 1.1 changes

### 1.2 Database Schema Updates
- [x] Add `file_dependencies` table to `schema.sql`
- [x] Create schema migration in `schema_migrations.py`
- [x] Test migration on fresh database (5 tests, all passed)
- [x] Test migration on existing database (backward compatibility)
- [x] Run regression tests on existing functionality (37 tests, all passed)
- [x] Commit Phase 1.2 changes

### 1.3 Documentation & Testing
- [ ] Update `REQUIREMENTS.md` with incremental analysis requirements
- [ ] Update `CONFIGURATION.md` with new config_file parameter
- [ ] Add Phase 1 integration tests
- [ ] Run full test suite and fix any regressions
- [ ] Update `README.md` with incremental analysis overview
- [ ] Commit Phase 1 documentation

---

## Phase 2: Dependency Tracking

### 2.1 Dependency Graph Builder
- [x] Create `mcp_server/dependency_graph.py`
- [x] Implement `DependencyGraphBuilder` class
- [x] Implement `extract_includes_from_tu()` method
- [x] Implement `update_dependencies()` method
- [x] Implement `find_dependents()` method
- [x] Implement `find_transitive_dependents()` method with recursive CTE
- [x] Add unit tests for DependencyGraphBuilder in `tests/test_dependency_graph.py`
- [x] Test with simple include chains (A→B, B→C)
- [x] Test with circular includes (A→B, B→A)
- [x] Run tests and verify all pass (15 tests, all passed)
- [x] Commit Phase 2.1 changes

### 2.2 Integration with Parsing Pipeline
- [x] Modify `cpp_analyzer.py` to instantiate DependencyGraphBuilder
- [x] Update `_index_translation_unit()` to extract includes
- [x] Update `_index_translation_unit()` to call `update_dependencies()`
- [x] Test dependency extraction on real codebase
- [x] Verify database contains correct dependency records
- [x] Add integration test for dependency tracking during parse
- [x] Run regression tests (41 tests, all passed)
- [x] Commit Phase 2.2 changes

### 2.3 Documentation & Testing
- [ ] Create `DEPENDENCY_TRACKING_ARCHITECTURE.md`
- [ ] Update `REQUIREMENTS.md` with dependency tracking details
- [ ] Add performance benchmarks for dependency queries
- [ ] Run full test suite
- [ ] Commit Phase 2 documentation

---

## Phase 3: Change Detection

### 3.1 Change Scanner
- [ ] Create `mcp_server/change_scanner.py`
- [ ] Implement `ChangeType` enum
- [ ] Implement `ChangeSet` class
- [ ] Implement `ChangeScanner` class
- [ ] Implement `scan_for_changes()` method
- [ ] Implement `_check_file_change()` method
- [ ] Implement `_check_compile_commands()` method
- [ ] Add unit tests in `tests/test_change_scanner.py`
- [ ] Test file addition detection
- [ ] Test file modification detection
- [ ] Test file deletion detection
- [ ] Test header change detection
- [ ] Run tests and verify all pass
- [ ] Commit Phase 3.1 changes

### 3.2 Compile Commands Differ
- [ ] Create `mcp_server/compile_commands_differ.py`
- [ ] Implement `CompileCommandsDiffer` class
- [ ] Implement `compute_diff()` method
- [ ] Implement `store_current_commands()` method
- [ ] Implement `_hash_args()` method
- [ ] Add unit tests in `tests/test_compile_commands_differ.py`
- [ ] Test diff with added files
- [ ] Test diff with removed files
- [ ] Test diff with changed arguments
- [ ] Test diff with no changes
- [ ] Run tests and verify all pass
- [ ] Commit Phase 3.2 changes

### 3.3 Documentation & Testing
- [ ] Update `COMPILE_COMMANDS_INTEGRATION.md` with diff logic
- [ ] Add integration tests for change detection
- [ ] Test change detection on real project
- [ ] Run full test suite
- [ ] Commit Phase 3 documentation

---

## Phase 4: Incremental Analysis Logic

### 4.1 Incremental Analyzer Core
- [ ] Create `mcp_server/incremental_analyzer.py`
- [ ] Implement `AnalysisResult` class
- [ ] Implement `IncrementalAnalyzer` class
- [ ] Implement `perform_incremental_analysis()` method
- [ ] Add unit tests in `tests/test_incremental_analyzer.py`
- [ ] Commit Phase 4.1 changes

### 4.2 Re-analysis Methods
- [ ] Add `_reanalyze_files()` method to CppAnalyzer
- [ ] Add `handle_header_change()` method to CppAnalyzer
- [ ] Add `handle_source_change()` method to CppAnalyzer
- [ ] Add `handle_compile_commands_change()` method to CppAnalyzer
- [ ] Add `_remove_file_from_cache()` method to CppAnalyzer
- [ ] Test header change cascade (modify header, verify dependents re-analyzed)
- [ ] Test source change isolation (modify source, verify only it re-analyzed)
- [ ] Test compile_commands diff (modify one entry, verify only it re-analyzed)
- [ ] Add integration tests
- [ ] Run tests and verify all pass
- [ ] Commit Phase 4.2 changes

### 4.3 Documentation & Testing
- [ ] Create `INCREMENTAL_ANALYSIS_USAGE.md` user guide
- [ ] Add end-to-end integration tests
- [ ] Test on large codebase (100+ files)
- [ ] Measure performance improvements
- [ ] Document performance benchmarks
- [ ] Run full regression suite
- [ ] Fix any issues found
- [ ] Commit Phase 4 documentation

---

## Phase 5: MCP Tool Integration

### 5.1 Update set_project_directory Tool
- [ ] Add `config_file` parameter to `set_project_directory`
- [ ] Add `auto_refresh` parameter to `set_project_directory`
- [ ] Implement project identity creation in tool
- [ ] Implement project switching logic
- [ ] Implement auto-refresh on cache load
- [ ] Test project initialization with config_file
- [ ] Test project switching
- [ ] Test auto-refresh behavior
- [ ] Add tool integration tests
- [ ] Commit Phase 5.1 changes

### 5.2 Enhance refresh_analysis Tool
- [ ] Add `incremental` parameter to `refresh_analysis`
- [ ] Add `force_full` parameter to `refresh_analysis`
- [ ] Implement incremental analysis path
- [ ] Implement force full path
- [ ] Return detailed statistics
- [ ] Test incremental refresh
- [ ] Test force full refresh
- [ ] Test with no changes
- [ ] Add tool integration tests
- [ ] Commit Phase 5.2 changes

### 5.3 Documentation & Testing
- [ ] Update MCP tool documentation
- [ ] Create usage examples for Claude
- [ ] Add MCP protocol integration tests
- [ ] Test from actual MCP client
- [ ] Run full test suite
- [ ] Commit Phase 5 documentation

---

## Phase 6: Testing, Documentation & Polish

### 6.1 Comprehensive Testing
- [ ] Review all unit test coverage
- [ ] Add missing unit tests (target: >80% coverage)
- [ ] Review all integration tests
- [ ] Add end-to-end workflow tests
- [ ] Create performance benchmark suite
- [ ] Run benchmarks and document results
- [ ] Test edge cases (circular deps, missing files, etc.)
- [ ] Test concurrent access scenarios
- [ ] Fix all identified issues
- [ ] Commit Phase 6.1 changes

### 6.2 Documentation Updates
- [ ] Update `README.md` with incremental analysis features
- [ ] Update `REQUIREMENTS.md` with all new requirements
- [ ] Update `CONFIGURATION.md` with new settings
- [ ] Review and update `INCREMENTAL_ANALYSIS_DESIGN.md`
- [ ] Create `INCREMENTAL_ANALYSIS_USAGE.md` user guide
- [ ] Add troubleshooting guide
- [ ] Add migration guide from old versions
- [ ] Update all architecture diagrams
- [ ] Commit Phase 6.2 changes

### 6.3 Final Regression & Polish
- [ ] Run full regression test suite
- [ ] Test on multiple platforms (Linux, macOS, Windows)
- [ ] Test with various project sizes (small, medium, large)
- [ ] Performance profiling and optimization
- [ ] Fix any remaining issues
- [ ] Code review and cleanup
- [ ] Update CHANGELOG.md
- [ ] Tag release version
- [ ] Final commit and push

---

## Cross-Phase Tasks

### Continuous Integration
- [ ] Ensure CI passes after each phase
- [ ] Update CI configuration if needed
- [ ] Add performance regression tests to CI

### Code Quality
- [ ] Follow existing code style consistently
- [ ] Add comprehensive docstrings
- [ ] Add type hints throughout
- [ ] Run linter and fix issues
- [ ] Keep code DRY and maintainable

### Git Hygiene
- [ ] Commit after each major milestone
- [ ] Write descriptive commit messages
- [ ] Push to remote branch regularly
- [ ] Keep commits atomic and focused

---

## Progress Summary

**Phase 1**: 16/21 tasks (76%) - MOSTLY COMPLETE
- ✅ Phase 1.1: Project Identity System (9/9 complete)
- ✅ Phase 1.2: Database Schema Updates (6/6 complete)
- ⏳ Phase 1.3: Documentation & Testing (1/6 partial)

**Phase 2**: 18/20 tasks (90%) - MOSTLY COMPLETE
- ✅ Phase 2.1: Dependency Graph Builder (10/10 complete)
- ✅ Phase 2.2: Integration with Parsing Pipeline (8/8 complete)
- ⏳ Phase 2.3: Documentation & Testing (0/2 pending)

**Phase 3**: 0/10 tasks (0%) - NOT STARTED
**Phase 4**: 0/11 tasks (0%) - NOT STARTED
**Phase 5**: 0/9 tasks (0%) - NOT STARTED
**Phase 6**: 0/11 tasks (0%) - NOT STARTED

**Overall**: 34/72 tasks (47%)

---

## Notes & Issues

*Document any blockers, decisions, or important notes here as implementation progresses.*

