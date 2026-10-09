"""Cache backend port for the indexing use-case layer.

This Protocol defines the interface that persistence backends must implement.
It lives in the indexing layer so that use cases depend on an abstraction rather
than on the persistence implementation.
"""

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..._symbols.model import SymbolInfo
from ..._symbols.ports.parser import TypeAliasRecord


@runtime_checkable
class CacheBackend(Protocol):
    """Protocol defining the interface for cache backends."""

    def save_cache(
        self,
        class_index: dict[str, list[SymbolInfo]],
        function_index: dict[str, list[SymbolInfo]],
        file_hashes: dict[str, str],
        indexed_file_count: int,
        include_dependencies: bool = False,
        config_file_path: Path | None = None,
        config_file_mtime: float | None = None,
        compile_commands_path: Path | None = None,
        compile_commands_mtime: float | None = None,
    ) -> bool:
        """Save indexes to cache with configuration metadata."""
        ...

    def load_cache(
        self,
        include_dependencies: bool = False,
        config_file_path: Path | None = None,
        config_file_mtime: float | None = None,
        compile_commands_path: Path | None = None,
        compile_commands_mtime: float | None = None,
    ) -> dict[str, Any] | None:
        """Load cache if it exists and is valid."""
        ...

    def save_file_cache(
        self,
        file_path: str,
        symbols: list[SymbolInfo],
        file_hash: str,
        compile_args_hash: str | None = None,
        success: bool = True,
        error_message: str | None = None,
        retry_count: int = 0,
    ) -> bool:
        """Save parsed symbols for a single file."""
        ...

    def load_file_cache(
        self, file_path: str, current_hash: str, compile_args_hash: str | None = None
    ) -> dict[str, Any] | None:
        """Load cached data for a file if hash matches."""
        ...

    def remove_file_cache(self, file_path: str) -> bool:
        """Remove cached data for a deleted file."""
        ...

    def save_type_aliases_batch(self, aliases: list[TypeAliasRecord]) -> int:
        """Batch insert type aliases using transaction."""
        ...

    def get_aliases_for_canonical(self, canonical_type: str) -> list[str]:
        """Get all alias names that resolve to a given canonical type."""
        ...

    def get_canonical_for_alias(self, alias_name: str) -> str | None:
        """Get canonical type for a given alias name."""
        ...

    def get_all_alias_mappings(self) -> dict[str, str]:
        """Get all alias -> canonical mappings."""
        ...

    def get_type_alias_info(self, type_name: str) -> dict[str, Any] | None:
        """Get high-level information for a known type alias."""
        ...

    def get_type_alias_details(self, alias_names: list[str]) -> list[dict[str, Any]]:
        """Get detailed records for a list of alias names."""
        ...

    def get_all_cached_file_paths(self):
        """Return all file paths stored in file_metadata table."""
        ...

    def load_symbol_by_usr(self, usr: str) -> SymbolInfo | None:
        """Load a single symbol by its USR from persistent storage.

        Used to resolve external (non-project) symbols that are not held
        in the in-memory index.
        """
        ...

    def set_compile_args_hash(self, file_path: str, args_hash: str) -> bool:
        """Store or update the compile arguments hash for a file."""
        ...

    def get_compile_args_hash(self, file_path: str) -> str | None:
        """Return the stored compile arguments hash for a file."""
        ...

    def clear_compile_args_hashes(self) -> int:
        """Clear all stored compile arguments hashes from file_metadata."""
        ...

    def delete_call_sites_by_file(self, file_path: str) -> int:
        """Delete all call sites from a specific file."""
        ...

    def save_call_sites_batch(self, call_sites: list[dict[str, Any]]) -> int:
        """Batch insert call sites using transaction."""
        ...

    def rebuild_fts(self) -> bool:
        """Rebuild FTS5 index from scratch."""
        ...

    def ensure_schema_current(self) -> bool:
        """Ensure database schema is current before spawning workers."""
        ...

    def close(self) -> None:
        """Close the backend and release resources."""
        ...
