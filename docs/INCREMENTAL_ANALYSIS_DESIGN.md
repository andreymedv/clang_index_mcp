# Incremental Analysis Architecture Design

**Version:** 1.0
**Status:** Design Document
**Author:** MCP Server Architect
**Date:** 2025-11-18

## Executive Summary

This document outlines the architectural design for implementing incremental analysis in the C++ MCP Server. The goal is to minimize re-analysis when project files change by tracking dependencies and selectively re-analyzing only affected files.

### Current State Assessment

The existing system has solid foundations for incremental analysis:

✅ **File Change Detection**: MD5 hashing in `file_metadata` table
✅ **Header Deduplication**: First-win strategy via `HeaderProcessingTracker`
✅ **compile_commands.json Tracking**: Hash-based invalidation
✅ **Persistent Cache**: SQLite backend with WAL mode
✅ **File Metadata**: Tracks indexed files with timestamps

### Gaps Requiring Implementation

❌ **Include Dependency Graph**: No tracking of which files include which headers
❌ **Project Identity**: Only uses project_root, needs config_path integration
❌ **Granular Re-analysis**: No cascade logic for header changes
❌ **compile_commands.json Entry Diff**: No per-entry change detection

---

## 1. Project Identification System

### 1.1 Requirements

Per user requirements:
> "I would identify the project by the combination of source directory and the path to MCP server configuration file. If I change one of paths above, it shall be a separate project creation or switching to the already existing one."

### 1.2 Current Implementation

```python
# Current: cache_manager.py
cache_dir = project_root / ".mcp_cache" / f"{project_name}_{project_hash}"
project_hash = hashlib.md5(str(project_root).encode()).hexdigest()[:8]
```

**Problem**: Only considers `project_root`, not configuration file path.

### 1.3 Proposed Design

#### Project Identity Components

```python
class ProjectIdentity:
    """Unique identifier for a project based on source dir + config path."""

    def __init__(self, source_directory: Path, config_file_path: Optional[Path]):
        self.source_directory = source_directory.resolve()
        self.config_file_path = config_file_path.resolve() if config_file_path else None

    def compute_hash(self) -> str:
        """
        Compute unique hash for this project identity.

        Combines:
        - Absolute source directory path
        - Absolute config file path (if provided)

        Returns 16-character hex hash for cache directory naming.
        """
        components = [str(self.source_directory)]

        if self.config_file_path:
            components.append(str(self.config_file_path))

        combined = "|".join(components)
        hash_value = hashlib.sha256(combined.encode('utf-8')).hexdigest()
        return hash_value[:16]  # 16 chars = 64-bit hash space

    def get_cache_directory_name(self) -> str:
        """Get cache directory name for this project."""
        project_name = self.source_directory.name or "project"
        return f"{project_name}_{self.compute_hash()}"
```

#### Integration Points

1. **CppAnalyzer Initialization**
   ```python
   def __init__(self, project_root: str, config_file: Optional[str] = None):
       self.project_identity = ProjectIdentity(
           Path(project_root),
           Path(config_file) if config_file else None
       )
       self.cache_manager = CacheManager(self.project_identity)
   ```

2. **Cache Manager Update**
   ```python
   def __init__(self, project_identity: ProjectIdentity):
       self.project_identity = project_identity
       cache_name = project_identity.get_cache_directory_name()
       self.cache_dir = Path.home() / ".mcp_cache" / cache_name
   ```

3. **MCP Server Tool**
   ```python
   @server.call_tool()
   async def set_project_directory(
       project_path: str,
       config_file: Optional[str] = None
   ):
       """
       Initialize or switch to a project.

       Args:
           project_path: Source directory path
           config_file: Optional path to MCP config file

       Behavior:
           - Different paths → New/different project
           - Same paths → Resume existing project
           - Config content change → Incremental update within same project
       """
   ```

### 1.4 Migration Path

**Backward Compatibility**:
- Old cache directories (without config hash) remain valid
- On first load with new system, rehash and migrate if needed
- Leave old cache for manual cleanup

---

## 2. Include Dependency Tracking System

### 2.1 Requirements

> "If header is changed, only the one and files that include it directly or indirectly will be re-analysed"

