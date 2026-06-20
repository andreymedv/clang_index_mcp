-- Migration 002: Add file_dependencies table for incremental analysis
--
-- Purpose: Track include relationships between source files and headers
--          to enable cascade re-analysis when headers change.
--
-- Feature: Incremental Analysis
-- Date: 2025-11-18

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
