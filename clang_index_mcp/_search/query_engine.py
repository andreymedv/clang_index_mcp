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
from .._search.search_criteria import SearchCriteria
from .._search.search_engine import SearchEngine
from .._search.smart_fallback import FallbackResult, SmartFallback
from .._search.template_analyzer import get_derived_classes
from .._search.type_alias_resolver import get_type_alias_info

if TYPE_CHECKING:
    from ..project_context import ProjectContext


class QueryEngine:
    """Manages search queries and analysis operations."""

    def __init__(self, context: "ProjectContext"):
        """
        Initialize query engine.

        Args:
            context: Shared project context with indexes, cache, and compilation services.
        """
        self.context = context
        assert context.symbol_store is not None
        self.symbol_store = context.symbol_store
        assert context.cache_manager is not None
        self.cache_manager = context.cache_manager
        assert context.concurrency is not None
        self.concurrency = context.concurrency
        assert context.compilation_env is not None
        self.compilation_env = context.compilation_env
        assert context.call_graph_service is not None
        self.call_graph_service = context.call_graph_service
        self.project_root = context.project_root
        self.search_engine = SearchEngine(
            symbol_store=self.symbol_store,
            cache_manager=self.cache_manager,
        )
        self.smart_fallback = SmartFallback()
        self._last_fallback: Optional[FallbackResult] = None

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
            if self.context.is_compile_commands_enabled():
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
        return get_type_alias_info(type_name, self.context)

    def find_in_file(self, file_path: str, pattern: str) -> Dict[str, Any]:
        """Search for symbols within a specific file or files matching a glob pattern."""
        return find_in_file(file_path, pattern, self.context, self.search_engine)

    async def get_files_containing_symbol(
        self, symbol_name: str, symbol_kind: Optional[str] = None, project_only: bool = True
    ) -> Dict[str, Any]:
        """Get all files that contain references to or define a symbol."""
        return await get_files_containing_symbol(
            symbol_name, symbol_kind, project_only, self.context
        )

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
