"""
Query engine for search and analysis operations.

Extracted from CppAnalyzer as part of architecture refactoring.
Manages search operations, class hierarchy analysis, type alias queries,
and file-based symbol lookup.
"""

import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .._search.file_symbol_finder import find_in_file, get_files_containing_symbol
from .._search.hierarchy_analyzer import get_class_hierarchy
from .._search.ports.search_deps import SearchDependencies
from .._search.search_criteria import SearchCriteria
from .._search.search_engine import SearchEngine
from .._search.smart_fallback import FallbackResult, SmartFallback
from .._search.template_analyzer import get_derived_classes
from .._search.type_alias_resolver import get_type_alias_info

if TYPE_CHECKING:
    from pathlib import Path

    from .._compilation.compilation_environment import CompilationEnvironment
    from .._core.concurrency_context import ConcurrencyContext
    from .._persistence.cache_manager import CacheManager
    from .._search.call_graph_service import CallGraphService
    from .._symbols.symbol_index_store import SymbolIndexStore


class QueryEngine:
    """Manages search queries and analysis operations."""

    def __init__(
        self,
        symbol_store: "SymbolIndexStore",
        cache_manager: "CacheManager",
        concurrency: "ConcurrencyContext",
        compilation_env: "CompilationEnvironment",
        call_graph_service: "CallGraphService",
        project_root: "Path",
        search_engine: Optional[SearchEngine] = None,
        smart_fallback: Optional[SmartFallback] = None,
    ):
        """
        Initialize query engine.

        Args:
            symbol_store: In-memory symbol indexes.
            cache_manager: SQLite-backed cache and persistence.
            concurrency: Concurrency context with index_lock.
            compilation_env: Compilation environment for compile args and file scanning.
            call_graph_service: Call graph and dependency tracking.
            project_root: Project root directory.
            search_engine: Optional pre-built SearchEngine instance.
            smart_fallback: Optional pre-built SmartFallback instance.
        """
        self.symbol_store = symbol_store
        self.cache_manager = cache_manager
        self.concurrency = concurrency
        self.compilation_env = compilation_env
        self.call_graph_service = call_graph_service
        self.project_root = project_root
        self.search_engine = search_engine or SearchEngine(
            symbol_store=symbol_store,
            cache_manager=cache_manager,
        )
        self.smart_fallback = smart_fallback or SmartFallback()
        self._last_fallback: Optional[FallbackResult] = None

    def _as_search_deps(self) -> SearchDependencies:
        """Return self as a SearchDependencies-compatible object.

        QueryEngine implements the SearchDependencies protocol, so it can
        pass itself directly to helper functions.
        """
        return self

    def pop_last_fallback(self):
        """Return and clear the last fallback result.

        Called by the MCP server layer to retrieve smart suggestions
        after a search returns empty results.
        """
        result = self._last_fallback
        self._last_fallback = None
        return result

    def search_classes(
        self,
        pattern: str,
        project_only: bool = True,
        file_name: Optional[str] = None,
        namespace: Optional[str] = None,
        max_results: Optional[int] = None,
        include_base_classes: bool = True,
    ):
        """Search for classes matching pattern"""
        from .._core import diagnostics

        self._last_fallback = None
        try:
            criteria = SearchCriteria(
                pattern=pattern,
                project_only=project_only,
                file_name=file_name,
                namespace=namespace,
                max_results=max_results,
                include_base_classes=include_base_classes,
            )
            results = self.search_engine.search_classes(criteria)
            actual = results[0] if isinstance(results, tuple) else results
            if not actual:
                self._last_fallback = self.smart_fallback.analyze_empty_result(
                    pattern=pattern,
                    tool_name="search_classes",
                    symbol_store=self.symbol_store,
                    file_name=file_name,
                    namespace=namespace,
                )
            return results
        except re.error as e:
            diagnostics.error(f"Invalid regex pattern: {e}")
            return []

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
        """Search for functions matching pattern, optionally within a specific class"""
        from .._core import diagnostics

        self._last_fallback = None
        try:
            criteria = SearchCriteria(
                pattern=pattern,
                project_only=project_only,
                class_name=class_name,
                file_name=file_name,
                namespace=namespace,
                max_results=max_results,
                signature_pattern=signature_pattern,
                include_attributes=include_attributes,
            )
            results = self.search_engine.search_functions(criteria)
            actual = results[0] if isinstance(results, tuple) else results
            if not actual:
                self._last_fallback = self.smart_fallback.analyze_empty_result(
                    pattern=pattern,
                    tool_name="search_functions",
                    symbol_store=self.symbol_store,
                    file_name=file_name,
                    namespace=namespace,
                    class_name=class_name,
                )
            return results
        except re.error as e:
            diagnostics.error(f"Invalid regex pattern: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Get indexer statistics"""
        with self.concurrency.index_lock:
            stats: Dict[str, Any] = {
                "class_count": self.symbol_store.total_class_symbols(),
                "function_count": self.symbol_store.total_function_symbols(),
                "file_count": self.symbol_store.indexed_file_count,
            }

            # Add compile commands statistics if enabled
            # Task 3.2: Skip if CompileCommandsManager not initialized (worker mode)
            if self.compilation_env.has_active_compile_commands():
                stats["compile_commands_stats"] = self.compilation_env.get_compile_commands_stats()

            return stats

    def get_class_info(self, class_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific class, including direct derived classes."""
        result = self.search_engine.get_class_info(class_name)
        if result and "error" not in result:
            # Append direct derived classes (project_only=True by default)
            # Use qualified_name for accurate lookup when available
            lookup_name = result.get("qualified_name") or class_name
            result["derived_classes"] = get_derived_classes(
                lookup_name,
                project_only=True,
                symbol_store=self.symbol_store,
                index_lock=self.concurrency.index_lock,
            )
        return result

    def get_function_signature(
        self, function_name: str, class_name: Optional[str] = None
    ) -> List[str]:
        """Get signature details for functions with given name, optionally within a specific class"""
        return self.search_engine.get_function_signature(function_name, class_name)

    def search_symbols(
        self,
        pattern: str,
        project_only: bool = True,
        symbol_types: Optional[List[str]] = None,
        namespace: Optional[str] = None,
        max_results: Optional[int] = None,
        signature_pattern: Optional[str] = None,
    ):
        """Search for all symbols (classes and functions) matching pattern."""
        from .._core import diagnostics

        self._last_fallback = None
        try:
            criteria = SearchCriteria(
                pattern=pattern,
                project_only=project_only,
                symbol_types=symbol_types,
                namespace=namespace,
                max_results=max_results,
                signature_pattern=signature_pattern,
            )
            results = self.search_engine.search_symbols(criteria)
            actual = results[0] if isinstance(results, tuple) else results
            if isinstance(actual, dict):
                count = sum(len(v) for v in actual.values() if isinstance(v, list))
            else:
                count = len(actual) if actual else 0
            if count == 0:
                self._last_fallback = self.smart_fallback.analyze_empty_result(
                    pattern=pattern,
                    tool_name="search_symbols",
                    symbol_store=self.symbol_store,
                    namespace=namespace,
                )
            return results
        except re.error as e:
            diagnostics.error(f"Invalid regex pattern: {e}")
            return {"classes": [], "functions": []}

    def get_type_alias_info(self, type_name: str) -> Dict[str, Any]:
        """Get comprehensive type alias information."""
        return get_type_alias_info(type_name, self)

    def find_in_file(self, file_path: str, pattern: str) -> Dict[str, Any]:
        """Search for symbols within a specific file or files matching a glob pattern."""
        return find_in_file(file_path, pattern, self, self.search_engine)

    async def get_files_containing_symbol(
        self, symbol_name: str, symbol_kind: Optional[str] = None, project_only: bool = True
    ) -> Dict[str, Any]:
        """Get all files that contain references to or define a symbol."""
        return await get_files_containing_symbol(symbol_name, symbol_kind, project_only, self)

    def _check_template_param_inheritance(self, base_class: str, target_class: str) -> bool:
        """Check if a class indirectly inherits from target_class through template parameter inheritance."""
        from .._search import template_analyzer

        return template_analyzer.check_template_param_inheritance(
            base_class, target_class, self.symbol_store, self.concurrency.index_lock
        )

    def _get_template_param_inheritance_indices(self, template_name: str) -> List[int]:
        """Get the template parameter indices that a template inherits from."""
        from .._search import template_analyzer

        return template_analyzer.get_template_param_inheritance_indices(
            template_name, self.symbol_store, self.concurrency.index_lock
        )

    def _parse_template_args(self, args_str: str) -> List[str]:
        """Parse template arguments from a string like 'A, B<C, D>, E'."""
        from .._search import template_analyzer

        return template_analyzer.parse_template_args(args_str)

    def get_derived_classes(
        self, class_name: str, project_only: bool = True
    ) -> List[Dict[str, Any]]:
        """Get all classes that derive from the given class."""
        return get_derived_classes(
            class_name,
            project_only=project_only,
            symbol_store=self.symbol_store,
            index_lock=self.concurrency.index_lock,
        )

    def get_class_hierarchy(
        self,
        class_name: str,
        max_nodes: Optional[int] = 200,
        max_depth: Optional[int] = None,
        direction: str = "both",
    ) -> Dict[str, Any]:
        """Get the inheritance graph for a class as a flat adjacency list."""
        return get_class_hierarchy(
            class_name,
            max_nodes=max_nodes,
            max_depth=max_depth,
            direction=direction,
            symbol_store=self.symbol_store,
            index_lock=self.concurrency.index_lock,
        )
