"""
Single-file indexing pipeline for C++ Analyzer.

Extracted from CppAnalyzer to isolate the end-to-end flow of indexing one C++ file:
hashing, cache lookup, parsing with fallback, diagnostic handling, symbol extraction,
and cache persistence.
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional

from . import diagnostics

if TYPE_CHECKING:
    from .project_context import ProjectContext


class SingleFileIndexingPipeline:
    """Coordinates parsing and symbol extraction for a single C++ file."""

    def __init__(self, context: "ProjectContext"):
        """
        Initialize the single-file indexing pipeline.

        Args:
            context: Shared project context with all required services.
        """
        self.context = context
        assert context.clang_parser is not None
        self.clang_parser = context.clang_parser
        assert context.symbol_extractor is not None
        self.symbol_extractor = context.symbol_extractor
        assert context.compilation_env is not None
        self.compilation_env = context.compilation_env
        assert context.cache_orchestrator is not None
        self.cache_orchestrator = context.cache_orchestrator
        assert context.cache_manager is not None
        self.cache_manager = context.cache_manager
        assert context.concurrency is not None
        self.concurrency = context.concurrency
        assert context.symbol_store is not None
        self.symbol_store = context.symbol_store

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

        current_hash = self.cache_orchestrator._get_file_hash(file_path)
        args = self.compilation_env.get_compile_args_for_file(Path(file_path))
        compile_args_hash = self.compilation_env._compute_compile_args_hash(args)

        cached = self.cache_orchestrator._try_load_cached_index(
            file_path, current_hash, compile_args_hash, force
        )
        if cached is not None:
            return cached  # type: ignore[no-any-return]

        retry_count = self._compute_retry_count(file_path, current_hash, compile_args_hash, force)

        try:
            tu, error_msg_opt = self.clang_parser._try_parse_with_fallback(file_path, args)
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

        cache_data = self.cache_orchestrator._load_file_cache(
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
        self.cache_orchestrator._save_file_cache(
            file_path,
            [],
            current_hash,
            compile_args_hash,
            success=False,
            error_message=error_msg[:200],
            retry_count=retry_count,
        )

    def _handle_index_file_diagnostics(
        self, file_path: str, tu: Any, current_hash: str, compile_args_hash: str, retry_count: int
    ) -> Optional[str]:
        """Extract and process diagnostics. Returns error message if any."""
        return (  # type: ignore[no-any-return]
            self.clang_parser._handle_index_file_diagnostics(
                file_path, tu, current_hash, compile_args_hash, retry_count
            )
        )

    def _finalize_index_success(
        self,
        file_path: str,
        tu,
        current_hash: str,
        compile_args_hash: str,
        cache_error_msg: Optional[str],
    ) -> tuple[bool, bool]:
        """Clear old entries, process TU, collect symbols, and save to cache."""
        with self.concurrency.get_lock():
            self.symbol_store._clear_file_index_entries(file_path)

        extraction_result = self.symbol_extractor._index_translation_unit(tu, file_path)
        processed_count = len(extraction_result["processed"])
        if processed_count > 1:
            diagnostics.debug(
                f"{file_path}: processed {processed_count} files "
                f"({processed_count - 1} headers extracted, {len(extraction_result['skipped'])} skipped)"
            )

        with self.concurrency.get_lock():
            collected_symbols = self.symbol_store.file_index.get(file_path, []).copy()
            del tu

            self.symbol_store.file_hashes[file_path] = current_hash

        self.cache_orchestrator._save_file_cache(
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
        self.cache_orchestrator._save_file_cache(
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