This requires a **dependency graph** tracking include relationships.

### 2.2 Database Schema Extension

#### New Table: file_dependencies

```sql
-- Track include relationships for incremental analysis
CREATE TABLE IF NOT EXISTS file_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,        -- File doing the including
    included_file TEXT NOT NULL,      -- File being included
    is_direct BOOLEAN NOT NULL,       -- True if direct #include, False if transitive
    include_depth INTEGER NOT NULL,   -- 1 for direct, 2+ for transitive
    detected_at REAL NOT NULL,        -- When relationship discovered

    -- Unique constraint: one row per relationship
    UNIQUE(source_file, included_file)
);

-- Indexes for efficient graph traversal
CREATE INDEX IF NOT EXISTS idx_dep_source ON file_dependencies(source_file);
CREATE INDEX IF NOT EXISTS idx_dep_included ON file_dependencies(included_file);
CREATE INDEX IF NOT EXISTS idx_dep_direct ON file_dependencies(is_direct);
```

#### Updated header_tracker Table

```sql
-- Add dependency tracking version
ALTER TABLE header_tracker ADD COLUMN dependency_graph_version INTEGER DEFAULT 1;
```

### 2.3 Dependency Graph Builder

```python
class DependencyGraphBuilder:
    """
    Builds and maintains the include dependency graph.

    Responsibilities:
    - Extract include directives from translation units
    - Build forward graph (file → what it includes)
    - Build reverse graph (header → files that include it)
    - Compute transitive closure for cascade analysis
    """

    def __init__(self, db_connection: sqlite3.Connection):
        self.conn = db_connection

    def extract_includes_from_tu(self, tu: TranslationUnit, source_file: str) -> List[str]:
        """
        Extract all includes from a translation unit.

        Uses libclang's translation unit to get complete include list,
        including system headers and transitive includes.

        Args:
            tu: Parsed translation unit
            source_file: Path to source file being analyzed

        Returns:
            List of absolute paths to all included files
        """
        includes = []

        # Get all includes from TU (libclang provides this)
        for include in tu.get_includes():
            included_path = str(include.include.name)
            includes.append(included_path)

        return includes

    def update_dependencies(self, source_file: str, included_files: List[str]):
        """
        Update dependency graph for a source file.

        Strategy:
        1. Delete old dependencies for this source
        2. Insert new direct dependencies
        3. Compute and insert transitive dependencies

        Args:
            source_file: Path to source file
            included_files: List of files it includes (direct + transitive)
        """
        cursor = self.conn.cursor()

        # Delete old dependencies
        cursor.execute(
            "DELETE FROM file_dependencies WHERE source_file = ?",
            (source_file,)
        )

        # Insert new dependencies
        now = time.time()

        for included_file in included_files:
            # Mark all as direct for simplicity
            # (libclang doesn't easily distinguish direct vs transitive)
            cursor.execute("""
                INSERT OR REPLACE INTO file_dependencies
                (source_file, included_file, is_direct, include_depth, detected_at)
                VALUES (?, ?, ?, ?, ?)
            """, (source_file, included_file, True, 1, now))

        self.conn.commit()

    def find_dependents(self, header_path: str) -> Set[str]:
        """
        Find all files that depend on a header (reverse lookup).

        This is the key query for incremental analysis:
        "Header X changed, which files need re-analysis?"

        Args:
            header_path: Path to header file

        Returns:
            Set of source files that include this header
        """
        cursor = self.conn.cursor()

        # Direct dependents
        cursor.execute("""
            SELECT DISTINCT source_file
            FROM file_dependencies
            WHERE included_file = ?
        """, (header_path,))

        dependents = {row[0] for row in cursor.fetchall()}

        return dependents

    def find_transitive_dependents(self, header_path: str) -> Set[str]:
        """
        Find all files that depend on a header transitively.

        Example:
            A.cpp includes B.h
            B.h includes C.h

            find_transitive_dependents("C.h") → {A.cpp, B.h}

        Uses recursive CTE for graph traversal.
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            WITH RECURSIVE dependents(file_path) AS (
                -- Base case: direct dependents
                SELECT DISTINCT source_file
                FROM file_dependencies
                WHERE included_file = ?

                UNION

                -- Recursive case: files that include dependents
                SELECT DISTINCT fd.source_file
                FROM file_dependencies fd
                JOIN dependents d ON fd.included_file = d.file_path
            )
            SELECT file_path FROM dependents
        """, (header_path,))

        return {row[0] for row in cursor.fetchall()}
```

