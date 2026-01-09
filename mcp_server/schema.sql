-- SQLite Schema for C++ Symbol Cache
-- Version: 10.0
-- Optimized for fast symbol lookups with FTS5 full-text search
-- Changelog v10.0: Added qualified_name field for namespace-aware search (Qualified Names Phase 1)
-- Changelog v9.0: Removed calls/called_by columns from symbols table (memory optimization Task 1.2)
-- Changelog v8.0: Added call_sites, cross_references, parameter_docs tables for call graph enhancement (Phase 3: LLM Integration)
-- Changelog v7.0: Added brief and doc_comment fields for documentation extraction (Phase 2: LLM Integration)
-- Changelog v6.0: Added is_definition field for definition-wins logic (Phase 1: Multiple Declarations)
-- Changelog v5.0: Added line ranges and header file location tracking (Phase 1: LLM Integration)

-- NOTE: Connection-level PRAGMA optimizations are now applied in
-- SqliteCacheBackend._set_connection_pragmas() instead of here.
-- This ensures they're applied to ALL connections (main + worker processes),
-- not just during schema recreation.
--
-- Previously applied PRAGMAs (now in _set_connection_pragmas()):
--   PRAGMA journal_mode = WAL;        -- Write-Ahead Logging for concurrency
--   PRAGMA synchronous = NORMAL;      -- Balance safety and speed
--   PRAGMA cache_size = -64000;       -- 64MB cache
--   PRAGMA temp_store = MEMORY;       -- Keep temp tables in RAM
--   PRAGMA mmap_size = 268435456;     -- 256MB memory-mapped I/O

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL,
    description TEXT NOT NULL
);

-- Insert initial version
INSERT OR IGNORE INTO schema_version (version, applied_at, description)
VALUES (1, julianday('now'), 'Initial schema with FTS5 support');

-- Main symbols table
CREATE TABLE IF NOT EXISTS symbols (
    usr TEXT PRIMARY KEY,              -- Unified Symbol Resolution (unique ID)
    name TEXT NOT NULL,                -- Symbol name (e.g., "Vector", "push_back")
    qualified_name TEXT DEFAULT '',    -- Fully qualified name (e.g., "std::vector", "ns1::ns2::Class")
    kind TEXT NOT NULL,                -- "class", "function", "method", "struct"
    file TEXT NOT NULL,                -- Source file path (absolute)
    line INTEGER NOT NULL,             -- Line number
    column INTEGER NOT NULL,           -- Column number
    signature TEXT DEFAULT '',         -- Function signature
    is_project BOOLEAN NOT NULL DEFAULT 1,  -- True for project code, False for dependencies
    namespace TEXT DEFAULT '',         -- Namespace portion (e.g., "std", "ns1::ns2" from "ns1::ns2::Class")
    access TEXT DEFAULT 'public',      -- "public", "private", "protected"
    parent_class TEXT DEFAULT '',      -- For methods: containing class name
    base_classes TEXT DEFAULT '[]',    -- JSON array of base class names
    -- Note: calls/called_by columns removed in v9.0 (Task 1.2 memory optimization)
    -- Call graph data is now stored in call_sites table

    -- Line ranges (v5.0: Phase 1 LLM Integration)
    start_line INTEGER,                -- First line of symbol definition
    end_line INTEGER,                  -- Last line of symbol definition
    header_file TEXT,                  -- Path to header file (if declaration separate)
    header_line INTEGER,               -- Declaration line in header
    header_start_line INTEGER,         -- Declaration start line
    header_end_line INTEGER,           -- Declaration end line

    -- Definition tracking (v6.0: Phase 1 Multiple Declarations)
    is_definition BOOLEAN NOT NULL DEFAULT 0,  -- True if cursor is a definition (has body)

    -- Documentation (v7.0: Phase 2 LLM Integration)
    brief TEXT,                        -- Brief description (first line of documentation)
    doc_comment TEXT,                  -- Full documentation comment (up to 4000 chars)

    -- Metadata
    created_at REAL NOT NULL,          -- Unix timestamp
    updated_at REAL NOT NULL           -- Unix timestamp for incremental updates
);

-- Indexes for fast lookups (critical for performance)
CREATE INDEX IF NOT EXISTS idx_symbol_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbol_qualified_name ON symbols(qualified_name);
CREATE INDEX IF NOT EXISTS idx_symbol_kind ON symbols(kind);
CREATE INDEX IF NOT EXISTS idx_symbol_file ON symbols(file);
CREATE INDEX IF NOT EXISTS idx_symbol_parent ON symbols(parent_class);
CREATE INDEX IF NOT EXISTS idx_symbol_namespace ON symbols(namespace);
CREATE INDEX IF NOT EXISTS idx_symbol_project ON symbols(is_project);
CREATE INDEX IF NOT EXISTS idx_symbol_updated ON symbols(updated_at);

-- Composite index for common query patterns
CREATE INDEX IF NOT EXISTS idx_name_kind_project ON symbols(name, kind, is_project);

-- Index for line range queries (v5.0)
CREATE INDEX IF NOT EXISTS idx_symbols_range ON symbols(file, start_line, end_line);

-- Full-text search index (FTS5)
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    name,                -- Tokenized for full-text search
    qualified_name,      -- Qualified name for namespace-aware search
    kind,
    usr UNINDEXED,       -- Store but don't index
    content=symbols,
    content_rowid=rowid
);

