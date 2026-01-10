# Changelog

All notable changes to the C++ MCP Server will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added - Qualified Names Support (Phases 1-3)

#### Phase 1: Basic Qualified Name Storage & Extraction
- **New Fields**: All search results now include `qualified_name` and `namespace` fields
  - `qualified_name`: Fully qualified symbol name (e.g., `"app::ui::View"`)
  - `namespace`: Namespace portion only (e.g., `"app::ui"`)
- **Schema v10.0**: Updated SQLite schema to store qualified names
- **All Tools Updated**: `search_classes`, `search_functions`, `search_symbols`, `find_in_file`, `get_class_info`
- **Backward Compatible**: Existing unqualified search patterns continue to work

#### Phase 2: Qualified Pattern Matching
- **Four Pattern Matching Modes**:
  1. **Unqualified**: `"View"` matches in any namespace
  2. **Qualified Suffix**: `"ui::View"` uses component-based suffix matching
  3. **Exact Match**: `"::View"` matches only global namespace (leading `::`)
  4. **Regex**: `"app::.*::View"` uses regex fullmatch semantics
- **Component Boundaries**: Suffix matching respects namespace boundaries (`"ui::View"` ≠ `"myui::View"`)
- **Case-Insensitive**: All pattern matching is case-insensitive
- **Performance**: All queries complete in <100ms (tested with 1000+ classes)
- **Backward Compatible**: Existing searches use unqualified mode automatically

#### Phase 3: Overload Metadata (Template Specialization Detection)
- **New Field**: `is_template_specialization` boolean for all function/method results
  - `false` for generic templates: `template<typename T> void foo(T)`
  - `true` for specializations: `template<> void foo<int>(int)`
  - `false` for regular overloads: `void foo(double)`
- **Schema v10.1**: Added `is_template_specialization` column
- **Detection Algorithm**: Analyzes cursor kind and displayname for template arguments
- **Use Case**: Distinguish template specializations from generic templates in overload analysis

#### Phase 4: Testing & Documentation
- **Integration Tests**: 21 new tests covering features F1-F7 (qualified names, templates, nested classes, etc.)
- **Performance Benchmarks**: 11 performance tests verifying <100ms query times
- **Migration Guide**: Comprehensive guide at `docs/QUALIFIED_NAMES_MIGRATION.md`
- **Updated Tool Descriptions**: All MCP tool descriptions now document qualified name features
- **100% Test Coverage**: All features validated with automated tests

### Changed

- **MCP Tool Descriptions**: Updated all search tool descriptions to document new fields and pattern matching modes
- **Search Results**: All results now include qualified name context for better disambiguation

### Performance

- Qualified pattern searches: 1-3ms (target: <100ms) ✅
- Unqualified searches: 1-3ms (unchanged from before)
- Regex pattern searches: 1-10ms (target: <200ms) ✅
- Pattern matching algorithm: <1ms per match

### Migration

- **No Breaking Changes**: All existing code continues to work
- **Recommended**: Use qualified patterns for disambiguation
- **Recommended**: Display `qualified_name` instead of `name` for clarity
- **See**: `docs/QUALIFIED_NAMES_MIGRATION.md` for detailed migration guide

---

## [1.0.0] - Previous Releases

### Added
- Multi-process parallel parsing with ProcessPoolExecutor (6-7x speedup)
- Header deduplication (first-win strategy) for 5-10x performance improvement
- Incremental analysis with intelligent change detection (30-300x faster re-indexing)
- SQLite-backed symbol cache with FTS5 full-text search
- compile_commands.json support for accurate build configuration
- 18 MCP tools for C++ code analysis
- Call graph analysis (find_callers, find_callees)
- Documentation extraction (Doxygen, JavaDoc, Qt-style comments)
- Line range tracking for symbols
- Definition-wins logic for multiple declarations

### Performance Optimizations
- Connection-level PRAGMA optimizations (restored ~3.5 files/sec performance)
- AST traversal optimization with system header skipping (5-7x speedup)
- Worker memory optimization: eliminated duplicate CompileCommandsManager (6-10 GB savings)
- Lazy call graph loading (Phase 4 memory optimization): eliminated in-memory call graphs (~2 GB savings)

### Documentation
- Comprehensive README with setup instructions
- CLAUDE.md for AI assistant guidance
- Testing guides and diagnostic tools
- Performance profiling scripts

---

## Release Notes

### Qualified Names Support v10.1

This release adds powerful namespace-aware search capabilities to the C++ MCP server:

**Key Features:**
- Search by qualified name patterns: `"ui::View"`, `"::Config"`, `"app::.*::View"`
- Component-based suffix matching with boundary respect
- Template specialization detection for overload analysis
- Fully backward compatible with existing code

**Use Cases:**
- Disambiguate symbols across namespaces
- Find specific namespaced classes/functions
- Analyze template specializations vs generics
- Navigate complex C++ codebases efficiently

**Performance:**
- All queries <100ms (typically 1-3ms)
- No performance degradation for existing searches
- Extensively tested with 1000+ class projects

**See Also:**
- Migration Guide: `docs/QUALIFIED_NAMES_MIGRATION.md`
- Integration Tests: `tests/test_qualified_name_integration.py`
- Performance Benchmarks: `tests/test_qualified_name_performance.py`

---

[Unreleased]: https://github.com/andreymedv/clang_index_mcp/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/andreymedv/clang_index_mcp/releases/tag/v1.0.0
