"""Automatic migration from JSON cache to SQLite cache."""

import json
import shutil
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from .symbol_info import SymbolInfo
from .sqlite_cache_backend import SqliteCacheBackend

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics


def migrate_json_to_sqlite(json_cache_dir: Path, db_path: Path) -> Tuple[bool, str]:
    """
    Migrate existing JSON cache to SQLite database.

    This function reads the existing cache_info.json and individual file caches,
    then migrates all symbols and metadata to the SQLite database.

    Args:
        json_cache_dir: Directory containing JSON cache files
        db_path: Path to SQLite database file

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        cache_info_path = json_cache_dir / "cache_info.json"

        # Check if JSON cache exists
        if not cache_info_path.exists():
            return False, "No JSON cache found to migrate"

        diagnostics.info(f"Starting migration from JSON cache: {json_cache_dir}")

        # Load JSON cache data
        with open(cache_info_path, 'r') as f:
            cache_data = json.load(f)

        # Validate cache version
        version = cache_data.get("version", "1.0")
        if version != "2.0":
            return False, f"Unsupported cache version: {version}"

        # Create SQLite backend
        backend = SqliteCacheBackend(db_path)

        # Extract all symbols from class_index and function_index
        all_symbols = []

        diagnostics.info("Extracting symbols from class_index...")
        for name, symbol_dicts in cache_data.get("class_index", {}).items():
            for symbol_dict in symbol_dicts:
                symbol = SymbolInfo(**symbol_dict)
                all_symbols.append(symbol)

        diagnostics.info("Extracting symbols from function_index...")
        for name, symbol_dicts in cache_data.get("function_index", {}).items():
            for symbol_dict in symbol_dicts:
                symbol = SymbolInfo(**symbol_dict)
                all_symbols.append(symbol)

        # Remove duplicates (symbols can be in both indexes)
        unique_symbols = {}
        for symbol in all_symbols:
            unique_symbols[symbol.usr] = symbol
        all_symbols = list(unique_symbols.values())

        diagnostics.info(f"Found {len(all_symbols)} unique symbols to migrate")

        # Batch insert symbols into SQLite
        if all_symbols:
            backend.save_symbols_batch(all_symbols)
            diagnostics.info(f"Successfully migrated {len(all_symbols)} symbols")

        # Migrate file_hashes to file_metadata table
        file_hashes = cache_data.get("file_hashes", {})
        diagnostics.info(f"Migrating {len(file_hashes)} file metadata entries...")

        for file_path, file_hash in file_hashes.items():
            # Count symbols for this file
            symbol_count = sum(1 for s in all_symbols if s.file == file_path)
            backend.update_file_metadata(file_path, file_hash, None, symbol_count)

        # Migrate cache metadata
        diagnostics.info("Migrating cache metadata...")
        metadata_fields = [
            "include_dependencies",
            "config_file_path",
            "config_file_mtime",
            "compile_commands_path",
            "compile_commands_mtime",
            "indexed_file_count"
        ]

        for field in metadata_fields:
            value = cache_data.get(field)
            if value is not None:
                backend.update_cache_metadata(field, str(value))

        # Verify migration
        stats = backend.get_symbol_stats()
        migrated_count = stats.get('total_symbols', 0)

        if migrated_count != len(all_symbols):
            return False, f"Migration verification failed: expected {len(all_symbols)} symbols, got {migrated_count}"

        success_msg = (
            f"Migration successful: {len(all_symbols)} symbols, "
            f"{len(file_hashes)} files, database size: {stats.get('db_size_mb', 0):.2f} MB"
        )
        diagnostics.info(success_msg)

        return True, success_msg

    except Exception as e:
        error_msg = f"Migration failed: {e}"
        diagnostics.error(error_msg)
        import traceback
        diagnostics.error(traceback.format_exc())
        return False, error_msg


def verify_migration(json_cache_dir: Path, db_path: Path, sample_size: int = 100) -> Tuple[bool, str]:
    """
    Verify that SQLite migration matches JSON cache.

    Performs comprehensive verification:
    1. Symbol count check
    2. Random sample verification
    3. Metadata verification

    Args:
        json_cache_dir: Directory containing JSON cache files
        db_path: Path to SQLite database file
        sample_size: Number of random symbols to verify (default: 100)

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        cache_info_path = json_cache_dir / "cache_info.json"

        # Check if JSON cache exists
        if not cache_info_path.exists():
            return False, "No JSON cache found to verify against"

        diagnostics.info(f"Verifying migration...")

        # Load JSON cache data
        with open(cache_info_path, 'r') as f:
            cache_data = json.load(f)

        # Create SQLite backend
        backend = SqliteCacheBackend(db_path)

        # 1. Symbol count check
        diagnostics.info("Checking symbol counts...")

        # Count symbols in JSON
        json_symbols = []
        for symbol_dicts in cache_data.get("class_index", {}).values():
            for symbol_dict in symbol_dicts:
                json_symbols.append(SymbolInfo(**symbol_dict))
        for symbol_dicts in cache_data.get("function_index", {}).values():
            for symbol_dict in symbol_dicts:
                json_symbols.append(SymbolInfo(**symbol_dict))

        # Remove duplicates
        unique_json = {s.usr: s for s in json_symbols}
        json_count = len(unique_json)

        # Count symbols in SQLite
        stats = backend.get_symbol_stats()
        sqlite_count = stats.get('total_symbols', 0)

        if json_count != sqlite_count:
            return False, f"Symbol count mismatch: JSON={json_count}, SQLite={sqlite_count}"

        diagnostics.info(f"✓ Symbol count matches: {json_count} symbols")

        # 2. Random sample verification
        diagnostics.info(f"Verifying random sample of {sample_size} symbols...")

        sample_count = min(sample_size, json_count)
        sample_symbols = random.sample(list(unique_json.values()), sample_count)

        mismatches = []
        for symbol in sample_symbols:
            # Search for symbol in SQLite by USR
            cursor = backend.conn.execute(
                "SELECT * FROM symbols WHERE usr = ?",
                (symbol.usr,)
            )
            row = cursor.fetchone()

            if not row:
                mismatches.append(f"Symbol {symbol.usr} not found in SQLite")
                continue

            # Verify key fields match
            sqlite_symbol = backend._row_to_symbol(row)

            if sqlite_symbol.name != symbol.name:
                mismatches.append(f"Name mismatch for {symbol.usr}: {symbol.name} != {sqlite_symbol.name}")
            if sqlite_symbol.kind != symbol.kind:
                mismatches.append(f"Kind mismatch for {symbol.usr}: {symbol.kind} != {sqlite_symbol.kind}")
            if sqlite_symbol.file != symbol.file:
                mismatches.append(f"File mismatch for {symbol.usr}: {symbol.file} != {sqlite_symbol.file}")

        if mismatches:
            error_msg = f"Sample verification failed: {len(mismatches)} mismatches:\n" + "\n".join(mismatches[:10])
            return False, error_msg

        diagnostics.info(f"✓ Random sample verified: {sample_count} symbols match")

        # 3. Metadata verification
        diagnostics.info("Verifying metadata...")

        metadata_fields = ["include_dependencies", "indexed_file_count"]
        metadata_mismatches = []

        for field in metadata_fields:
            json_value = str(cache_data.get(field, ""))
            sqlite_value = backend.get_cache_metadata(field) or ""

            if json_value != sqlite_value:
                metadata_mismatches.append(f"{field}: JSON={json_value}, SQLite={sqlite_value}")

        if metadata_mismatches:
            error_msg = "Metadata verification failed:\n" + "\n".join(metadata_mismatches)
            return False, error_msg

        diagnostics.info("✓ Metadata verified")

        # All checks passed
        success_msg = (
            f"Migration verification successful: "
            f"{json_count} symbols, {sample_count} samples verified, metadata verified"
        )
        diagnostics.info(success_msg)

        return True, success_msg

    except Exception as e:
        error_msg = f"Verification failed: {e}"
        diagnostics.error(error_msg)
        import traceback
        diagnostics.error(traceback.format_exc())
        return False, error_msg


