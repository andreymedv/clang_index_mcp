"""
Query engine for search and analysis operations.

Extracted from CppAnalyzer as part of architecture refactoring.
Manages search operations, class hierarchy analysis, type alias queries,
and file-based symbol lookup.
"""

import json
import os
import re
from collections import deque
from fnmatch import fnmatch
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from .search_engine import SearchEngine
from .smart_fallback import FallbackResult, SmartFallback
from .symbol_info import CLASS_KINDS, SymbolInfo, build_location_objects

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
            result["derived_classes"] = self.get_derived_classes(lookup_name, project_only=True)
        return result

    def get_function_signature(
        self, function_name: str, class_name: Optional[str] = None
    ) -> List[str]:
        """Get signature details for functions with given name, optionally within a specific class"""
        return self.search_engine.get_function_signature(function_name, class_name)

    def _process_alias_row(self, row: Any, unique_aliases: Dict[str, Dict[str, Any]]) -> None:
        """Process a single alias row and add to unique_aliases if new."""
        qualified_alias = row["qualified_name"]
        if qualified_alias in unique_aliases:
            return
        alias_dict = {
            "name": row["alias_name"],
            "qualified_name": qualified_alias,
            "file": row["file"],
            "line": row["line"],
        }
        if row["canonical_type"]:
            alias_dict["canonical_type"] = row["canonical_type"]
        if row["namespace"]:
            alias_dict["namespace"] = row["namespace"]
        if row["is_template_alias"]:
            alias_dict["is_template_alias"] = True
            try:
                alias_dict["template_params"] = json.loads(row["template_params"])
            except (json.JSONDecodeError, TypeError):
                pass
        unique_aliases[qualified_alias] = alias_dict

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
                    self._process_alias_row(row, unique_aliases)

            return list(unique_aliases.values())
        except Exception:
            return []

    def _get_info_for_known_alias(self, type_name: str) -> Optional[Dict[str, Any]]:
        """Build info dict for an alias already confirmed in type_aliases table."""
        details = self._get_alias_details_from_db([type_name])
        if details:
            return details[0]
        return None

    def _find_type_matches(self, type_name: str) -> List[SymbolInfo]:
        """Find class/struct symbols matching type_name (exact or qualified)."""
        matches = []
        for symbol_list in self.analyzer.class_index.values():
            for symbol in symbol_list:
                if symbol.name == type_name or symbol.qualified_name == type_name:
                    matches.append(symbol)
        return matches

    def _check_type_ambiguity(
        self, type_name: str, matches: List[SymbolInfo]
    ) -> Optional[Dict[str, Any]]:
        """Check if type_name is ambiguous across multiple definitions."""
        if len(matches) <= 1:
            return None

        unique_files = set()
        for symbol in matches:
            if symbol.file:
                unique_files.add(symbol.file)

        if len(unique_files) <= 1:
            return None

        return {
            "error": f"Type '{type_name}' is ambiguous",
            "message": f"Found {len(matches)} definitions in {len(unique_files)} files",
            "candidates": [
                {"name": s.name, "qualified_name": s.qualified_name, "file": s.file, "line": s.line}
                for s in matches
            ],
        }

    def get_type_alias_info(self, type_name: str) -> Dict[str, Any]:
        """Get type alias information including canonical type resolution."""
        # First check if type_name is a known alias in the database
        alias_info = self._get_info_for_known_alias(type_name)
        if alias_info:
            return alias_info

        # Check if type_name matches a class/struct name
        type_matches = self._find_type_matches(type_name)

        # Check for ambiguity
        ambiguity = self._check_type_ambiguity(type_name, type_matches)
        if ambiguity:
            return ambiguity

        # If type_name is a known class/struct, return its info
        if type_matches:
            symbol = type_matches[0]
            return {
                "name": symbol.name,
                "qualified_name": symbol.qualified_name,
                "file": symbol.file,
                "line": symbol.line,
                "is_type_alias": False,
                "message": f"'{type_name}' is a class/struct, not a type alias",
            }

        # Type not found
        return {"error": f"Type '{type_name}' not found"}

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

    def _is_derived_from(
        self,
        class_symbol: SymbolInfo,
        base_class_name: str,
        visited: Optional[Set[str]] = None,
    ) -> bool:
        """Check if a class derives from a base class (recursive)."""
        if visited is None:
            visited = set()

        # Prevent infinite loops
        class_key = class_symbol.qualified_name or class_symbol.name
        if class_key in visited:
            return False
        visited.add(class_key)

        # Check base_classes field
        if hasattr(class_symbol, "base_classes") and class_symbol.base_classes:
            for base in class_symbol.base_classes:
                # Extract base class name (remove template params and namespace)
                base_name = base.split("<")[0].split("::")[-1].strip()
                if base_name == base_class_name:
                    return True

                # Recursively check if base derives from target
                base_infos = self.analyzer.class_index.get(base_name, [])
                for base_info in base_infos:
                    if self._is_derived_from(base_info, base_class_name, visited):
                        return True

        return False

    def get_derived_classes(
        self, class_name: str, project_only: bool = True
    ) -> List[Dict[str, Any]]:
        """Find all classes that derive from the given class."""
        derived = []
        target_name = class_name.split("::")[-1]  # Extract simple name

        # Search all classes for those that derive from target
        for name, symbols in self.analyzer.class_index.items():
            for symbol in symbols:
                # Skip the target class itself
                if symbol.name == target_name or symbol.qualified_name == class_name:
                    continue

                # Check if this class derives from target
                if self._is_derived_from(symbol, target_name):
                    # Filter by project files if requested
                    if project_only and symbol.file:
                        if not self.analyzer.compilation_env._is_project_file(symbol.file):
                            continue

                    derived.append(
                        {
                            "name": symbol.name,
                            "qualified_name": symbol.qualified_name,
                            "file": symbol.file,
                            "line": symbol.line,
                        }
                    )

        return derived

    def _resolve_base_key(self, raw: str) -> str:
        """Resolve a raw base class string to an index lookup key."""
        name = raw.split("<")[0].strip()
        parts = name.split("::")
        simple = parts[-1]
        candidates = self.analyzer.class_index.get(simple, [])
        if not candidates:
            return simple
        if len(candidates) == 1:
            return candidates[0].qualified_name or simple
        # Multiple candidates: prefer the one whose qualified name ends with raw
        for c in candidates:
            qn = c.qualified_name or ""
            if qn.endswith(name):
                return qn
        # Otherwise, prefer an exact match on raw
        for c in candidates:
            if (c.qualified_name or "") == raw or c.name == raw:
                return c.qualified_name or simple
        return candidates[0].qualified_name or simple

    def _lookup_class_infos(self, key: str) -> List[SymbolInfo]:
        """Look up SymbolInfo list by qualified or simple name."""
        infos = self.analyzer.class_index.get(key, [])
        if infos:
            return infos
        # Fallback: search by qualified_name
        for sym_list in self.analyzer.class_index.values():
            for sym in sym_list:
                if sym.qualified_name == key:
                    return [sym]
        return []

    def _collect_hierarchy_node_data(self, key: str) -> Optional[Dict[str, Any]]:
        """Build the data payload for a hierarchy node."""
        infos = self._lookup_class_infos(key)
        if not infos:
            return None
        info = infos[0]
        node: Dict[str, Any] = {
            "name": info.name,
            "qualified_name": info.qualified_name,
            "file": info.file,
            "line": info.line,
            "locations": build_location_objects(infos),
        }
        base_classes = []
        for base in info.base_classes or []:
            base_clean = base.split("<")[0].strip()
            base_classes.append(base_clean.split("::")[-1])
        if base_classes:
            node["base_classes"] = base_classes
        return node

    def _should_skip_hierarchy_node(self, key: str, project_only: bool, seen: Set[str]) -> bool:
        """Return True if this hierarchy node should be skipped."""
        if key in seen:
            return True
        if project_only:
            infos = self._lookup_class_infos(key)
            if not infos:
                return True
            primary = infos[0]
            if primary.file and not self.analyzer.compilation_env._is_project_file(primary.file):
                return True
        return False

    def _collect_derived_children(
        self, node_key: str, project_only: bool, seen: set, depth: int
    ) -> List[Dict[str, Any]]:
        """Find all classes that derive from the given node and return child nodes."""
        derived_list: List[Dict[str, Any]] = []
        for name, symbols in self.analyzer.class_index.items():
            for symbol in symbols:
                if not symbol.base_classes:
                    continue
                derives = False
                for base in symbol.base_classes:
                    base_resolved = self._resolve_base_key(base)
                    if base_resolved == node_key:
                        derives = True
                        break
                if not derives:
                    continue

                sym_key = symbol.qualified_name or symbol.name
                if self._should_skip_hierarchy_node(sym_key, project_only, seen):
                    continue
                seen.add(sym_key)

                child = self._collect_hierarchy_node_data(sym_key)
                if child:
                    derived_list.append(child)
        return derived_list

    def _bfs_traverse_hierarchy(
        self,
        root_key: str,
        project_only: bool,
        max_depth: int,
    ) -> Dict[str, Any]:
        """BFS traversal of the class hierarchy."""
        root_infos = self._lookup_class_infos(root_key)
        if not root_infos:
            return {"error": f"Class '{root_key}' not found"}

        root_symbol = root_infos[0]
        root_node: Dict[str, Any] = {
            "name": root_symbol.name,
            "qualified_name": root_symbol.qualified_name,
            "file": root_symbol.file,
            "line": root_symbol.line,
            "locations": build_location_objects(root_infos),
        }
        base_classes = []
        for base in root_symbol.base_classes or []:
            base_clean = base.split("<")[0].strip()
            base_classes.append(base_clean.split("::")[-1])
        if base_classes:
            root_node["base_classes"] = base_classes

        seen = {root_symbol.qualified_name or root_symbol.name}
        queue: deque = deque([(root_node, 0)])

        while queue:
            node, depth = queue.popleft()
            if depth >= max_depth:
                continue

            node_key = node.get("qualified_name") or node.get("name", "")
            node_infos = self._lookup_class_infos(node_key)
            if not node_infos:
                continue

            derived_list = self._collect_derived_children(node_key, project_only, seen, depth)
            for child in derived_list:
                queue.append((child, depth + 1))

            if derived_list:
                node["derived_classes"] = derived_list

        return root_node

    def get_class_hierarchy(
        self,
        class_name: str,
        project_only: bool = True,
        max_depth: int = 10,
    ) -> Dict[str, Any]:
        """Get the full class hierarchy tree for a given class."""
        # Find the root class
        simple_name = class_name.split("::")[-1]
        candidates = self.analyzer.class_index.get(simple_name, [])
        if not candidates:
            # Try qualified name search
            for sym_list in self.analyzer.class_index.values():
                for sym in sym_list:
                    if sym.qualified_name == class_name:
                        candidates = [sym]
                        break
                if candidates:
                    break

        if not candidates:
            return {"error": f"Class '{class_name}' not found"}

        # Pick best candidate (prefer exact qualified name match)
        root = candidates[0]
        for c in candidates:
            if c.qualified_name == class_name:
                root = c
                break

        root_key = root.qualified_name or root.name
        return self._bfs_traverse_hierarchy(root_key, project_only, max_depth)

    def _matches_glob(self, indexed_file: str, glob_pattern: str) -> bool:
        """Check if an indexed file path matches a glob pattern."""
        # Normalize separators
        norm_indexed = indexed_file.replace("\\", "/")
        norm_pattern = glob_pattern.replace("\\", "/")
        return fnmatch(norm_indexed, norm_pattern) or fnmatch(
            os.path.basename(norm_indexed), norm_pattern
        )

    def _filter_results_by_files(
        self,
        class_results: List[Dict[str, Any]],
        func_results: List[Dict[str, Any]],
        file_paths: Set[str],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Filter class and function results to only include matches from given files."""
        filtered_classes = []
        for item in class_results:
            locations = item.get("locations", [])
            if any(loc.get("file") in file_paths for loc in locations):
                filtered_classes.append(item)

        filtered_functions = []
        for item in func_results:
            locations = item.get("locations", [])
            if any(loc.get("file") in file_paths for loc in locations):
                filtered_functions.append(item)

        return filtered_classes, filtered_functions

    def _find_in_files_glob(self, glob_pattern: str, symbol_pattern: str) -> Dict[str, Any]:
        """Find symbols in files matching a glob pattern."""
        matching_files: Set[str] = set()
        for file_path in self.analyzer.file_index.keys():
            if self._matches_glob(file_path, glob_pattern):
                matching_files.add(file_path)

        if not matching_files:
            return {
                "classes": [],
                "functions": [],
                "message": f"No files matching '{glob_pattern}' in index",
            }

        # Search all symbols
        class_results = self.search_engine.search_classes(
            symbol_pattern, project_only=False, max_results=None
        )
        if isinstance(class_results, tuple):
            class_results = class_results[0]

        func_results = self.search_engine.search_functions(
            symbol_pattern, project_only=False, max_results=None, include_attributes=True
        )
        if isinstance(func_results, tuple):
            func_results = func_results[0]

        # Filter to matching files
        filtered_classes, filtered_functions = self._filter_results_by_files(
            class_results, func_results, matching_files
        )

        return {
            "classes": filtered_classes,
            "functions": filtered_functions,
            "files_searched": len(matching_files),
        }

    def _find_in_file_exact(self, file_path: str, pattern: str) -> Dict[str, Any]:
        """Find symbols in an exact file path."""
        # Normalize file path
        norm_path = os.path.normpath(file_path)

        # Search in file_index
        symbols = self.analyzer.file_index.get(norm_path, [])
        if not symbols:
            # Try with absolute path
            abs_path = os.path.abspath(norm_path)
            symbols = self.analyzer.file_index.get(abs_path, [])

        if not symbols:
            return {
                "classes": [],
                "functions": [],
                "message": f"No symbols found in '{file_path}'",
            }

        # Filter by pattern
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)

        classes = []
        functions = []
        for symbol in symbols:
            if not regex.search(symbol.name) and not regex.search(symbol.qualified_name or ""):
                continue

            info = {
                "name": symbol.name,
                "qualified_name": symbol.qualified_name,
                "file": symbol.file,
                "line": symbol.line,
            }
            if symbol.kind in CLASS_KINDS:
                classes.append(info)
            else:
                info["prototype"] = symbol.prototype or ""
                if symbol.parent_class:
                    info["parent_class"] = symbol.parent_class
                functions.append(info)

        return {"classes": classes, "functions": functions}

    def find_in_file(self, file_path: str, pattern: str) -> Dict[str, Any]:
        """Find symbols in a specific file or files matching a glob pattern."""
        # Check if file_path contains glob characters
        if any(c in file_path for c in "*?["):
            return self._find_in_files_glob(file_path, pattern)
        else:
            return self._find_in_file_exact(file_path, pattern)

    def _get_path_suggestions(self, partial_path: str, max_suggestions: int = 5) -> List[str]:
        """Get file path suggestions based on partial input."""
        suggestions = []
        partial_lower = partial_path.lower()

        for file_path in self.analyzer.file_index.keys():
            if partial_lower in file_path.lower():
                suggestions.append(file_path)
                if len(suggestions) >= max_suggestions:
                    break

        return suggestions

    def _find_class_definition_files(self, class_name: str, project_only: bool) -> Set[str]:
        """Find files containing class definitions."""
        files = set()
        symbols = self.analyzer.class_index.get(class_name, [])
        for symbol in symbols:
            if symbol.file:
                if project_only and not self.analyzer.compilation_env._is_project_file(symbol.file):
                    continue
                files.add(symbol.file)
        return files

    def _find_function_definition_files(
        self, function_name: str, class_name: Optional[str], project_only: bool
    ) -> Set[str]:
        """Find files containing function definitions."""
        files = set()
        symbols = self.analyzer.function_index.get(function_name, [])
        for symbol in symbols:
            if class_name and symbol.parent_class != class_name:
                continue
            if symbol.file:
                if project_only and not self.analyzer.compilation_env._is_project_file(symbol.file):
                    continue
                files.add(symbol.file)
        return files

    def _find_symbol_definition_files(
        self, symbol_name: str, symbol_kind: Optional[str], project_only: bool
    ) -> Set[str]:
        """Find files containing symbol definitions."""
        files = set()
        if symbol_kind in (None, "class"):
            files.update(self._find_class_definition_files(symbol_name, project_only))
        if symbol_kind in (None, "function"):
            files.update(self._find_function_definition_files(symbol_name, None, project_only))
        return files

    def _find_symbol_caller_files(
        self, symbol_name: str, symbol_kind: Optional[str], project_only: bool
    ) -> Set[str]:
        """Find files containing callers of a symbol."""
        files = set()
        # Use call graph service to find callers
        try:
            incoming = self.analyzer.call_graph_service.find_incoming_calls(
                symbol_name, project_only=project_only
            )
            if incoming:
                for caller in incoming.get("callers", []):
                    caller_file = caller.get("file")
                    if caller_file:
                        if project_only and not self.analyzer.compilation_env._is_project_file(
                            caller_file
                        ):
                            continue
                        files.add(caller_file)
        except Exception:
            pass
        return files

    def _find_class_reference_files(self, class_name: str, project_only: bool) -> Set[str]:
        """Find files that reference a class."""
        files = set()
        # Search for class name in all indexed files
        for file_path, symbols in self.analyzer.file_index.items():
            if project_only and not self.analyzer.compilation_env._is_project_file(file_path):
                continue
            for symbol in symbols:
                # Check if symbol references the class (as type, parameter, etc.)
                if class_name in (symbol.qualified_name or ""):
                    files.add(file_path)
                    break
                # Check prototype for type references
                if symbol.prototype and class_name in symbol.prototype:
                    files.add(file_path)
                    break
        return files
