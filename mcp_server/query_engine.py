"""
Query engine for search and analysis operations.

Extracted from CppAnalyzer as part of architecture refactoring.
Manages search operations, class hierarchy analysis, type alias queries,
and file-based symbol lookup.
"""

import json
import re
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from .search_engine import SearchEngine
from .smart_fallback import FallbackResult, SmartFallback
from .symbol_info import SymbolInfo, build_location_objects, omit_empty

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

    def find_in_file(self, file_path: str, pattern: str) -> Dict[str, Any]:
        """Search for symbols within a specific file or files matching a glob pattern."""
        glob_chars = set("*?[]")
        is_glob = any(c in file_path for c in glob_chars)

        if is_glob:
            return self._find_in_files_glob(file_path, pattern)
        else:
            return self._find_in_file_exact(file_path, pattern)

    def _matches_glob(self, indexed_file: str, glob_pattern: str) -> bool:
        """Check if an indexed file matches a glob pattern using multiple strategies."""
        if fnmatch(indexed_file, glob_pattern):
            return True
        if fnmatch(indexed_file, "**/" + glob_pattern):
            return True
        if self.analyzer.project_root:
            try:
                rel_path = str(Path(indexed_file).relative_to(self.analyzer.project_root))
                return fnmatch(rel_path, glob_pattern)
            except ValueError:
                pass
        return False

    def _filter_results_by_files(
        self, items: List[Dict[str, Any]], matched_files: set
    ) -> List[Dict[str, Any]]:
        """Filter search results to only include items from specified files."""
        results = []
        for item in items:
            _item_loc = item.get("definition") or item.get("declaration") or {}
            item_file = _item_loc.get("file") or item.get("file", "")
            if item_file in matched_files:
                results.append(item)
        return results

    def _find_in_files_glob(self, glob_pattern: str, symbol_pattern: str) -> Dict[str, Any]:
        """Search for symbols in files matching a glob pattern."""
        matched_files = [
            f for f in self.analyzer.file_index.keys() if self._matches_glob(f, glob_pattern)
        ]

        if not matched_files:
            return {
                "results": [],
                "matched_files": [],
                "suggestions": self._get_path_suggestions(glob_pattern),
                "message": f"No files found matching glob pattern '{glob_pattern}'",
            }

        all_classes = self.search_engine.search_classes(
            symbol_pattern, project_only=False, max_results=None
        )
        if isinstance(all_classes, tuple):
            all_classes = all_classes[0]

        all_functions = self.search_engine.search_functions(
            symbol_pattern, project_only=False, max_results=None
        )
        if isinstance(all_functions, tuple):
            all_functions = all_functions[0]

        matched_files_set = set(matched_files)
        results = self._filter_results_by_files(all_classes + all_functions, matched_files_set)

        return {
            "results": results,
            "matched_files": sorted(matched_files),
            "message": f"Found {len(results)} symbols in {len(matched_files)} files matching '{glob_pattern}'",
        }

    def _resolve_file_path(self, file_path: str) -> Optional[str]:
        """Resolve a file path to absolute path for matching."""
        if Path(file_path).is_absolute():
            return str(Path(file_path).resolve())
        if self.analyzer.project_root:
            potential_path = Path(self.analyzer.project_root) / file_path
            if potential_path.exists():
                return str(potential_path.resolve())
        return None

    def _match_item_to_file(
        self, item: Dict[str, Any], file_path: str, abs_file_path: Optional[str]
    ) -> bool:
        """Check if a search result item belongs to the given file."""
        _item_loc = item.get("definition") or item.get("declaration") or {}
        item_file = _item_loc.get("file") or item.get("file", "")
        if not item_file:
            return False

        item_abs = str(Path(item_file).resolve()) if item_file else ""

        if abs_file_path and item_abs == abs_file_path:
            return True
        if item_file.endswith(file_path) or item_abs.endswith(file_path):
            return True
        return False

    def _find_in_file_exact(self, file_path: str, pattern: str) -> Dict[str, Any]:
        """Search for symbols in a specific file (exact or suffix match)."""
        results = []
        matched_file = None

        all_classes = self.search_engine.search_classes(
            pattern, project_only=False, max_results=None
        )
        if isinstance(all_classes, tuple):
            all_classes = all_classes[0]

        all_functions = self.search_engine.search_functions(
            pattern, project_only=False, max_results=None
        )
        if isinstance(all_functions, tuple):
            all_functions = all_functions[0]

        abs_file_path = self._resolve_file_path(file_path)

        for item in all_classes + all_functions:
            if self._match_item_to_file(item, file_path, abs_file_path):
                results.append(item)
                _item_loc = item.get("definition") or item.get("declaration") or {}
                matched_file = _item_loc.get("file") or item.get("file", "")

        if results:
            return {
                "results": results,
                "matched_files": [matched_file] if matched_file else [],
                "message": f"Found {len(results)} symbols in '{file_path}'",
            }
        else:
            suggestions = self._get_path_suggestions(file_path)
            return {
                "results": [],
                "matched_files": [],
                "suggestions": suggestions,
                "message": f"No file found matching '{file_path}'. See suggestions for similar paths.",
            }

    def _get_path_suggestions(self, partial_path: str, max_suggestions: int = 5) -> List[str]:
        """Get suggestions for similar file paths based on partial input."""
        suggestions = []
        partial_lower = partial_path.lower()
        partial_basename = Path(partial_path).name.lower()
        path_parts = [p.lower() for p in Path(partial_path).parts if p]

        for indexed_file in self.analyzer.file_index.keys():
            indexed_lower = indexed_file.lower()
            indexed_basename = Path(indexed_file).name.lower()

            score = 0

            if indexed_basename == partial_basename:
                score += 100
            elif partial_basename in indexed_basename:
                score += 50
            elif partial_lower in indexed_lower:
                score += 30

            for part in path_parts:
                if part in indexed_lower:
                    score += 10

            if score > 0:
                suggestions.append((score, indexed_file))

        suggestions.sort(key=lambda x: (-x[0], x[1]))
        return [path for _, path in suggestions[:max_suggestions]]

    async def get_files_containing_symbol(
        self, symbol_name: str, symbol_kind: Optional[str] = None, project_only: bool = True
    ) -> Dict[str, Any]:
        """Get all files that contain references to or define a symbol."""
        files: Set[str] = set()
        total_refs = 0
        kind = None

        simple_name = symbol_name.split("::")[-1]

        with self.analyzer.index_lock:
            kind = self._find_symbol_definition_files(
                symbol_name, symbol_kind, simple_name, project_only, files
            )

            total_refs = self._find_symbol_caller_files(
                symbol_name, symbol_kind, simple_name, project_only, kind, files
            )

            self._find_class_reference_files(symbol_name, symbol_kind, project_only, kind, files)

        file_list = sorted(list(files))

        if total_refs == 0:
            total_refs = len(file_list)

        return {
            "symbol": symbol_name,
            "kind": kind,
            "files": file_list,
            "total_references": total_refs,
        }

    def _find_class_definition_files(
        self,
        symbol_name: str,
        symbol_kind: Optional[str],
        simple_name: str,
        project_only: bool,
        files: Set[str],
    ) -> Optional[str]:
        """Find files where the class is defined and return its kind."""
        if symbol_kind in (None, "class"):
            for info in self.analyzer.class_index.get(simple_name, []):
                if SearchEngine.matches_qualified_pattern(
                    info.qualified_name or info.name, symbol_name
                ):
                    if not project_only or info.is_project:
                        files.add(info.file)
                        if info.header_file:
                            files.add(info.header_file)
                        return info.kind
        return None

    def _find_function_definition_files(
        self,
        symbol_name: str,
        symbol_kind: Optional[str],
        simple_name: str,
        project_only: bool,
        files: Set[str],
    ) -> Optional[str]:
        """Find files where the function/method is defined and return its kind."""
        kind = None
        if symbol_kind in (None, "function", "method"):
            for info in self.analyzer.function_index.get(simple_name, []):
                if SearchEngine.matches_qualified_pattern(
                    info.qualified_name or info.name, symbol_name
                ):
                    if not project_only or info.is_project:
                        files.add(info.file)
                        if info.header_file:
                            files.add(info.header_file)
                        if not kind:
                            kind = info.kind
        return kind

    def _find_symbol_definition_files(
        self,
        symbol_name: str,
        symbol_kind: Optional[str],
        simple_name: str,
        project_only: bool,
        files: Set[str],
    ) -> Optional[str]:
        """Find files where the symbol is defined and return the first found kind."""
        kind = self._find_class_definition_files(
            symbol_name, symbol_kind, simple_name, project_only, files
        )

        func_kind = self._find_function_definition_files(
            symbol_name, symbol_kind, simple_name, project_only, files
        )

        return kind or func_kind

    def _find_symbol_caller_files(
        self,
        symbol_name: str,
        symbol_kind: Optional[str],
        simple_name: str,
        project_only: bool,
        kind: Optional[str],
        files: Set[str],
    ) -> int:
        """Find files that call the symbol and return the reference count."""
        total_refs = 0
        if kind in ("function", "method") or (
            not kind and symbol_kind in (None, "function", "method")
        ):

            def _name_matches(info) -> bool:
                return SearchEngine.matches_qualified_pattern(
                    info.qualified_name or info.name, symbol_name
                )

            target_usrs = set()
            for info in self.analyzer.function_index.get(simple_name, []):
                if _name_matches(info) and info.usr:
                    if not project_only or info.is_project:
                        target_usrs.add(info.usr)

            for usr in target_usrs:
                callers = self.analyzer.call_graph_analyzer.find_incoming_calls(usr)
                for caller_usr in callers:
                    if caller_usr in self.analyzer.usr_index:
                        caller_info = self.analyzer.usr_index[caller_usr]
                        if not project_only or caller_info.is_project:
                            files.add(caller_info.file)
                            total_refs += 1
        return total_refs

    def _find_class_reference_files(
        self,
        symbol_name: str,
        symbol_kind: Optional[str],
        project_only: bool,
        kind: Optional[str],
        files: Set[str],
    ) -> None:
        """Find files that reference a class and add them to the set."""
        if kind in ("class", "struct") or (not kind and symbol_kind in (None, "class")):
            for file_path, symbols in self.analyzer.file_index.items():
                if not project_only or self.analyzer.compilation_env._is_project_file(file_path):
                    for symbol in symbols:
                        sym_qname = symbol.qualified_name or symbol.name
                        parent_qname = symbol.parent_class or ""
                        if SearchEngine.matches_qualified_pattern(
                            sym_qname, symbol_name
                        ) or SearchEngine.matches_qualified_pattern(parent_qname, symbol_name):
                            files.add(file_path)
                            break

    def _check_template_param_inheritance(self, base_class: str, target_class: str) -> bool:
        """
        Check if a class indirectly inherits from target_class through template
        parameter inheritance.

        Issue: cplusplus_mcp-hnj

        Example:
            If Template<T> inherits from T, and a class has base_class="Template<BaseClass>",
            then it indirectly inherits from BaseClass.

        Args:
            base_class: The base class string (e.g., "ns::Template<ns::BaseClass>")
            target_class: The class we're looking for (e.g., "ns::BaseClass" or "BaseClass")

        Returns:
            True if there's indirect inheritance through template parameters
        """
        # Quick check: if no template instantiation, no indirect inheritance possible
        if "<" not in base_class:
            return False

        # Parse the template instantiation
        # Format: "ns::Template<arg1, arg2, ...>" or "Template<arg>"
        bracket_pos = base_class.find("<")
        if bracket_pos == -1:
            return False

        template_name = base_class[:bracket_pos]
        args_str = base_class[bracket_pos + 1 : -1]  # Remove < and >

        # Find which parameter indices the template inherits from
        # Look up the template in class_index and check its base_classes for type-parameter-X-Y
        param_indices = self._get_template_param_inheritance_indices(template_name)

        if not param_indices:
            return False

        # Parse template arguments (handle nested templates)
        template_args = self._parse_template_args(args_str)

        # Check if any of the inherited-from parameter positions match target_class
        for param_idx in param_indices:
            if param_idx < len(template_args):
                arg = template_args[param_idx]
                # Check if the argument matches target_class
                # Handle both qualified and simple names
                if arg == target_class:
                    return True
                # Check if target_class is the simple name of arg
                if "::" in arg and arg.endswith("::" + target_class):
                    return True
                # Check if arg is the simple name of target_class
                if "::" in target_class and target_class.endswith("::" + arg):
                    return True
                # Check simple name match
                arg_simple = arg.split("::")[-1] if "::" in arg else arg
                target_simple = (
                    target_class.split("::")[-1] if "::" in target_class else target_class
                )
                if arg_simple == target_simple:
                    return True

        return False

    def _get_template_param_inheritance_indices(self, template_name: str) -> List[int]:
        """
        Get the template parameter indices that a template inherits from.

        Looks up the template in class_index and analyzes its base_classes
        to find which template parameters are used as base classes.

        Supports two formats:
        1. Parameter names (new format): base_classes = ['T', 'BaseType']
        2. Legacy format: base_classes = ['type-parameter-0-0'] (for backward compatibility)

        Args:
            template_name: The template name (e.g., "ns::TemplateInheritsParam")

        Returns:
            List of parameter indices that are used as base classes.
            E.g., [0] means the template inherits from its first parameter.
        """
        simple_name = template_name.split("::")[-1] if "::" in template_name else template_name

        param_indices = []
        with self.analyzer.index_lock:
            infos = self.analyzer.class_index.get(simple_name, [])
            for info in infos:
                if info.kind != "class_template":
                    continue
                if not self._template_info_matches_name(info, template_name):
                    continue

                param_name_to_index = self._build_param_name_to_index(info.template_parameters)
                for base in info.base_classes:
                    param_index = self._resolve_param_index(base, param_name_to_index)
                    if param_index is not None and param_index not in param_indices:
                        param_indices.append(param_index)

        return param_indices

    @staticmethod
    def _template_info_matches_name(info, template_name: str) -> bool:
        """Check if a class info matches the requested template name."""
        if "::" not in template_name:
            return True
        info_qualified = info.qualified_name if info.qualified_name else info.name
        return SearchEngine.matches_qualified_pattern(info_qualified, template_name)

    @staticmethod
    def _build_param_name_to_index(template_parameters: Optional[str]) -> Dict[str, int]:
        """Build a mapping from template parameter names to their indices."""
        import json

        param_name_to_index: Dict[str, int] = {}
        if not template_parameters:
            return param_name_to_index

        try:
            params = json.loads(template_parameters)
            for i, param in enumerate(params):
                param_name = param.get("name", "")
                if param_name:
                    param_name_to_index[param_name] = i
        except (json.JSONDecodeError, TypeError):
            pass

        return param_name_to_index

    @staticmethod
    def _resolve_param_index(base: str, param_name_to_index: Dict[str, int]) -> Optional[int]:
        """Resolve a base class name to a template parameter index if applicable."""
        import re

        if base in param_name_to_index:
            return param_name_to_index[base]

        match = re.match(r"type-parameter-(\d+)-(\d+)", base)
        if match:
            return int(match.group(2))

        return None

    def _parse_template_args(self, args_str: str) -> List[str]:
        """
        Parse template arguments from a string like "A, B<C, D>, E".

        Handles nested templates by tracking bracket depth.

        Args:
            args_str: The string inside template brackets (without < and >)

        Returns:
            List of template argument strings
        """
        args = []
        current_arg = ""
        depth = 0

        for char in args_str:
            if char == "<":
                depth += 1
                current_arg += char
            elif char == ">":
                depth -= 1
                current_arg += char
            elif char == "," and depth == 0:
                args.append(current_arg.strip())
                current_arg = ""
            else:
                current_arg += char

        if current_arg.strip():
            args.append(current_arg.strip())

        return args

    def _get_template_patterns(self, simple_name: str) -> List[str]:
        """Get template patterns for matching derived classes."""
        template_patterns = []
        with self.analyzer.index_lock:
            # Check if class_name exists in class_index (use simple_name for lookup)
            if simple_name in self.analyzer.class_index:
                for symbol in self.analyzer.class_index[simple_name]:
                    # If any symbol is a template, get all specializations
                    if symbol.kind in ("class_template", "partial_specialization"):
                        # Build patterns to match in base_classes
                        # Matches: "Container", "Container<int>", "Container<double>", etc.
                        # Use simple_name since base_classes matching uses suffix matching
                        template_patterns.append(simple_name)  # Exact match
                        template_patterns.append(
                            f"{simple_name}<"
                        )  # Prefix match for specializations
                        break  # Only need to detect template once

            # If not a template, just use exact match (use simple_name for matching)
            if not template_patterns:
                template_patterns = [simple_name]
        return template_patterns

    @staticmethod
    def _check_pattern_match(base_class: str, template_patterns: List[str]) -> bool:
        """Check if base_class matches any of the template patterns."""
        for pattern in template_patterns:
            # Exact match or template specialization prefix match
            if base_class == pattern or base_class.startswith(pattern):
                return True
            # Handle qualified names: "ns::BaseClass" should match "BaseClass"
            # Check if base_class ends with "::pattern" or "::pattern<"
            if "::" in base_class:
                if base_class.endswith("::" + pattern):
                    return True
                if base_class.split("::")[-1].startswith(pattern):
                    return True
        return False

    def _is_derived_from(
        self, info: SymbolInfo, template_patterns: List[str], simple_name: str
    ) -> bool:
        """Check if a symbol inherits from the target class or any specialization."""
        tparam_names: set = set()
        if info.template_parameters:
            try:
                tparams = json.loads(info.template_parameters)
                tparam_names = {p.get("name", "") for p in tparams if p.get("name")}
            except (json.JSONDecodeError, TypeError):
                pass

        for base_class in info.base_classes:
            # Skip base classes that are template parameters
            if base_class in tparam_names:
                continue

            match_found = self._check_pattern_match(base_class, template_patterns)

            # Issue cplusplus_mcp-hnj: Check for indirect inheritance
            # through template parameters
            if not match_found:
                match_found = self._check_template_param_inheritance(base_class, simple_name)

            if match_found:
                return True
        return False

    def get_derived_classes(
        self, class_name: str, project_only: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get all classes that derive from the given class.

        Issue #99 Phase 3: Template-aware derived class queries
        If class_name is a template, finds classes derived from ANY specialization:
        - Container → finds classes derived from Container<T>, Container<int>, Container<double>, etc.
        - Enables CRTP pattern discovery

        Args:
            class_name: Name of the base class (can be template name)
            project_only: Only include project classes (exclude dependencies)

        Returns:
            List of classes that inherit from the given class or any of its specializations
        """
        derived_classes = []

        # Normalize class_name: extract simple name from qualified name
        # class_index is keyed by simple name, but users may pass qualified names
        # (e.g., "myapp::builders::Widget" → "Widget")
        simple_name = SearchEngine._extract_simple_name(class_name)

        # Issue #99 Phase 3: Check if this is a template and get all specializations
        template_patterns = self._get_template_patterns(simple_name)

        with self.analyzer.index_lock:
            for name, infos in self.analyzer.class_index.items():
                for info in infos:
                    if not project_only or info.is_project:
                        if self._is_derived_from(info, template_patterns, simple_name):
                            derived_classes.append(
                                omit_empty(
                                    {
                                        "qualified_name": info.qualified_name or info.name,
                                        "kind": info.kind,
                                        "is_project": info.is_project,
                                        "base_classes": info.base_classes,
                                        **build_location_objects(info),
                                    }
                                )
                            )

        return derived_classes