def create_migration_backup(json_cache_dir: Path) -> Tuple[bool, str, Optional[Path]]:
    """
    Create backup of JSON cache before migration.

    Args:
        json_cache_dir: Directory containing JSON cache files

    Returns:
        Tuple of (success: bool, message: str, backup_path: Optional[Path])
    """
    try:
        # Create backup directory name with timestamp
        import time
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_dir = json_cache_dir.parent / f"{json_cache_dir.name}_backup_{timestamp}"

        diagnostics.info(f"Creating backup: {backup_dir}")

        # Copy entire cache directory
        shutil.copytree(json_cache_dir, backup_dir)

        success_msg = f"Backup created: {backup_dir}"
        diagnostics.info(success_msg)

        return True, success_msg, backup_dir

    except Exception as e:
        error_msg = f"Backup failed: {e}"
        diagnostics.error(error_msg)
        return False, error_msg, None


def should_migrate(json_cache_dir: Path, marker_file_path: Path) -> bool:
    """
    Check if migration should run.

    Args:
        json_cache_dir: Directory containing JSON cache files
        marker_file_path: Path to migration marker file

    Returns:
        True if migration should run, False if already migrated
    """
    # Check if already migrated
    if marker_file_path.exists():
        diagnostics.debug(f"Migration already completed (marker exists): {marker_file_path}")
        return False

    # Check if JSON cache exists
    cache_info_path = json_cache_dir / "cache_info.json"
    if not cache_info_path.exists():
        diagnostics.debug("No JSON cache found, migration not needed")
        return False

    diagnostics.info("JSON cache found and no migration marker - migration needed")
    return True


def create_migration_marker(marker_file_path: Path, migration_info: Dict) -> bool:
    """
    Create marker file to prevent re-migration.

    Args:
        marker_file_path: Path to migration marker file
        migration_info: Dict with migration details

    Returns:
        True if successful, False otherwise
    """
    try:
        import time

        marker_data = {
            "migrated_at": time.time(),
            "migration_info": migration_info,
            "version": "1.0"
        }

        with open(marker_file_path, 'w') as f:
            json.dump(marker_data, f, indent=2)

        diagnostics.info(f"Migration marker created: {marker_file_path}")
        return True

    except Exception as e:
        diagnostics.error(f"Failed to create migration marker: {e}")
        return False