### 2.4 Integration with Parsing

```python
class CppAnalyzer:
    def __init__(self, project_root: str):
        # ... existing initialization ...

        # Add dependency graph builder
        self.dependency_graph = DependencyGraphBuilder(
            self.cache_manager.backend.conn
        )

    def _index_translation_unit(self, tu, source_file: str) -> List[SymbolInfo]:
        """Modified to track dependencies."""

        # Extract includes from TU
        included_files = self.dependency_graph.extract_includes_from_tu(tu, source_file)

        # Update dependency graph
        self.dependency_graph.update_dependencies(source_file, included_files)

        # ... rest of existing symbol extraction ...
```

---

## 3. Incremental Analysis Strategies

### 3.1 Header File Changes

**Requirement**:
> "If header is changed, only the one and files that include it directly or indirectly will be re-analysed"

#### Algorithm

```python
def handle_header_change(self, header_path: str) -> Set[str]:
    """
    Handle incremental analysis when a header changes.

    Steps:
    1. Detect header change via file hash
    2. Find all files that include this header
    3. Mark header for re-processing
    4. Re-analyze all dependent files

    Returns:
        Set of files that were re-analyzed
    """
    # 1. Detect change
    current_hash = self._get_file_hash(header_path)
    stored_metadata = self.cache_manager.get_file_metadata(header_path)

    if stored_metadata and stored_metadata['file_hash'] == current_hash:
        # No change, skip
        return set()

    diagnostics.info(f"Header changed: {header_path}")

    # 2. Find dependents
    dependent_files = self.dependency_graph.find_transitive_dependents(header_path)

    diagnostics.info(f"Found {len(dependent_files)} files depending on {header_path}")

    # 3. Invalidate header in tracker
    self.header_tracker.invalidate_header(header_path)

    # 4. Re-analyze all dependent files
    files_to_reanalyze = dependent_files.copy()

    # Note: Header itself will be re-processed when dependents are analyzed
    # due to first-win strategy being invalidated

    return self._reanalyze_files(files_to_reanalyze)
```

### 3.2 Source File Changes

**Requirement**:
> "If source file is changed, only this file has to be re-analysed"

#### Algorithm

```python
def handle_source_change(self, source_path: str) -> bool:
    """
    Handle incremental analysis when a source file changes.

    Steps:
    1. Detect source change via file hash
    2. Re-analyze only this file
    3. Update dependency graph
    4. Update symbols in cache

    Returns:
        True if re-analysis succeeded
    """
    # 1. Detect change
    current_hash = self._get_file_hash(source_path)
    stored_metadata = self.cache_manager.get_file_metadata(source_path)

    if stored_metadata and stored_metadata['file_hash'] == current_hash:
        # No change, skip
        return True

    diagnostics.info(f"Source changed: {source_path}")

    # 2. Re-analyze file
    # Note: Headers it includes will be checked via first-win strategy
    # If headers changed, they'll be re-processed automatically

    success, was_cached = self.index_file(source_path, force=True)

    return success
```

### 3.3 compile_commands.json Changes

**Requirement**:
> "If compile_commands.json has changed, only the modified/added/removed entries should be re-analysed"

#### Algorithm

