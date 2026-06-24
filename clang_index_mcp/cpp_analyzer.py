"""
C++ Analyzer — Thin Orchestrator Facade

This module provides the CppAnalyzer class, which serves as a thin facade
over the CompositionRoot. CppAnalyzer exposes the public API for code analysis
while delegating component wiring to the CompositionRoot.

CppAnalyzer itself contains only:
- __init__: delegates to CompositionRoot
- Lifecycle: close, __enter__, __exit__, __del__
- Interrupt handling: interrupt, _is_interrupted
- Thin public wrappers that delegate to the appropriate component

External code should access components via analyzer.X (e.g. analyzer.cache_manager)
or through the public wrapper methods (e.g. analyzer.search_classes()).
"""

import sys
from typing import Any, Dict, List, Optional

from .composition_root import CompositionRoot
from ._symbols.indexing_callbacks import IndexingCallbacks

# Handle both package and script imports
try:
    from ._core import diagnostics
except ImportError:
    import diagnostics  # type: ignore[no-redef]

try:
    from clang.cindex import Index  # noqa: F401
except ImportError:
    diagnostics.fatal("clang package not found. Install with: pip install libclang")
    sys.exit(1)


class CppAnalyzer:
    """
    Pure Python C++ code analyzer using libclang.

    This class provides code analysis functionality including:
    - Class and struct discovery
    - Function and method discovery
    - Symbol search with regex patterns
    - File-based filtering
    """

    def __init__(
        self,
        project_root: str,
        config_file: Optional[str] = None,
        skip_schema_recreation: bool = False,
        use_compile_commands_manager: bool = True,
    ):
        """
        Initialize C++ Analyzer.

        Args:
            project_root: Path to project source directory
            config_file: Optional path to configuration file for project identity
            skip_schema_recreation: If True, skip database recreation on schema mismatch.
                                   Used by worker processes to avoid race conditions.
                                   Workers should rely on main process to ensure schema is current.
            use_compile_commands_manager: If False, skip CompileCommandsManager initialization.
                                         Used by worker processes that receive precomputed compile args.

        Note:
            Project identity is determined by (source_directory, config_file) pair.
            Different config_file values create separate cache directories.
        """
        self._skip_schema_recreation = skip_schema_recreation

        # Delegate all wiring to CompositionRoot
        self._root = CompositionRoot(
            project_root,
            config_file=config_file,
            skip_schema_recreation=skip_schema_recreation,
            use_compile_commands_manager=use_compile_commands_manager,
        )

        # Expose all composed services as direct attributes for backward compatibility
        self.context = self._root.context
        self.project_root = self._root.project_root
        self.index = self._root.index
        self.project_identity = self._root.project_identity
        self.config = self._root.config
        self.cache_manager = self._root.cache_manager
        self.concurrency = self._root.concurrency
        self.cancellation = self._root.cancellation
        self.execution = self._root.execution
        self.progress_reporter = self._root.progress_reporter
        self.call_graph_service = self._root.call_graph_service
        self.symbol_store = self._root.symbol_store
        self.compilation_env = self._root.compilation_env
        self.query_engine = self._root.query_engine
        self.cache_orchestrator = self._root.cache_orchestrator
        self.cache_dir = self._root.cache_manager.cache_dir
        self.clang_parser = self._root.clang_parser
        self.symbol_extractor = self._root.symbol_extractor
        self.task_submitter = self._root.task_submitter
        self.worker_result_merger = self._root.worker_result_merger
        self.indexing_pipeline = self._root.indexing_pipeline
        self.refresh_pipeline = self._root.refresh_pipeline
        self.indexing_orchestrator = self._root.indexing_orchestrator

    def interrupt(self):
        """
        Interrupt any ongoing indexing operations.
        Sets the interrupted flag which is checked by indexing loops.
        """
        self.cancellation.interrupt()

    def _is_interrupted(self) -> bool:
        """Check if indexing has been interrupted."""
        return self.cancellation.is_interrupted()

    def close(self):
        """
        Close the analyzer and release all resources.

        This should be called when the CppAnalyzer is no longer needed
        to properly close database connections and avoid resource leaks.
        """
        if hasattr(self, "cache_manager") and self.cache_manager is not None:
            self.cache_manager.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False

    def __del__(self):
        """Destructor to ensure resources are released on garbage collection."""
        # During Python shutdown, modules may be None. Suppress all errors.
        try:
            # Check if we're shutting down - skip cleanup if so
            if sys is None or sys.meta_path is None:
                return
            self.close()
        except (ImportError, AttributeError, TypeError):
            # Suppress errors during shutdown - resources will be cleaned up by OS
            pass

    def get_compile_commands_stats(self) -> Dict[str, Any]:
        """Get compile commands statistics (delegates to compilation_env)."""
        return self.compilation_env.get_compile_commands_stats()

    def index_file(self, file_path: str, force: bool = False) -> tuple[bool, bool]:
        """Index a single C++ file.

        Returns:
            (success, was_cached) - success indicates if indexing succeeded,
                                   was_cached indicates if it was loaded from cache
        """
        return self.indexing_pipeline.index_file(file_path, force)

    def index_project(
        self,
        force: bool = False,
        include_dependencies: bool = True,
        callbacks: Optional[IndexingCallbacks] = None,
    ) -> int:
        """
        Index all C++ files in the project.

        Args:
            force: Force re-indexing even if cache exists
            include_dependencies: Include dependency files in indexing
            callbacks: Optional IndexingCallbacks with progress and wait_for_tools callbacks

        Returns:
            Number of files indexed
        """
        self.compilation_env.include_dependencies = include_dependencies
        return self.indexing_orchestrator.index_project(
            include_dependencies,
            force=force,
            callbacks=callbacks,
        )

    def pop_last_fallback(self):
        """Return and clear the last fallback result (delegates to query_engine)."""
        return self.query_engine.pop_last_fallback()

    def search_classes(
        self,
        pattern: str,
        project_only: bool = True,
        file_name: Optional[str] = None,
        namespace: Optional[str] = None,
        max_results: Optional[int] = None,
        include_base_classes: bool = True,
    ):
        """Search for classes matching pattern (delegates to query_engine)."""
        return self.query_engine.search_classes(
            pattern, project_only, file_name, namespace, max_results, include_base_classes
        )

    def search_functions(
        self,
        pattern: str,
        project_only: bool = True,
        class_name: Optional[str] = None,
        file_name: Optional[str] = None,
        namespace: Optional[str] = None,
        max_results: Optional[int] = None,
        signature_pattern: Optional[str] = None,
        include_attributes: bool = False,
    ):
        """Search for functions matching pattern (delegates to query_engine)."""
        return self.query_engine.search_functions(
            pattern,
            project_only,
            class_name,
            file_name,
            namespace,
            max_results,
            signature_pattern,
            include_attributes,
        )

    def get_stats(self) -> Dict[str, int]:
        """Get indexer statistics (delegates to query_engine)."""
        return self.query_engine.get_stats()

    def refresh_if_needed(
        self,
        callbacks: Optional[IndexingCallbacks] = None,
    ) -> int:
        """
        Refresh index for changed files and remove deleted files.

        Args:
            callbacks: Optional IndexingCallbacks with progress and wait_for_tools callbacks

        Returns:
            Number of files refreshed
        """
        return self.refresh_pipeline.refresh_if_needed(
            self.compilation_env.include_dependencies,
            callbacks=callbacks,
        )

    def get_class_info(self, class_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific class (delegates to query_engine)."""
        return self.query_engine.get_class_info(class_name)

    def get_function_signature(
        self, function_name: str, class_name: Optional[str] = None
    ) -> List[str]:
        """Get signature details for functions (delegates to query_engine)."""
        return self.query_engine.get_function_signature(function_name, class_name)

    def get_type_alias_info(self, type_name: str) -> Dict[str, Any]:
        """Get comprehensive type alias information (delegates to query_engine)."""
        return self.query_engine.get_type_alias_info(type_name)

    def search_symbols(
        self,
        pattern: str,
        project_only: bool = True,
        symbol_types: Optional[List[str]] = None,
        namespace: Optional[str] = None,
        max_results: Optional[int] = None,
        signature_pattern: Optional[str] = None,
    ):
        """Search for all symbols (classes and functions) matching pattern (delegates to query_engine)."""
        return self.query_engine.search_symbols(
            pattern, project_only, symbol_types, namespace, max_results, signature_pattern
        )

    def get_derived_classes(
        self, class_name: str, project_only: bool = True
    ) -> List[Dict[str, Any]]:
        """Get all classes that derive from the given class (delegates to query_engine)."""
        return self.query_engine.get_derived_classes(class_name, project_only)

    def _check_template_param_inheritance(self, base_class: str, target_class: str) -> bool:
        """Check indirect inheritance through template parameters (delegates to query_engine)."""
        return self.query_engine._check_template_param_inheritance(base_class, target_class)

    def _get_template_param_inheritance_indices(self, template_name: str) -> List[int]:
        """Get template parameter indices that a template inherits from (delegates to query_engine)."""
        return self.query_engine._get_template_param_inheritance_indices(template_name)

    def _parse_template_args(self, args_str: str) -> List[str]:
        """Parse template arguments from a string (delegates to query_engine)."""
        return self.query_engine._parse_template_args(args_str)

    def get_class_hierarchy(
        self,
        class_name: str,
        max_nodes: Optional[int] = 200,
        max_depth: Optional[int] = None,
        direction: str = "both",
    ) -> Dict[str, Any]:
        """Get the inheritance graph for a class as a flat adjacency list (delegates to query_engine)."""
        return self.query_engine.get_class_hierarchy(class_name, max_nodes, max_depth, direction)

    def find_incoming_calls(
        self,
        function_name: str,
        class_name: str = "",
        include_call_sites: bool = True,
        project_only: bool = True,
    ) -> Dict[str, Any]:
        """Find all functions that call the specified function."""
        return self.call_graph_service.find_incoming_calls(
            function_name, class_name, include_call_sites, project_only
        )

    def find_callees(
        self, function_name: str, class_name: str = "", project_only: bool = True
    ) -> Dict[str, Any]:
        """Find all functions called by the specified function."""
        return self.call_graph_service.find_callees(function_name, class_name, project_only)

    def get_call_sites(self, function_name: str, class_name: str = "") -> List[Dict[str, Any]]:
        """Get all call sites FROM a specific function."""
        return self.call_graph_service.get_call_sites(function_name, class_name)

    def get_call_path(
        self, from_function: str, to_function: str, max_depth: int = 10
    ) -> List[List[str]]:
        """Find call paths from one function to another using BFS."""
        return self.call_graph_service.get_call_path(from_function, to_function, max_depth)

    def find_in_file(self, file_path: str, pattern: str) -> Dict[str, Any]:
        """Search for symbols within a specific file or files matching a glob pattern (delegates to query_engine)."""
        return self.query_engine.find_in_file(file_path, pattern)

    async def get_files_containing_symbol(
        self, symbol_name: str, symbol_kind: Optional[str] = None, project_only: bool = True
    ) -> Dict[str, Any]:
        """Get all files that contain references to or define a symbol (delegates to query_engine)."""
        return await self.query_engine.get_files_containing_symbol(
            symbol_name, symbol_kind, project_only
        )

    def get_parse_errors(
        self, limit: Optional[int] = None, file_path_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get parse errors from the error log (for developer analysis).

        Args:
            limit: Maximum number of errors to return (most recent first)
            file_path_filter: Only return errors for files matching this path

        Returns:
            List of error entries
        """
        return self.cache_manager.get_parse_errors(limit, file_path_filter)

    def get_error_summary(self) -> Dict[str, Any]:
        """Get a summary of parse errors for developer analysis.

        Returns:
            Dict with error statistics and recent errors
        """
        return self.cache_manager.get_error_summary()

    def clear_error_log(self, older_than_days: Optional[int] = None) -> int:
        """Clear the error log, optionally keeping recent errors.

        Args:
            older_than_days: If specified, only clear errors older than this many days

        Returns:
            Number of errors cleared
        """
        return self.cache_manager.clear_error_log(older_than_days)


# Create factory function for compatibility
def create_analyzer(project_root: str) -> CppAnalyzer:
    """Factory function to create a C++ analyzer"""
    return CppAnalyzer(project_root)


# Test function
if __name__ == "__main__":
    diagnostics.debug("Testing Python CppAnalyzer...")
    analyzer = CppAnalyzer(".")

    # Try to load from cache first
    assert analyzer.cache_orchestrator is not None
    if not analyzer.cache_orchestrator._load_cache():
        analyzer.index_project()

    stats = analyzer.get_stats()
    diagnostics.debug(f"Stats: {stats}")

    classes = analyzer.search_classes(".*", project_only=True)
    diagnostics.debug(f"Found {len(classes)} project classes")

    functions = analyzer.search_functions(".*", project_only=True)
    diagnostics.debug(f"Found {len(functions)} project functions")
