-- Migration 001: Initial Schema
-- Description: Create initial database schema with FTS5 support
-- Version: 1
-- Date: 2025-11-17

-- This migration creates the complete initial schema for the SQLite cache.
-- The actual schema is executed from schema.sql, so this migration just
-- ensures the schema_version table tracks it correctly.

-- Note: The schema is already created by schema.sql when the database
-- is first initialized. This migration file exists for documentation
-- and future schema versioning purposes.

-- All tables and indexes are created in schema.sql:
-- - symbols (main symbol storage)
-- - symbols_fts (FTS5 full-text search)
-- - file_metadata (file tracking)
-- - cache_metadata (configuration)
-- - schema_version (migration tracking)
-- - header_tracker (header processing)
-- - parse_errors (error logging)