-- Triggers to keep FTS index in sync with symbols table
CREATE TRIGGER IF NOT EXISTS symbols_ai AFTER INSERT ON symbols BEGIN
    INSERT INTO symbols_fts(rowid, name, qualified_name, kind, usr)
    VALUES (new.rowid, new.name, new.qualified_name, new.kind, new.usr);
END;

CREATE TRIGGER IF NOT EXISTS symbols_ad AFTER DELETE ON symbols BEGIN
    DELETE FROM symbols_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS symbols_au AFTER UPDATE ON symbols BEGIN
    UPDATE symbols_fts SET name = new.name, qualified_name = new.qualified_name, kind = new.kind
    WHERE rowid = old.rowid;
END;

-- File metadata table (replaces file_hashes dict)
CREATE TABLE IF NOT EXISTS file_metadata (
    file_path TEXT PRIMARY KEY,        -- Absolute file path
    file_hash TEXT NOT NULL,           -- MD5 hash of file contents
    compile_args_hash TEXT,            -- Hash of compilation arguments
    indexed_at REAL NOT NULL,          -- When file was last indexed
    symbol_count INTEGER DEFAULT 0,    -- Number of symbols in file
    success BOOLEAN NOT NULL DEFAULT 1,-- Whether parsing succeeded
    error_message TEXT DEFAULT NULL,   -- Error message if parsing failed
    retry_count INTEGER NOT NULL DEFAULT 0  -- Number of retry attempts
);

CREATE INDEX IF NOT EXISTS idx_file_indexed ON file_metadata(indexed_at);

-- Cache metadata table (replaces top-level cache_info fields)
CREATE TABLE IF NOT EXISTS cache_metadata (
    key TEXT PRIMARY KEY,              -- Setting key
    value TEXT NOT NULL,               -- Setting value (JSON for complex types)
    updated_at REAL NOT NULL           -- Last update timestamp
);

-- Initial metadata
INSERT OR IGNORE INTO cache_metadata (key, value, updated_at) VALUES
    ('version', '"10.0"', julianday('now')),
    ('include_dependencies', 'false', julianday('now')),
    ('indexed_file_count', '0', julianday('now')),
    ('last_vacuum', '0', julianday('now'));

-- Header tracking table (replaces header_tracker.json)
CREATE TABLE IF NOT EXISTS header_tracker (
    header_path TEXT PRIMARY KEY,      -- Absolute path to header file
    processed_by TEXT NOT NULL,        -- Source file that first processed this header
    file_hash TEXT NOT NULL,           -- Hash of header when processed
    compile_commands_hash TEXT,        -- Hash of compile_commands.json when processed
    processed_at REAL NOT NULL         -- Timestamp
);

-- Parse error log table (replaces parse_errors.jsonl)
CREATE TABLE IF NOT EXISTS parse_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    stack_trace TEXT,
    file_hash TEXT NOT NULL,
    compile_args_hash TEXT,
    retry_count INTEGER DEFAULT 0,
    timestamp REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_error_file ON parse_errors(file_path);
CREATE INDEX IF NOT EXISTS idx_error_timestamp ON parse_errors(timestamp);

-- File dependencies table for incremental analysis
-- Tracks include relationships to enable cascade re-analysis when headers change
CREATE TABLE IF NOT EXISTS file_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,          -- File doing the including (source or header)
    included_file TEXT NOT NULL,        -- File being included (header)
    is_direct BOOLEAN NOT NULL DEFAULT 1, -- True if direct #include, False if transitive
    include_depth INTEGER NOT NULL DEFAULT 1, -- 1 for direct, 2+ for transitive
    detected_at REAL NOT NULL,          -- When relationship discovered (Unix timestamp)

    -- Unique constraint: one row per relationship
    UNIQUE(source_file, included_file)
);

-- Indexes for efficient graph traversal
CREATE INDEX IF NOT EXISTS idx_dep_source ON file_dependencies(source_file);
CREATE INDEX IF NOT EXISTS idx_dep_included ON file_dependencies(included_file);
CREATE INDEX IF NOT EXISTS idx_dep_direct ON file_dependencies(is_direct);
CREATE INDEX IF NOT EXISTS idx_dep_detected ON file_dependencies(detected_at);

-- Phase 3: Call Graph Enhancement Tables (v8.0)

-- Call sites table: Tracks exact line/column where function calls occur
-- Enables line-level precision for call graph analysis
CREATE TABLE IF NOT EXISTS call_sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    caller_usr TEXT NOT NULL,              -- USR of calling function
    callee_usr TEXT NOT NULL,              -- USR of called function
    file TEXT NOT NULL,                    -- Source file containing call
    line INTEGER NOT NULL,                 -- Line number of call
    column INTEGER,                        -- Column number (optional)
    created_at REAL NOT NULL,              -- When call site was indexed
    FOREIGN KEY (caller_usr) REFERENCES symbols(usr) ON DELETE CASCADE,
    FOREIGN KEY (callee_usr) REFERENCES symbols(usr) ON DELETE CASCADE
);

-- Indexes for fast call site queries
CREATE INDEX IF NOT EXISTS idx_call_sites_caller ON call_sites(caller_usr);
CREATE INDEX IF NOT EXISTS idx_call_sites_callee ON call_sites(callee_usr);
CREATE INDEX IF NOT EXISTS idx_call_sites_file ON call_sites(file);
CREATE INDEX IF NOT EXISTS idx_call_sites_line ON call_sites(file, line);
