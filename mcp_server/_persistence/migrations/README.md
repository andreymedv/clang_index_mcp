# Database Schema Migrations

This directory contains SQL migration files for the SQLite cache database.

## Overview

Migrations provide a versioned, incremental approach to database schema changes. Each migration file represents a specific version of the database schema.

## Migration Files

### Naming Convention

Migration files follow the pattern: `NNN_description.sql`

- `NNN`: Three-digit migration number (001, 002, 003, ...)
- `description`: Brief description of what the migration does

### Current Migrations

- **001_initial_schema.sql**: Initial database schema with FTS5 support (v1)

## How Migrations Work

1. **Version Tracking**: The `schema_version` table tracks which migrations have been applied.

2. **Automatic Application**: Migrations are automatically applied when:
   - Database is first created (all migrations applied)
   - Database version is older than current version (pending migrations applied)

3. **Forward-Only**: Migrations are applied in order and cannot be rolled back. Always move forward.

## Creating a New Migration

To create a new migration:

1. **Determine next version number**: Check existing migrations, use next number (e.g., 002)

2. **Create migration file**: `mcp_server/migrations/002_add_feature.sql`

3. **Write SQL**: Add schema changes (CREATE TABLE, ALTER TABLE, CREATE INDEX, etc.)

4. **Update CURRENT_SCHEMA_VERSION**: Increment version in `sqlite_cache_backend.py`

5. **Test**: Verify migration works on existing databases

### Example Migration

```sql
-- Migration 002: Add symbol visibility tracking
-- Description: Add visibility column to symbols table
-- Version: 2
-- Date: 2025-12-01

-- Add new column with default value
ALTER TABLE symbols ADD COLUMN visibility TEXT DEFAULT 'default';

-- Create index for visibility queries
CREATE INDEX IF NOT EXISTS idx_symbol_visibility ON symbols(visibility);

-- Update metadata
UPDATE cache_metadata
SET value = '3.1', updated_at = julianday('now')
WHERE key = 'version';
```

## Migration Best Practices

1. **Backward Compatibility**: Ensure new schemas can read old data
2. **Test Thoroughly**: Test on databases with existing data
3. **Document Changes**: Clear comments explaining what and why
4. **Atomic Operations**: Each migration should be atomic
5. **Data Migration**: If changing data structure, include data migration SQL
6. **Performance**: Consider impact on large databases (add indexes carefully)

## Troubleshooting

### Migration Failed

If a migration fails:

1. Check error message in logs
2. Verify SQL syntax
3. Check if schema already exists (migrations should use `IF NOT EXISTS`)
4. Test migration on empty database
5. Contact development team if issue persists

### Version Mismatch

If database version is newer than code version:

- Error message: "Database schema version X is newer than supported version Y"
- Solution: Update code to latest version
- Alternative: Downgrade database (not recommended, may lose data)

### Corrupted Database

If database is corrupted during migration:

1. Restore from backup (created automatically before migration)
2. Or delete cache and rebuild from source
3. Check disk space and filesystem health

## Schema Version History

| Version | Migration | Description | Date |
|---------|-----------|-------------|------|
| 1 | 001_initial_schema.sql | Initial schema with FTS5 | 2025-11-17 |

## Related Files

- `mcp_server/schema.sql`: Initial schema definition
- `mcp_server/schema_migrations.py`: Migration framework code
- `mcp_server/sqlite_cache_backend.py`: Backend that applies migrations