```python
class CompileCommandsDiffer:
    """
    Computes differences between compile_commands.json versions.

    Tracks per-file compilation arguments and detects:
    - Added files
    - Removed files
    - Files with changed arguments
    """

    def __init__(self, cache_backend: SqliteCacheBackend):
        self.cache = cache_backend

    def compute_diff(
        self,
        old_commands: Dict[str, List[str]],
        new_commands: Dict[str, List[str]]
    ) -> Tuple[Set[str], Set[str], Set[str]]:
        """
        Compute difference between compile command sets.

        Args:
            old_commands: {file_path: [args]} from cache
            new_commands: {file_path: [args]} from new file

        Returns:
            (added_files, removed_files, changed_files)
        """
        old_files = set(old_commands.keys())
        new_files = set(new_commands.keys())

        added = new_files - old_files
        removed = old_files - new_files

        # Check for changed arguments
        changed = set()
        for file_path in old_files & new_files:
            old_args = old_commands[file_path]
            new_args = new_commands[file_path]

            # Compare args (order matters for some flags)
            if old_args != new_args:
                changed.add(file_path)

        return added, removed, changed

    def store_current_commands(self, commands: Dict[str, List[str]]):
        """
        Store current compile commands in cache for future diffing.

        Stored in file_metadata table as compile_args_hash per file.
        """
        for file_path, args in commands.items():
            args_hash = self._hash_args(args)

            self.cache.conn.execute("""
                UPDATE file_metadata
                SET compile_args_hash = ?
                WHERE file_path = ?
            """, (args_hash, file_path))

        self.cache.conn.commit()

    def _hash_args(self, args: List[str]) -> str:
        """Hash compilation arguments for comparison."""
        args_str = "|".join(args)
        return hashlib.sha256(args_str.encode()).hexdigest()


def handle_compile_commands_change(self) -> Set[str]:
    """
    Handle incremental analysis when compile_commands.json changes.

    Steps:
    1. Detect file change via hash
    2. Load new compile commands
    3. Compute diff with cached version
    4. Re-analyze only affected files

    Returns:
        Set of files that were re-analyzed
    """
    cc_path = self.project_root / self.config.get_compile_commands_path()

    if not cc_path.exists():
        diagnostics.info("compile_commands.json removed or not found")
        return set()

    # 1. Detect change
    current_hash = self._get_file_hash(str(cc_path))

    if current_hash == self.compile_commands_hash:
        # No change
        return set()

    diagnostics.info("compile_commands.json changed, computing diff...")

    # 2. Load new commands
    old_commands = self.compile_commands_manager.file_to_command_map
    self.compile_commands_manager._load_compile_commands()
    new_commands = self.compile_commands_manager.file_to_command_map

    # 3. Compute diff
    differ = CompileCommandsDiffer(self.cache_manager.backend)
    added, removed, changed = differ.compute_diff(old_commands, new_commands)

    diagnostics.info(f"Compile commands diff: +{len(added)} -{len(removed)} ~{len(changed)}")

    # 4. Handle changes
    files_to_reanalyze = added | changed

    # Remove symbols for removed files
    for file_path in removed:
        self._remove_file_from_cache(file_path)

    # 5. Update compile_commands_hash
    self.compile_commands_hash = current_hash

    # 6. Invalidate ALL headers (args changed might affect preprocessing)
    # This is conservative but safe
    self.header_tracker.clear_all()
    diagnostics.info("Invalidated all header tracking due to compile commands change")

    # 7. Re-analyze affected files
    return self._reanalyze_files(files_to_reanalyze)
```

---

## 4. Unified Change Detection System

### 4.1 Change Scanner

