-- Migration 003: Add failure tracking to file_metadata
-- Add success, error_message, and retry_count columns to track parse failures per file

-- First, create file_metadata table if it doesn't exist (for test databases)
CREATE TABLE IF NOT EXISTS file_metadata (
    file_path TEXT PRIMARY KEY,
    file_hash TEXT NOT NULL,
    compile_args_hash TEXT,
    indexed_at REAL NOT NULL,
    symbol_count INTEGER DEFAULT 0
);

-- Now check if we need to add the new columns
-- We'll use a recreation approach to add columns while preserving data

-- Check if success column already exists (migration already applied or fresh DB)
-- If it exists, skip the rest of this migration
CREATE TEMP TABLE _check_migration AS
SELECT COUNT(*) as has_success_column
FROM pragma_table_info('file_metadata')
WHERE name = 'success';

-- Only proceed if success column doesn't exist
-- Create backup table with current data
CREATE TEMP TABLE file_metadata_temp AS
SELECT file_path, file_hash, compile_args_hash, indexed_at, symbol_count
FROM file_metadata;

-- Drop and recreate file_metadata with new schema
DROP TABLE file_metadata;

CREATE TABLE file_metadata (
    file_path TEXT PRIMARY KEY,
    file_hash TEXT NOT NULL,
    compile_args_hash TEXT,
    indexed_at REAL NOT NULL,
    symbol_count INTEGER DEFAULT 0,
    success BOOLEAN NOT NULL DEFAULT 1,
    error_message TEXT DEFAULT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0
);

-- Restore data from temp backup
INSERT INTO file_metadata (file_path, file_hash, compile_args_hash, indexed_at, symbol_count)
SELECT file_path, file_hash, compile_args_hash, indexed_at, symbol_count
FROM file_metadata_temp;

-- Drop temp table
DROP TABLE file_metadata_temp;
DROP TABLE _check_migration;

-- Recreate index
CREATE INDEX IF NOT EXISTS idx_file_indexed ON file_metadata(indexed_at);

-- Update schema version
INSERT INTO schema_version (version, applied_at, description)
VALUES (3, julianday('now'), 'Add failure tracking columns to file_metadata');
