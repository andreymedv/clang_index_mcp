"""
Query engine for search and analysis operations.

Extracted from CppAnalyzer as part of architecture refactoring.
Manages search operations, class hierarchy analysis, type alias queries,
and file-based symbol lookup.
"""

import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .search_engine import SearchEngine
from .smart_fallback import FallbackResult, SmartFallback

if TYPE_CHECKING:
    from .cpp_analyzer import CppAnalyzer


class QueryEngine:
    """Manages search queries and analysis operations."""

    def __init__(self, analyzer: "CppAnalyzer"):
        """
        Initialize query engine.

        Args:
            analyzer: Reference to the CppAnalyzer instance
        """
        self.analyzer = analyzer
        self.search_engine = SearchEngine(
            analyzer.symbol_store.class_index,
            analyzer.symbol_store.function_index,
            analyzer.symbol_store.file_index,
            analyzer.symbol_store.usr_index,
            analyzer.index_lock,
            cache_manager=analyzer.cache_manager,
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
        from . import diagnostics

        self._last_fallback = None
        try:
            results = self.search_engine.search_classes(
                pattern, project_only, file_name, namespace, max_results, include_base_classes
            )
            actual = results[0] if isinstance(results, tuple) else results
            if not actual:
                self._last_fallback = self.smart_fallback.analyze_empty_result(
                    pattern=pattern,
                    tool_name="search_classes",
                    class_index=self.analyzer.class_index,
                    function_index=self.analyzer.function_index,
                    file_index=self.analyzer.file_index,
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
        from . import diagnostics

        self._last_fallback = None
        try:
            results = self.search_engine.search_functions(
                pattern,
                project_only,
                class_name,
                file_name,
                namespace,
                max_results,
                signature_pattern,
                include_attributes,
            )
            actual = results[0] if isinstance(results, tuple) else results
            if not actual:
                self._last_fallback = self.smart_fallback.analyze_empty_result(
                    pattern=pattern,
                    tool_name="search_functions",
                    class_index=self.analyzer.class_index,
                    function_index=self.analyzer.function_index,
                    file_index=self.analyzer.file_index,
                    file_name=file_name,
                    namespace=namespace,
                    class_name=class_name,
                )
            return results
        except re.error as e:
            diagnostics.error(f"Invalid regex pattern: {e}")
            return []

    def get_stats(self) -> Dict[str, int]:
        """Get indexer statistics"""
        with self.analyzer.index_lock:
            # Count total symbols (not just unique names)
            class_count = sum(len(infos) for infos in self.analyzer.class_index.values())
            function_count = sum(len(infos) for infos in self.analyzer.function_index.values())

            stats = {
                "class_count": class_count,
                "function_count": function_count,
                "file_count": self.analyzer.indexed_file_count,
            }

            # Add compile commands statistics if enabled
            # Task 3.2: Skip if CompileCommandsManager not initialized (worker mode)
            if (
                self.analyzer.compile_commands_manager is not None
                and self.analyzer.compile_commands_manager.enabled
            ):
                stats["compile_commands_stats"] = (
                    self.analyzer.compilation_env.get_compile_commands_stats()
                )

            return stats

    def get_class_info(self, class_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific class, including direct derived classes."""
        result = self.search_engine.get_class_info(class_name)
        if result and "error" not in result:
            # Append direct derived classes (project_only=True by default)
            # Use qualified_name for accurate lookup when available
            lookup_name = result.get("qualified_name") or class_name
            result["derived_classes"] = self.analyzer.get_derived_classes(
                lookup_name, project_only=True
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
        from . import diagnostics

        self._last_fallback = None
        try:
            results = self.search_engine.search_symbols(
                pattern,
                project_only,
                symbol_types,
                namespace,
                max_results,
                signature_pattern,
            )
            actual = results[0] if isinstance(results, tuple) else results
            if isinstance(actual, dict):
                count = sum(len(v) for v in actual.values() if isinstance(v, list))
            else:
                count = len(actual) if actual else 0
            if count == 0:
                self._last_fallback = self.smart_fallback.analyze_empty_result(
                    pattern=pattern,
                    tool_name="search_symbols",
                    class_index=self.analyzer.class_index,
                    function_index=self.analyzer.function_index,
                    file_index=self.analyzer.file_index,
                    namespace=namespace,
                )
            return results
        except re.error as e:
            diagnostics.error(f"Invalid regex pattern: {e}")
            return {"classes": [], "functions": []}