```python
class ChangeScanner:
    """
    Unified change detection system that scans for all types of changes.

    Integrates:
    - File content changes (MD5 hash)
    - compile_commands.json changes
    - Dependency graph tracking
    """

    def __init__(self, analyzer: CppAnalyzer):
        self.analyzer = analyzer

    def scan_for_changes(self) -> ChangeSet:
        """
        Scan project for all changes since last analysis.

        Returns:
            ChangeSet containing all detected changes
        """
        changeset = ChangeSet()

        # 1. Check compile_commands.json first (affects everything)
        cc_changed = self._check_compile_commands()
        if cc_changed:
            changeset.compile_commands_changed = True
            # Will trigger broader re-analysis

        # 2. Scan source files
        source_files = self.analyzer.file_scanner.find_cpp_files()

        for source_file in source_files:
            change_type = self._check_file_change(source_file)

            if change_type == ChangeType.ADDED:
                changeset.added_files.add(source_file)
            elif change_type == ChangeType.MODIFIED:
                changeset.modified_files.add(source_file)

        # 3. Scan headers (check against tracked headers)
        tracked_headers = self.analyzer.header_tracker.get_processed_headers()

        for header_path in tracked_headers:
            if not Path(header_path).exists():
                changeset.removed_files.add(header_path)
                continue

            current_hash = self.analyzer._get_file_hash(header_path)
            tracked_hash = tracked_headers[header_path]

            if current_hash != tracked_hash:
                changeset.modified_headers.add(header_path)

        # 4. Check for deleted files
        cached_files = self.analyzer.cache_manager.get_all_indexed_files()

        for cached_file in cached_files:
            if not Path(cached_file).exists():
                changeset.removed_files.add(cached_file)

        return changeset

    def _check_file_change(self, file_path: str) -> ChangeType:
        """Check if a file is new, modified, or unchanged."""
        metadata = self.analyzer.cache_manager.get_file_metadata(file_path)

        if not metadata:
            return ChangeType.ADDED

        current_hash = self.analyzer._get_file_hash(file_path)

        if current_hash != metadata['file_hash']:
            return ChangeType.MODIFIED

        return ChangeType.UNCHANGED


class ChangeSet:
    """Container for all detected changes."""

    def __init__(self):
        self.compile_commands_changed: bool = False
        self.added_files: Set[str] = set()
        self.modified_files: Set[str] = set()
        self.modified_headers: Set[str] = set()
        self.removed_files: Set[str] = set()

    def is_empty(self) -> bool:
        """Check if no changes detected."""
        return (
            not self.compile_commands_changed
            and not self.added_files
            and not self.modified_files
            and not self.modified_headers
            and not self.removed_files
        )

    def get_total_changes(self) -> int:
        """Get total number of changed files."""
        return (
            len(self.added_files)
            + len(self.modified_files)
            + len(self.modified_headers)
            + len(self.removed_files)
        )


class ChangeType(Enum):
    """Type of file change."""
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    UNCHANGED = "unchanged"
```

### 4.2 Incremental Analysis Coordinator

```python
class IncrementalAnalyzer:
    """
    Coordinates incremental analysis based on detected changes.

    This is the main entry point for all incremental updates.
    """

    def __init__(self, analyzer: CppAnalyzer):
        self.analyzer = analyzer
        self.scanner = ChangeScanner(analyzer)

    def perform_incremental_analysis(self) -> AnalysisResult:
        """
        Perform incremental analysis of changed files.

        High-level algorithm:
        1. Scan for all changes
        2. Prioritize changes (compile_commands first)
        3. Compute affected files
        4. Re-analyze minimal set
        5. Update cache and indexes

        Returns:
            AnalysisResult with statistics
        """
        diagnostics.info("Starting incremental analysis...")

        # 1. Scan for changes
        changes = self.scanner.scan_for_changes()

        if changes.is_empty():
            diagnostics.info("No changes detected, cache is up to date")
            return AnalysisResult.no_changes()

        diagnostics.info(f"Detected {changes.get_total_changes()} changes")

        # 2. Build re-analysis set
        files_to_analyze = set()

        # Handle compile_commands.json change (broadest impact)
        if changes.compile_commands_changed:
            cc_affected = self.analyzer.handle_compile_commands_change()
            files_to_analyze.update(cc_affected)

        # Handle header changes (cascade to dependents)
        for header in changes.modified_headers:
            dependents = self.analyzer.dependency_graph.find_transitive_dependents(header)
            files_to_analyze.update(dependents)
            diagnostics.info(f"Header {header} affects {len(dependents)} files")

        # Handle source changes (isolated)
        files_to_analyze.update(changes.modified_files)

        # Handle new files
        files_to_analyze.update(changes.added_files)

        # Handle removed files
        for removed_file in changes.removed_files:
            self.analyzer._remove_file_from_cache(removed_file)

        # 3. Re-analyze
        diagnostics.info(f"Re-analyzing {len(files_to_analyze)} files...")

        start_time = time.time()
        reanalyzed = self.analyzer._reanalyze_files(files_to_analyze)
        elapsed = time.time() - start_time

        # 4. Results
        result = AnalysisResult(
            files_analyzed=len(reanalyzed),
            files_removed=len(changes.removed_files),
            elapsed_seconds=elapsed,
            changes=changes
        )

        diagnostics.info(f"Incremental analysis complete: {result}")

        return result


class AnalysisResult:
    """Results from incremental analysis."""

    def __init__(
        self,
        files_analyzed: int,
        files_removed: int,
        elapsed_seconds: float,
        changes: ChangeSet
    ):
        self.files_analyzed = files_analyzed
        self.files_removed = files_removed
        self.elapsed_seconds = elapsed_seconds
        self.changes = changes

    @staticmethod
    def no_changes():
        """Create result for no changes case."""
        return AnalysisResult(0, 0, 0.0, ChangeSet())

    def __str__(self):
        return (
            f"Analyzed {self.files_analyzed} files, "
            f"removed {self.files_removed} files "
            f"in {self.elapsed_seconds:.2f}s"
        )
```

