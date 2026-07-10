"""
Single-file indexing pipeline for C++ Analyzer.

Extracted from CppAnalyzer to isolate the end-to-end flow of indexing one C++ file:
hashing, cache lookup, parsing with fallback, diagnostic handling, symbol extraction,
and cache persistence.
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from clang.cindex import TranslationUnit

from .._core import diagnostics

if TYPE_CHECKING:
    from .._compilation.clang_parser import ClangParser
    from .._compilation.compilation_environment import CompilationEnvironment
    from .._persistence.cache_manager import CacheManager
    from .._persistence.cache_orchestrator import CacheOrchestrator
    from .._symbols.symbol_extractor import SymbolExtractor
    from .._symbols.symbol_index_store import SymbolIndexStore


class SingleFileIndexingPipeline:
    """Coordinates parsing and symbol extraction for a single C++ file."""

    def __init__(
        self,
        clang_parser: "ClangParser",
        symbol_extractor: "SymbolExtractor",
        compilation_env: "CompilationEnvironment",
        cache_orchestrator: "CacheOrchestrator",
        cache_manager: "CacheManager",
        symbol_store: "SymbolIndexStore",
    ):
        """
        Initialize the single-file indexing pipeline.

        Args:
            clang_parser: Clang parser for translation unit parsing.
            symbol_extractor: Symbol extraction from translation units.
            compilation_env: Compilation environment for file scanning.
            cache_orchestrator: Cache orchestration and header tracking.
            cache_manager: SQLite-backed cache and persistence.
            symbol_store: In-memory symbol indexes.
        """
        self.clang_parser = clang_parser
        self.symbol_extractor = symbol_extractor
        self.compilation_env = compilation_env
        self.cache_orchestrator = cache_orchestrator
        self.cache_manager = cache_manager
        self.symbol_store = symbol_store

    def index_file(self, file_path: str, force: bool = False) -> tuple[bool, bool]:
        """Index a single C++ file.

        Returns:
            (success, was_cached) - success indicates if indexing succeeded,
                                   was_cached indicates if it was loaded from cache
        """
        file_path = os.path.abspath(file_path)

        if not Path(file_path).exists():
            error_msg = f"Source file does not exist: {file_path}"
            diagnostics.error(error_msg)
            self.cache_manager.log_parse_error(file_path, FileNotFoundError(error_msg), "", None, 0)
            return (False, False)

        current_hash = self.cache_orchestrator.get_file_hash(file_path)
        args = self.compilation_env.get_compile_args_for_file(Path(file_path))
        compile_args_hash = self.compilation_env.compute_compile_args_hash(args)

        cached = self.cache_orchestrator.try_load_cached_index(
            file_path, current_hash, compile_args_hash, force
        )
        if cached is not None:
            return cached  # type: ignore[no-any-return]

        retry_count = self._compute_retry_count(file_path, current_hash, compile_args_hash, force)

        try:
            tu, error_msg_opt = self.clang_parser.try_parse_with_fallback(file_path, args)
            if not tu:
                error_msg = error_msg_opt or "Unknown libclang error"
                self._handle_index_file_failure(
                    file_path, error_msg, args, current_hash, compile_args_hash, retry_count
                )
                return (False, False)

            cache_error_msg = self._handle_index_file_diagnostics(
                file_path, tu, current_hash, compile_args_hash, retry_count
            )

            return self._finalize_index_success(
                file_path, tu, current_hash, compile_args_hash, cache_error_msg
            )

        except Exception as e:
            return self._finalize_index_failure(
                file_path, e, current_hash, compile_args_hash, retry_count
            )

    def _compute_retry_count(
        self, file_path: str, current_hash: str, compile_args_hash: str, force: bool
    ) -> int:
        """Compute retry count based on previous failed cache entries."""
        if force:
            return 0

        cache_data = self.cache_orchestrator.load_file_cache(
            file_path, current_hash, compile_args_hash
        )
        if cache_data is not None and not cache_data["success"]:
            return int(cache_data["retry_count"]) + 1
        return 0

    def _handle_index_file_failure(
        self,
        file_path: str,
        error_msg: str,
        args: List[str],
        current_hash: str,
        compile_args_hash: str,
        retry_count: int,
    ) -> None:
        """Log failure and save to cache."""
        diagnostics.error(f"Failed to parse {file_path}")
        diagnostics.error(f"  Error: {error_msg}")

        # Log first 10 args to avoid overwhelming output
        diagnostics.error(f"  Compilation args ({len(args)} total):")
        for i, arg in enumerate(args[:10]):
            diagnostics.error(f"    [{i}] {arg}")

        # Log to centralized error log
        parse_error = Exception(f"{error_msg}\nArgs: {args}")
        self.cache_manager.log_parse_error(
            file_path, parse_error, current_hash, compile_args_hash, retry_count
        )

        # Save failure to cache
        self.cache_orchestrator.save_file_cache(
            file_path,
            [],
            current_hash,
            compile_args_hash,
            success=False,
            error_message=error_msg[:200],
            retry_count=retry_count,
        )

    def _handle_index_file_diagnostics(
        self,
        file_path: str,
        tu: TranslationUnit,
        current_hash: str,
        compile_args_hash: str,
        retry_count: int,
    ) -> Optional[str]:
        """Extract and process diagnostics. Returns error message if any."""
        return (  # type: ignore[no-any-return]
            self.clang_parser.handle_index_file_diagnostics(
                file_path, tu, current_hash, compile_args_hash, retry_count
            )
        )

    def _finalize_index_success(
        self,
        file_path: str,
        tu: TranslationUnit,
        current_hash: str,
        compile_args_hash: str,
        cache_error_msg: Optional[str],
    ) -> tuple[bool, bool]:
        """Clear old entries, process TU, collect symbols, and save to cache."""
        with self.symbol_store.index_lock:
            self.symbol_store.clear_file_index_entries(file_path)

        extraction_result = self.symbol_extractor.index_translation_unit(tu, file_path)
        processed_count = len(extraction_result["processed"])
        if processed_count > 1:
            diagnostics.debug(
                f"{file_path}: processed {processed_count} files "
                f"({processed_count - 1} headers extracted, {len(extraction_result['skipped'])} skipped)"
            )

        with self.symbol_store.index_lock:
            collected_symbols = self.symbol_store.get_symbols_in_file(file_path).copy()
            del tu

            self.symbol_store.set_file_hash(file_path, current_hash)

        self.cache_orchestrator.save_file_cache(
            file_path,
            collected_symbols,
            current_hash,
            compile_args_hash,
            success=True,
            error_message=cache_error_msg,
            retry_count=0,
        )
        return (True, False)

    def _finalize_index_failure(
        self,
        file_path: str,
        error: Exception,
        current_hash: str,
        compile_args_hash: str,
        retry_count: int,
    ) -> tuple[bool, bool]:
        """Log parse error and save failure state to cache."""
        self.cache_manager.log_parse_error(
            file_path, error, current_hash, compile_args_hash, retry_count
        )
        error_msg = str(error)[:200]
        self.cache_orchestrator.save_file_cache(
            file_path,
            [],
            current_hash,
            compile_args_hash,
            success=False,
            error_message=error_msg,
            retry_count=retry_count,
        )
        diagnostics.debug(f"Failed to parse {file_path}: {error_msg}")
        return (False, False)
