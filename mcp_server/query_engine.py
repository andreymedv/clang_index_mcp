"""
Query engine for search and analysis operations.

Extracted from CppAnalyzer as part of architecture refactoring.
Manages search operations, class hierarchy analysis, type alias queries,
and file-based symbol lookup.
"""

import json
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .search_engine import SearchEngine
from .smart_fallback import FallbackResult, SmartFallback
from .symbol_info import SymbolInfo

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

    def _get_alias_details_from_db(self, alias_names: List[str]) -> List[Dict[str, Any]]:
        """Query type_aliases table for detailed information about a set of aliases."""
        unique_aliases: Dict[str, Dict[str, Any]] = {}
        try:
            self.analyzer.cache_manager.backend._ensure_connected()
            conn = self.analyzer.cache_manager.backend.conn
            assert conn is not None

            for alias_name in alias_names:
                cursor = conn.execute(
                    """
                    SELECT alias_name, qualified_name, canonical_type, file, line, namespace,
                           is_template_alias, template_params
                    FROM type_aliases
                    WHERE alias_name = ? OR qualified_name = ?
                    """,
                    (alias_name, alias_name),
                )
                row = cursor.fetchone()
                if row:
                    qualified_alias = row["qualified_name"]
                    if qualified_alias not in unique_aliases:
                        alias_dict = {
                            "name": row["alias_name"],
                            "qualified_name": qualified_alias,
                            "file": row["file"],
                            "line": row["line"],
                        }
                        if row["is_template_alias"]:
                            alias_dict["is_template_alias"] = True
                            if row["template_params"]:
                                alias_dict["template_params"] = json.loads(row["template_params"])
                        unique_aliases[qualified_alias] = alias_dict
        except Exception as e:
            from . import diagnostics

            diagnostics.debug(f"Failed to get alias details: {e}")
        return list(unique_aliases.values())

    def _get_info_for_known_alias(self, type_name: str) -> Optional[Dict[str, Any]]:
        """Attempt to get type alias info from the database if type_name is a known alias."""
        try:
            self.analyzer.cache_manager.backend._ensure_connected()
            conn = self.analyzer.cache_manager.backend.conn
            assert conn is not None
            cursor = conn.execute(
                """
                SELECT alias_name, qualified_name, canonical_type, file, line, namespace,
                       is_template_alias, template_params
                FROM type_aliases
                WHERE alias_name = ? OR qualified_name = ?
                """,
                (type_name, type_name),
            )
            row = cursor.fetchone()
            if row:
                alias_names = self.analyzer.cache_manager.get_aliases_for_canonical(
                    row["canonical_type"]
                )
                aliases = self._get_alias_details_from_db(alias_names)

                return {
                    "canonical_type": row["canonical_type"],
                    "qualified_name": row["qualified_name"],
                    "namespace": row["namespace"],
                    "file": row["file"],
                    "line": row["line"],
                    "input_was_alias": True,
                    "is_ambiguous": False,
                    "aliases": aliases,
                }
        except Exception as e:
            from . import diagnostics

            diagnostics.warning(f"Error querying type_aliases for '{type_name}': {e}")
        return None

    def _find_type_matches(self, type_name: str) -> List[SymbolInfo]:
        """Search class index for matching types and return list of matches."""
        matches = []
        with self.analyzer.index_lock:
            for name, infos in self.analyzer.class_index.items():
                for info in infos:
                    qualified_name = info.qualified_name if info.qualified_name else info.name
                    if SearchEngine.matches_qualified_pattern(qualified_name, type_name):
                        matches.append(info)
        return matches

    def _check_type_ambiguity(
        self, type_name: str, matches: List[SymbolInfo]
    ) -> Optional[Dict[str, Any]]:
        """Check for ambiguity among matches and return error dict if ambiguous."""
        if len(matches) > 1:
            unique_qualified_names = set(
                m.qualified_name if m.qualified_name else m.name for m in matches
            )
            if len(unique_qualified_names) > 1:
                return {
                    "error": f"Ambiguous type name '{type_name}'",
                    "is_ambiguous": True,
                    "matches": [
                        {
                            "canonical_type": m.name,
                            "qualified_name": m.qualified_name if m.qualified_name else m.name,
                            "namespace": m.namespace,
                            "file": m.file,
                            "line": m.line,
                        }
                        for m in matches
                    ],
                    "suggestion": "Use qualified name (e.g., 'ui::Widget')",
                }
        return None

    def get_type_alias_info(self, type_name: str) -> Dict[str, Any]:
        """Get comprehensive type alias information."""
        input_canonical = self.analyzer.cache_manager.get_canonical_for_alias(type_name)
        input_was_alias = False

        if input_canonical:
            input_was_alias = True
            info = self._get_info_for_known_alias(type_name)
            if info:
                return info

        matches = self._find_type_matches(type_name)

        ambiguity_error = self._check_type_ambiguity(type_name, matches)
        if ambiguity_error:
            return ambiguity_error

        if len(matches) == 0:
            return {
                "error": f"Type '{type_name}' not found",
                "canonical_type": None,
                "aliases": [],
            }

        canonical_info = matches[0]
        for m in matches:
            if m.is_definition:
                canonical_info = m
                break

        canonical_type = (
            canonical_info.qualified_name if canonical_info.qualified_name else canonical_info.name
        )

        alias_names = self.analyzer.cache_manager.get_aliases_for_canonical(canonical_type)
        aliases = self._get_alias_details_from_db(alias_names) if alias_names else []

        return {
            "canonical_type": canonical_type,
            "qualified_name": (
                canonical_info.qualified_name
                if canonical_info.qualified_name
                else canonical_info.name
            ),
            "namespace": canonical_info.namespace,
            "file": canonical_info.file,
            "line": canonical_info.line,
            "input_was_alias": input_was_alias,
            "is_ambiguous": False,
            "aliases": aliases,
        }