---

## 5. MCP Tool Integration

### 5.1 New Tool: refresh_analysis (Enhanced)

```python
@server.call_tool()
async def refresh_analysis(
    incremental: bool = True,
    force_full: bool = False
) -> List[TextContent]:
    """
    Refresh code analysis with incremental or full re-indexing.

    Args:
        incremental: Use incremental analysis (default: True)
        force_full: Force full re-analysis even if no changes (default: False)

    Behavior:
        - incremental=True: Scan for changes, re-analyze only affected files
        - force_full=True: Clear cache and re-analyze everything

    Returns:
        Analysis results with statistics
    """
    global analyzer

    if analyzer is None:
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": "Analyzer not initialized. Call set_project_directory first."
            })
        )]

    try:
        if force_full:
            # Full re-analysis
            diagnostics.info("Performing full re-analysis (forced)")
            analyzer.cache_manager.clear_cache()
            analyzer.index_project()

            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "mode": "full",
                    "indexed_files": analyzer.indexed_file_count
                })
            )]

        elif incremental:
            # Incremental analysis
            incremental_analyzer = IncrementalAnalyzer(analyzer)
            result = incremental_analyzer.perform_incremental_analysis()

            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "mode": "incremental",
                    "files_analyzed": result.files_analyzed,
                    "files_removed": result.files_removed,
                    "elapsed_seconds": result.elapsed_seconds,
                    "changes": {
                        "compile_commands": result.changes.compile_commands_changed,
                        "added": len(result.changes.added_files),
                        "modified": len(result.changes.modified_files),
                        "headers_modified": len(result.changes.modified_headers),
                        "removed": len(result.changes.removed_files)
                    }
                })
            )]

        else:
            # Just validate cache is current
            scanner = ChangeScanner(analyzer)
            changes = scanner.scan_for_changes()

            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "mode": "scan_only",
                    "changes_detected": not changes.is_empty(),
                    "total_changes": changes.get_total_changes()
                })
            )]

    except Exception as e:
        diagnostics.error(f"Refresh analysis failed: {e}")
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": str(e)
            })
        )]
```

### 5.2 Updated Tool: set_project_directory

```python
@server.call_tool()
async def set_project_directory(
    project_path: str,
    config_file: Optional[str] = None,
    auto_refresh: bool = True
) -> List[TextContent]:
    """
    Set project directory and initialize analyzer.

    Args:
        project_path: Root directory of C++ project
        config_file: Optional path to .cpp-analyzer-config.json
        auto_refresh: Automatically perform incremental refresh on load

    Behavior:
        - First call: Initialize and full index
        - Subsequent calls with same identity: Incremental refresh
        - Different identity: Switch projects
    """
    global analyzer, state_manager

    try:
        # Create project identity
        identity = ProjectIdentity(
            Path(project_path),
            Path(config_file) if config_file else None
        )

        # Check if switching projects
        if analyzer is not None:
            current_identity = analyzer.project_identity
            if current_identity.compute_hash() != identity.compute_hash():
                # Different project, reinitialize
                diagnostics.info("Switching to different project")
                analyzer = None

        # Initialize if needed
        if analyzer is None:
            state_manager.transition_to(AnalyzerState.INITIALIZING)
            analyzer = CppAnalyzer(project_path, config_file)

            # Check if cache exists
            cache_exists = analyzer.cache_manager.cache_exists()

            if cache_exists and auto_refresh:
                # Incremental refresh
                diagnostics.info("Cache found, performing incremental refresh")
                incremental_analyzer = IncrementalAnalyzer(analyzer)
                result = incremental_analyzer.perform_incremental_analysis()

                state_manager.transition_to(AnalyzerState.INDEXED)

                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "initialized",
                        "mode": "incremental_refresh",
                        "files_analyzed": result.files_analyzed,
                        "cache_used": True
                    })
                )]
            else:
                # Full initial index
                state_manager.transition_to(AnalyzerState.INDEXING)
                analyzer.index_project()
                state_manager.transition_to(AnalyzerState.INDEXED)

                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "initialized",
                        "mode": "full_index",
                        "indexed_files": analyzer.indexed_file_count
                    })
                )]

    except Exception as e:
        diagnostics.error(f"Failed to set project directory: {e}")
        state_manager.transition_to(AnalyzerState.FAILED)
        raise
```

