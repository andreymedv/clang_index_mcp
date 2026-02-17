"""Cache backend protocol/interface for C++ analyzer."""

import sqlite3
from typing import Protocol, Dict, List, Optional, Any, runtime_checkable
from pathlib import Path
from .symbol_info import SymbolInfo


@runtime_checkable
class CacheBackend(Protocol):
    """
    Protocol defining the interface for cache backends.

    Both JSON and SQLite backends implement this interface,
    allowing seamless switching between storage mechanisms.
    """

    def save_cache(
        self,
        class_index: Dict[str, List[SymbolInfo]],
        function_index: Dict[str, List[SymbolInfo]],
        file_hashes: Dict[str, str],
        indexed_file_count: int,
        include_dependencies: bool = False,
        config_file_path: Optional[Path] = None,
        config_file_mtime: Optional[float] = None,
        compile_commands_path: Optional[Path] = None,
        compile_commands_mtime: Optional[float] = None,
    ) -> bool:
        """Save indexes to cache with configuration metadata"""
        ...

    def load_cache(
        self,
        include_dependencies: bool = False,
        config_file_path: Optional[Path] = None,
        config_file_mtime: Optional[float] = None,
        compile_commands_path: Optional[Path] = None,
        compile_commands_mtime: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Load cache if it exists and is valid, checking for configuration changes"""
        ...

    def save_file_cache(
        self,
        file_path: str,
        symbols: List[SymbolInfo],
        file_hash: str,
        compile_args_hash: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        retry_count: int = 0,
    ) -> bool:
        """Save parsed symbols for a single file with compilation arguments hash"""
        ...

    def load_file_cache(
        self, file_path: str, current_hash: str, compile_args_hash: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Load cached data for a file if hash matches"""
        ...

    def remove_file_cache(self, file_path: str) -> bool:
        """Remove cached data for a deleted file"""
        ...

    def save_type_aliases_batch(self, aliases: List[Dict[str, Any]]) -> int:
        """Batch insert type aliases using transaction."""
        ...

    def get_aliases_for_canonical(self, canonical_type: str) -> List[str]:
        """Get all alias names that resolve to a given canonical type."""
        ...

    def get_canonical_for_alias(self, alias_name: str) -> Optional[str]:
        """Get canonical type for a given alias name."""
        ...

    def get_all_alias_mappings(self) -> Dict[str, str]:
        """Get all alias -> canonical mappings."""
        ...

    def delete_call_sites_by_file(self, file_path: str) -> int:
        """Delete all call sites from a specific file."""
        ...

    def save_call_sites_batch(self, call_sites: List[Dict[str, Any]]) -> int:
        """Batch insert call sites using transaction."""
        ...

    def rebuild_fts(self) -> bool:
        """Rebuild FTS5 index from scratch."""
        ...

    def _ensure_connected(self) -> None:
        """Ensure connection is active, reconnect if needed."""
        ...

    conn: Optional[sqlite3.Connection]
