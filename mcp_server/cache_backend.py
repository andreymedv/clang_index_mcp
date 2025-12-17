"""Cache backend protocol/interface for C++ analyzer."""

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