---

## 6. Implementation Roadmap

### Phase 1: Foundation (Week 1)

**Goal**: Project identity and database schema

1. **Task 1.1**: Implement `ProjectIdentity` class
   - File: `mcp_server/project_identity.py` (new)
   - Tests: Unit tests for hash computation

2. **Task 1.2**: Update database schema
   - Add `file_dependencies` table
   - Migration script for existing caches
   - File: `mcp_server/schema.sql`

3. **Task 1.3**: Integrate ProjectIdentity into CacheManager
   - Update constructor to accept ProjectIdentity
   - Backward compatibility for old cache directories

### Phase 2: Dependency Tracking (Week 2)

**Goal**: Build and maintain include dependency graph

1. **Task 2.1**: Implement `DependencyGraphBuilder`
   - File: `mcp_server/dependency_graph.py` (new)
   - Extract includes from TranslationUnit
   - Database CRUD operations

2. **Task 2.2**: Integrate with parsing pipeline
   - Modify `_index_translation_unit` to extract dependencies
   - Update after each file parse

3. **Task 2.3**: Add query methods
   - `find_dependents(header)` → direct dependents
   - `find_transitive_dependents(header)` → full cascade

### Phase 3: Change Detection (Week 3)

**Goal**: Detect all types of changes

1. **Task 3.1**: Implement `ChangeScanner`
   - File: `mcp_server/change_scanner.py` (new)
   - Scan for file content changes
   - Scan for compile_commands.json changes
   - Detect added/removed files

2. **Task 3.2**: Implement `CompileCommandsDiffer`
   - File: `mcp_server/compile_commands_differ.py` (new)
   - Compute diffs between CC versions
   - Store per-file args hashes

3. **Task 3.3**: Add ChangeSet data structure
   - Unified representation of all changes

### Phase 4: Incremental Analysis (Week 4)

**Goal**: Re-analyze only affected files

1. **Task 4.1**: Implement `IncrementalAnalyzer`
   - File: `mcp_server/incremental_analyzer.py` (new)
   - Coordinate change detection + re-analysis
   - Handle each change type appropriately

2. **Task 4.2**: Add `_reanalyze_files()` method
   - Re-parse specified files
   - Update cache incrementally
   - Rebuild in-memory indexes

3. **Task 4.3**: Handle file removal
   - Delete symbols from database
   - Update dependency graph
   - Clean up file_metadata

### Phase 5: MCP Integration (Week 5)

**Goal**: Expose incremental analysis via MCP tools

1. **Task 5.1**: Update `set_project_directory` tool
   - Accept config_file parameter
   - Auto-refresh on project load
   - Project switching logic

2. **Task 5.2**: Enhance `refresh_analysis` tool
   - Add incremental mode
   - Add force_full option
   - Return detailed statistics

3. **Task 5.3**: Add automatic refresh hooks
   - Optional: Watch filesystem for changes
   - Or: Refresh on first query after period

### Phase 6: Testing & Documentation (Week 6)

**Goal**: Comprehensive testing and docs

