"""Cache backend protocol/interface for C++ analyzer."""

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from .._persistence.symbol_info import SymbolInfo


@runtime_checkable
class CacheBackend(Protocol):
    """
    Protocol defining the interface for cache backends.

    Currently only the SQLite backend implements this interface.
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

    def get_type_alias_info(self, type_name: str) -> Optional[Dict[str, Any]]:
        """Get high-level information for a known type alias."""
        ...

    def get_type_alias_details(self, alias_names: List[str]) -> List[Dict[str, Any]]:
        """Get detailed records for a list of alias names."""
        ...

    def get_all_cached_file_paths(self):
        """Return all file paths stored in file_metadata table."""
        ...

    def set_compile_args_hash(self, file_path: str, args_hash: str) -> bool:
        """Store or update the compile arguments hash for a file."""
        ...

    def get_compile_args_hash(self, file_path: str) -> Optional[str]:
        """Return the stored compile arguments hash for a file."""
        ...

    def clear_compile_args_hashes(self) -> int:
        """Clear all stored compile arguments hashes from file_metadata."""
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

    def get_connection(self) -> Optional[sqlite3.Connection]:
        """Return the raw SQLite connection for components that need direct access.

        This is a transitional method for components like DependencyGraphBuilder
        that inherently require raw SQL access. New code should use protocol
        methods instead of direct connection access.
        """
        ...

    conn: Optional[sqlite3.Connection]