1. **Task 6.1**: Unit tests
   - ProjectIdentity
   - DependencyGraphBuilder
   - ChangeScanner
   - IncrementalAnalyzer

2. **Task 6.2**: Integration tests
   - End-to-end incremental analysis scenarios
   - Header change cascade
   - compile_commands.json changes

3. **Task 6.3**: Documentation
   - Update architecture docs
   - User guide for incremental analysis
   - Performance benchmarks

---

## 7. Performance Considerations

### 7.1 Expected Performance Improvements

**Scenario 1: Single header change**
- Current: Re-analyze entire project (~100 files, 30s)
- With incremental: Re-analyze header + dependents (~5 files, 2s)
- **Speedup: 15x**

**Scenario 2: Single source change**
- Current: Re-analyze entire project (~100 files, 30s)
- With incremental: Re-analyze 1 file (0.3s)
- **Speedup: 100x**

**Scenario 3: compile_commands.json change (1 file)**
- Current: Re-analyze entire project (~100 files, 30s)
- With incremental: Re-analyze 1 file (0.3s)
- **Speedup: 100x**

### 7.2 Memory Overhead

**Dependency Graph Storage**:
- Average project: 500 files, 5 includes each = 2,500 rows
- Row size: ~200 bytes
- Total: ~500KB (negligible)

**In-Memory Graph** (optional optimization):
- Cache reverse dependencies in memory
- ~1MB for large projects
- Faster lookups, avoid SQL queries

### 7.3 Optimization Opportunities

1. **Parallel Re-analysis**: Already supported via ProcessPoolExecutor
2. **Lazy Refresh**: Only refresh when queries require it
3. **Background Refresh**: Watch filesystem, refresh in background
4. **Incremental Symbol Updates**: UPDATE instead of DELETE+INSERT

---

## 8. Edge Cases & Robustness

### 8.1 Circular Dependencies

**Scenario**: A.h includes B.h, B.h includes A.h (via guards)

**Handling**:
- Dependency graph tracks includes as-is
- Circular references naturally handled by SQLite UNIQUE constraint
- Transitive query uses DISTINCT to avoid duplicates

### 8.2 Missing Files

**Scenario**: Header tracked in dependency graph but file deleted

**Handling**:
- Change scanner detects missing files
- Removes from cache
- Updates dependency graph (removes rows with that file)

### 8.3 Build System Changes

**Scenario**: Switch from CMake to Bazel, different compile_commands.json format

**Handling**:
- compile_commands_hash changes
- Full header tracker invalidation
- Re-analyze with new compilation args

### 8.4 Concurrent Updates

**Scenario**: Multiple MCP clients modifying same project

**Handling**:
- SQLite WAL mode supports concurrent reads
- Write operations serialized via database lock
- File hash checks detect external changes

---

## 9. Success Metrics

### 9.1 Functional Metrics

✅ **Correctness**: Incremental analysis produces same results as full analysis
✅ **Coverage**: All change types handled (files, headers, compile_commands)
✅ **Robustness**: No crashes on edge cases

### 9.2 Performance Metrics

🎯 **Single File Change**: < 1s re-analysis (vs 30s full)
🎯 **Header Change**: < 5s for 10 dependents (vs 30s full)
🎯 **compile_commands Change**: < 2s for single entry (vs 30s full)
🎯 **Memory Overhead**: < 2MB additional (dependency graph + tracking)

### 9.3 Usability Metrics

📊 **Developer Experience**: Transparent incremental updates on `set_project_directory`
📊 **Visibility**: Clear statistics on what was re-analyzed
📊 **Control**: Force full re-analysis when needed

---

## 10. Conclusion

This design provides a comprehensive incremental analysis system that:

1. **Minimizes re-analysis** by tracking dependencies and detecting precise changes
2. **Maintains correctness** via hash-based validation and cascade logic
3. **Integrates seamlessly** with existing MCP server architecture
4. **Scales efficiently** using SQLite for graph storage and parallel processing
5. **Handles edge cases** robustly via careful invalidation strategies

The implementation follows a phased approach over 6 weeks, building incrementally on the solid foundation already in place.

**Next Steps**: Begin Phase 1 implementation of ProjectIdentity and schema updates.
