"""Search functionality for C++ symbols."""

import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union, cast

from .._core.regex_validator import RegexValidator
from .._search.search_criteria import SearchCriteria
from .._symbols.model import (
    SymbolInfo,
    build_location_objects,
    get_template_param_base_indices,
    is_richer_definition,
    omit_empty,
)
from .pattern_matcher import detect_pattern_type, matches_qualified_pattern
from .prototype_builder import build_attributes, build_class_prototype, build_function_prototype
from .symbol_name_utils import extract_simple_name, strip_template_args

if TYPE_CHECKING:
    from .._symbols.symbol_index_store import SymbolIndexStore


class SearchEngine:
    """Handles searching for C++ symbols."""

    symbol_store: Optional["SymbolIndexStore"]

    def __init__(
        self,
        class_index: Optional[Dict[str, List[SymbolInfo]]] = None,
        function_index: Optional[Dict[str, List[SymbolInfo]]] = None,
        file_index: Optional[Dict[str, List[SymbolInfo]]] = None,
        usr_index: Optional[Dict[str, SymbolInfo]] = None,
        index_lock: Optional[threading.RLock] = None,
        cache_manager=None,  # Phase 1.3: Type Alias Tracking support
        symbol_store: Optional["SymbolIndexStore"] = None,
    ):
        if symbol_store is not None:
            self.symbol_store = symbol_store
            self.class_index = symbol_store.class_index
            self.function_index = symbol_store.function_index
            self.file_index = symbol_store.file_index
            self.usr_index = symbol_store.usr_index
            self.index_lock = index_lock or symbol_store.index_lock
        else:
            assert class_index is not None
            assert function_index is not None
            assert file_index is not None
            assert usr_index is not None
            assert index_lock is not None
            self.symbol_store = None
            self.class_index = class_index
            self.function_index = function_index
            self.file_index = file_index
            self.usr_index = usr_index
            self.index_lock = index_lock
        self.cache_manager = cache_manager  # Phase 1.3: For alias lookups

    def _resolve_specialization_of(self, primary_template_usr: Optional[str]) -> Optional[str]:
        """
        Resolve primary template USR to its qualified name for LLM-friendly output.

        Instead of exposing cryptic USRs like 'c:@N@NS@ST>1#T@Template',
        returns the human-readable qualified name like 'NS::Template'.

        Args:
            primary_template_usr: USR of the primary template

        Returns:
            Qualified name of the primary template, or None if not found/not a specialization
        """
        if not primary_template_usr:
            return None

        with self.index_lock:
            if self.symbol_store is not None:
                primary_info = self.symbol_store.get_symbol_by_usr(primary_template_usr)
            else:
                primary_info = self.usr_index.get(primary_template_usr)
            if primary_info:
                return cast(str, primary_info.qualified_name or primary_info.name)
        return None

    @staticmethod
    def _matches_namespace(symbol_namespace: str, filter_namespace: str) -> bool:
        """Check if symbol's namespace matches the filter namespace.

        Supports partial namespace matching: filter "builders" will match
        symbol namespace "myapp::builders" (suffix match at :: boundary).

        Args:
            symbol_namespace: The namespace of the symbol (e.g., "myapp::builders")
            filter_namespace: The namespace filter from the user (e.g., "builders")

        Returns:
            True if symbol_namespace matches filter_namespace (exact or suffix match)

        Examples:
            _matches_namespace("myapp::builders", "builders") → True  (suffix)
            _matches_namespace("builders", "builders") → True  (exact)
            _matches_namespace("myapp::builders", "myapp::builders") → True  (exact)
            _matches_namespace("X::myapp::builders", "myapp::builders") → True  (suffix)
            _matches_namespace("Foobuilders", "builders") → False  (not at boundary)
            _matches_namespace("", "") → True  (global namespace)
            _matches_namespace("ns1", "") → False  (not global namespace)
        """
        # Empty filter matches only global namespace (empty symbol_namespace)
        if filter_namespace == "":
            return symbol_namespace == ""

        # Exact match
        if symbol_namespace == filter_namespace:
            return True

        # Suffix match: symbol_namespace ends with "::filter_namespace"
        suffix = "::" + filter_namespace
        if symbol_namespace.endswith(suffix):
            return True

        return False

    def _matches_class_criteria(
        self,
        info: SymbolInfo,
        pattern: str,
        project_only: bool,
        file_name: Optional[str],
        namespace: Optional[str],
    ) -> bool:
        """Check if a class symbol matches the search criteria."""
        qualified_name = info.qualified_name if info.qualified_name else info.name
        if not matches_qualified_pattern(qualified_name, pattern):
            return False

        if project_only and not info.is_project:
            return False

        if file_name and file_name not in info.file:
            return False

        if namespace is not None and not self._matches_namespace(info.namespace, namespace):
            return False

        return True

    def _create_class_result(self, info: SymbolInfo, include_base_classes: bool) -> Dict[str, Any]:
        """Build a result dictionary for a class search hit."""
        entry = {
            "prototype": build_class_prototype(info),
            "qualified_name": info.qualified_name or info.name,
            "namespace": info.namespace,
            "kind": info.kind,
            "is_project": info.is_project,
            "template_kind": info.template_kind,
            "template_parameters": info.template_parameters,
            "specialization_of": self._resolve_specialization_of(info.primary_template_usr),
            **build_location_objects(info),
            "brief": info.brief,
            "doc_comment": info.doc_comment,
        }
        if include_base_classes:
            entry["base_classes"] = info.base_classes
        return omit_empty(entry)

    def search_classes(
        self,
        criteria: SearchCriteria,
    ) -> Union[List[Dict[str, Any]], Tuple[List[Dict[str, Any]], int]]:
        """Search for classes matching a pattern.

        Phase 2 (Qualified Names): Supports qualified pattern matching.

        Pattern matching modes:
        - Empty string ("") matches ALL classes (useful with file_name filter)
        - Unqualified ("View") matches View in any namespace (case-insensitive)
        - Qualified ("ui::View") matches with component-based suffix (e.g., app::ui::View)
        - Exact ("::View") matches only global namespace (leading ::)
        - Regex ("app::.*::View") uses regex fullmatch semantics

        Args:
            criteria: SearchCriteria with pattern, filters, and result options.

        Returns:
            If max_results is None: List of matching class dictionaries
            If max_results is set: Tuple of (truncated list, total count before truncation)

        Task: T2.2.1 (Qualified Names Phase 2)
        """
        pattern = criteria.pattern
        pattern_type = detect_pattern_type(pattern)
        if pattern_type == "regex":
            RegexValidator.validate_or_raise(pattern)

        results: List[Dict[str, Any]] = []

        with self.index_lock:
            for name, infos in self.class_index.items():
                for info in infos:
                    if self._matches_class_criteria(
                        info,
                        pattern,
                        criteria.project_only,
                        criteria.file_name,
                        criteria.namespace,
                    ):
                        results.append(
                            self._create_class_result(info, criteria.include_base_classes)
                        )

        return self._apply_max_results(results, criteria.max_results)

    def _matches_function_criteria(
        self,
        info: SymbolInfo,
        pattern: str,
        pattern_type: str,
        project_only: bool,
        class_name: Optional[str],
        namespace: Optional[str],
        signature_pattern: Optional[str],
    ) -> bool:
        """Helper to check if a function symbol matches the search criteria."""
        if info.kind not in ("function", "method", "function_template"):
            return False

        # Use qualified pattern matching (Phase 2)
        # Fallback to info.name if qualified_name is empty (backward compatibility)
        qualified_name = info.qualified_name if info.qualified_name else info.name

        # For backward compatibility: regex patterns can match EITHER qualified or unqualified name
        # This allows "test.*" to match both "testFunction" and "TestClass::testMethod"
        matches = matches_qualified_pattern(qualified_name, pattern)
        if not matches and pattern_type == "regex":
            # Also try matching against unqualified name for backward compatibility
            matches = matches_qualified_pattern(info.name, pattern)

        if not matches:
            return False

        if project_only and not info.is_project:
            return False

        # Filter by class name if specified
        if class_name and info.parent_class != class_name:
            return False

        # Filter by namespace if specified (supports partial matching)
        if namespace is not None:
            if not self._matches_namespace(info.namespace, namespace):
                return False

        # Filter by prototype substring (case-insensitive)
        # Prototype supersedes raw signature: contains return type,
        # qualified name, params, const/virtual/static qualifiers.
        if signature_pattern is not None:
            prototype = build_function_prototype(info) or ""
            if signature_pattern.lower() not in prototype.lower():
                return False

        return True

    def _create_function_result(self, info: SymbolInfo, include_attributes: bool) -> Dict[str, Any]:
        """Build a result dictionary for a function search hit."""
        d: Dict[str, Any] = {
            "prototype": build_function_prototype(info),
            "qualified_name": info.qualified_name or info.name,
            "namespace": info.namespace,
            "kind": info.kind,
            "is_project": info.is_project,
            "parent_class": info.parent_class or None,
            "template_kind": info.template_kind,
            "template_parameters": info.template_parameters,
            "specialization_of": self._resolve_specialization_of(info.primary_template_usr),
            **build_location_objects(info),
            "brief": info.brief,
            "doc_comment": info.doc_comment,
        }
        if include_attributes:
            d["attributes"] = build_attributes(info)
        return omit_empty(d)

    def _search_functions_in_file_index(
        self,
        pattern: str,
        pattern_type: str,
        project_only: bool,
        class_name: Optional[str],
        namespace: Optional[str],
        signature_pattern: Optional[str],
        file_name: str,
        include_attributes: bool,
    ) -> List[Dict[str, Any]]:
        """Search for functions in file_index when a file_name filter is provided."""
        results: List[Dict[str, Any]] = []
        with self.index_lock:
            for file_path, infos in self.file_index.items():
                if file_name not in file_path:
                    continue
                for info in infos:
                    if self._matches_function_criteria(
                        info,
                        pattern,
                        pattern_type,
                        project_only,
                        class_name,
                        namespace,
                        signature_pattern,
                    ):
                        results.append(self._create_function_result(info, include_attributes))
        return results

    def _search_functions_in_function_index(
        self,
        pattern: str,
        pattern_type: str,
        project_only: bool,
        class_name: Optional[str],
        namespace: Optional[str],
        signature_pattern: Optional[str],
        include_attributes: bool,
    ) -> List[Dict[str, Any]]:
        """Search for functions in function_index."""
        results: List[Dict[str, Any]] = []
        with self.index_lock:
            for name, infos in self.function_index.items():
                for info in infos:
                    if self._matches_function_criteria(
                        info,
                        pattern,
                        pattern_type,
                        project_only,
                        class_name,
                        namespace,
                        signature_pattern,
                    ):
                        results.append(self._create_function_result(info, include_attributes))
        return results

    @staticmethod
    def _apply_max_results(
        results: List[Dict[str, Any]], max_results: Optional[int]
    ) -> Union[List[Dict[str, Any]], Tuple[List[Dict[str, Any]], int]]:
        """Truncate results if max_results is specified."""
        if max_results is not None:
            return (results[:max_results], len(results))
        return results

    def search_functions(
        self,
        criteria: SearchCriteria,
    ) -> Union[List[Dict[str, Any]], Tuple[List[Dict[str, Any]], int]]:
        """Search for functions matching a pattern.

        Phase 2 (Qualified Names): Supports qualified pattern matching.

        Pattern matching modes:
        - Empty string ("") matches ALL functions (useful with file_name filter)
        - Unqualified ("foo") matches foo in any namespace (case-insensitive)
        - Qualified ("ns::foo") matches with component-based suffix (e.g., app::ns::foo)
        - Member functions ("Class::method") supported
        - Exact ("::foo") matches only global namespace (leading ::)
        - Regex ("ns::.*") uses regex fullmatch semantics

        Args:
            criteria: SearchCriteria with pattern, filters, and result options.

        Returns:
            If max_results is None: List of matching function dictionaries
            If max_results is set: Tuple of (truncated list, total count before truncation)

        Task: T2.2.2 (Qualified Names Phase 2)
        """
        pattern = criteria.pattern
        pattern_type = detect_pattern_type(pattern)
        if pattern_type == "regex":
            RegexValidator.validate_or_raise(pattern)

        class_name = criteria.class_name
        if class_name:
            class_name = extract_simple_name(class_name)

        if criteria.file_name:
            results = self._search_functions_in_file_index(
                pattern,
                pattern_type,
                criteria.project_only,
                class_name,
                criteria.namespace,
                criteria.signature_pattern,
                criteria.file_name,
                criteria.include_attributes,
            )
        else:
            results = self._search_functions_in_function_index(
                pattern,
                pattern_type,
                criteria.project_only,
                class_name,
                criteria.namespace,
                criteria.signature_pattern,
                criteria.include_attributes,
            )

        return self._apply_max_results(results, criteria.max_results)

    def search_symbols(
        self,
        criteria: SearchCriteria,
    ) -> Union[Dict[str, List[Dict[str, Any]]], Tuple[Dict[str, List[Dict[str, Any]]], int]]:
        """Search for any symbols matching a pattern.

        Phase 2 (Qualified Names): Supports qualified pattern matching.

        Pattern matching modes:
        - Empty string ("") matches ALL symbols of specified types
        - Unqualified ("View") matches View in any namespace (case-insensitive)
        - Qualified ("ui::View") matches with component-based suffix (e.g., app::ui::View)
        - Exact ("::View") matches only global namespace (leading ::)
        - Regex ("app::.*::View") uses regex fullmatch semantics

        Args:
            criteria: SearchCriteria with pattern, filters, and result options.

        Returns:
            If max_results is None: Dictionary with "classes" and "functions" keys
            If max_results is set: Tuple of (truncated dict, total count before truncation)

        Note:
            Delegates to search_classes() and search_functions() which implement
            qualified pattern matching. See those methods for detailed behavior.

        Task: T2.2.3 (Qualified Names Phase 2)
        """
        results: Dict[str, List[Dict[str, Any]]] = {"classes": [], "functions": []}

        symbol_types = criteria.symbol_types
        # Filter symbol types
        search_classes = not symbol_types or any(t in ["class", "struct"] for t in symbol_types)
        search_functions = not symbol_types or any(
            t in ["function", "method"] for t in symbol_types
        )

        if search_classes:
            class_criteria = SearchCriteria(
                pattern=criteria.pattern,
                project_only=criteria.project_only,
                namespace=criteria.namespace,
            )
            results["classes"] = cast(
                List[Dict[str, Any]],
                self.search_classes(class_criteria),
            )

        if search_functions:
            function_criteria = SearchCriteria(
                pattern=criteria.pattern,
                project_only=criteria.project_only,
                namespace=criteria.namespace,
                signature_pattern=criteria.signature_pattern,
                include_attributes=criteria.include_attributes,
            )
            results["functions"] = cast(
                List[Dict[str, Any]],
                self.search_functions(function_criteria),
            )

        # Handle max_results truncation (truncate combined results)
        max_results = criteria.max_results
        if max_results is not None:
            total_count = len(results["classes"]) + len(results["functions"])
            # Truncate each list proportionally, keeping classes first
            remaining = max_results
            if remaining > 0:
                classes_count = min(len(results["classes"]), remaining)
                results["classes"] = results["classes"][:classes_count]
                remaining -= classes_count
            else:
                results["classes"] = []
            if remaining > 0:
                results["functions"] = results["functions"][:remaining]
            else:
                results["functions"] = []
            return (results, total_count)

        return results

    def get_symbols_in_file(self, file_path: str) -> List[SymbolInfo]:
        """Get all symbols in a specific file"""
        with self.index_lock:
            # Return a copy to prevent concurrent modification during iteration
            return list(self.file_index.get(file_path, []))

    def _find_class_candidate(
        self, class_name: str, lookup_name: str, is_qualified: bool, has_template_args: bool
    ) -> Union[SymbolInfo, Dict[str, Any], None]:
        """Find the best matching SymbolInfo for a class name, or an ambiguity error."""
        simple_name = extract_simple_name(lookup_name)

        # Try direct lookup first (fast path)
        infos = self.class_index.get(simple_name, [])
        if not infos:
            # Case-insensitive fallback: search for matching key
            simple_name_lower = simple_name.lower()
            for key in self.class_index:
                if key.lower() == simple_name_lower:
                    infos = self.class_index[key]
                    simple_name = key
                    break
        if not infos:
            return None

        if is_qualified:
            return self._disambiguate_qualified_class(infos, lookup_name)
        else:
            return self._disambiguate_simple_class(infos, class_name, has_template_args)

    def _disambiguate_qualified_class(
        self, infos: List[SymbolInfo], lookup_name: str
    ) -> Optional[SymbolInfo]:
        """Find the best match among candidates for a qualified name."""
        matching_candidates = []
        for candidate in infos:
            candidate_qualified = (
                candidate.qualified_name if candidate.qualified_name else candidate.name
            )
            if matches_qualified_pattern(candidate_qualified, lookup_name):
                matching_candidates.append(candidate)

        if not matching_candidates:
            return None

        # Apply definition-wins logic: prefer richest definition
        info = None
        for candidate in matching_candidates:
            if candidate.is_definition:
                if info is None or is_richer_definition(candidate, info):
                    info = candidate

        return info or matching_candidates[0]

    def _disambiguate_simple_class(
        self, infos: List[SymbolInfo], class_name: str, has_template_args: bool
    ) -> Union[SymbolInfo, Dict[str, Any]]:
        """Find the best match or return an ambiguity error for a simple name."""
        if len(infos) > 1:
            if has_template_args:
                specializations = [c for c in infos if c.is_template_specialization]
                if len(specializations) == 1:
                    return specializations[0]
                elif len(specializations) > 1:
                    return self._create_ambiguity_error(
                        f"Ambiguous template specialization '{class_name}'", specializations
                    )

            # Multiple classes with same simple name - ambiguous
            return self._create_ambiguity_error(f"Ambiguous class name '{class_name}'", infos)

        # Apply definition-wins logic: prefer richest definition
        info = None
        for candidate in infos:
            if candidate.is_definition:
                if info is None or is_richer_definition(candidate, info):
                    info = candidate

        return info or infos[0]

    def _create_ambiguity_error(self, message: str, matches: List[SymbolInfo]) -> Dict[str, Any]:
        """Create a standardized ambiguity error dictionary."""
        return {
            "error": message,
            "is_ambiguous": True,
            "matches": [
                {
                    "name": m.name,
                    "qualified_name": (m.qualified_name if m.qualified_name else m.name),
                    "namespace": m.namespace,
                    "kind": m.kind,
                    "file": m.file,
                    "line": m.line,
                }
                for m in matches
            ],
            "suggestion": "Use qualified name to disambiguate",
        }

    def _find_class_methods(
        self, simple_name: str, class_qualified_name: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Find all methods belonging to a specific class."""
        methods = []
        for name, func_infos in self.function_index.items():
            for func_info in func_infos:
                # Match by parent_class (simple name) OR qualified_name prefix
                if func_info.parent_class == simple_name:
                    # Direct parent_class match - disambiguate with qualified_name
                    if class_qualified_name and func_info.qualified_name:
                        if not func_info.qualified_name.startswith(class_qualified_name + "::"):
                            continue
                elif class_qualified_name and func_info.qualified_name:
                    # Fallback: match by qualified_name prefix
                    # (for methods with empty parent_class, e.g. out-of-line definitions)
                    if not func_info.qualified_name.startswith(class_qualified_name + "::"):
                        continue
                else:
                    continue

                methods.append(
                    omit_empty(
                        {
                            "prototype": build_function_prototype(func_info),
                            "qualified_name": func_info.qualified_name or func_info.name,
                            "access": func_info.access,
                            "template_kind": func_info.template_kind,
                            "template_parameters": func_info.template_parameters,
                            "specialization_of": self._resolve_specialization_of(
                                func_info.primary_template_usr
                            ),
                            **build_location_objects(func_info),
                            "attributes": build_attributes(func_info),
                            "brief": func_info.brief,
                            "doc_comment": func_info.doc_comment,
                        }
                    )
                )
        return methods

    def get_class_info(self, class_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a class.

        Args:
            class_name: Simple name (e.g., "Widget") or qualified name
                       (e.g., "myapp::builders::Widget")

        Returns:
            Class info dict or None if not found
        """
        with self.index_lock:
            # Strip template arguments for lookup
            has_template_args = "<" in class_name
            lookup_name = strip_template_args(class_name) if has_template_args else class_name

            is_qualified = "::" in lookup_name
            candidate = self._find_class_candidate(
                class_name, lookup_name, is_qualified, has_template_args
            )

            if candidate is None:
                return None
            if isinstance(candidate, dict):
                return candidate  # Ambiguity error

            info: SymbolInfo = candidate
            simple_name = extract_simple_name(info.name)

            # For method lookup, we need to match parent_class
            # parent_class is stored as simple name (from cursor.spelling)
            # To disambiguate classes with same simple name, also check qualified_name prefix
            class_qualified_name = info.qualified_name

            # Find all methods of this class
            methods = self._find_class_methods(simple_name, class_qualified_name)

        def _method_sort_line(m: Dict[str, Any]) -> int:
            """Extract line number for sorting from declaration or definition."""
            loc: Dict[str, Any] = m.get("declaration") or m.get("definition") or {}
            return int(loc.get("line", 0))

        return omit_empty(
            {
                "prototype": build_class_prototype(info),
                "qualified_name": info.qualified_name or info.name,
                "namespace": info.namespace,
                "kind": info.kind,
                "completeness": "complete",
                "completeness_note": "All methods, base classes, and derived classes are listed. No further searching needed for class details.",
                "base_classes": info.base_classes,
                "template_param_base_indices": get_template_param_base_indices(info) or None,
                "methods": sorted(methods, key=_method_sort_line),
                "is_project": info.is_project,
                "template_kind": info.template_kind,
                "template_parameters": info.template_parameters,
                "specialization_of": self._resolve_specialization_of(info.primary_template_usr),
                **build_location_objects(info),
                "brief": info.brief,
                "doc_comment": info.doc_comment,
            }
        )

    def _lookup_function_infos(self, simple_name: str) -> List[Any]:
        """Look up function infos by simple name with case-insensitive fallback."""
        infos = self.function_index.get(simple_name, [])
        if infos:
            return infos

        simple_name_lower = simple_name.lower()
        for key in self.function_index:
            if key.lower() == simple_name_lower:
                return self.function_index[key]
        return []

    @staticmethod
    def _info_matches_class_filter(info, class_name: str) -> bool:
        """Check if a function info matches the requested class filter."""
        if info.parent_class == class_name:
            return True
        if info.qualified_name and (
            info.qualified_name.startswith(class_name + "::")
            or ("::" + class_name + "::") in info.qualified_name
        ):
            return True
        return False

    @staticmethod
    def _build_scoped_signature(info, scope: str) -> str:
        """Inject class scope into a human-readable signature."""
        sig: str = info.signature
        target = f"{info.name}("
        idx = sig.find(target)
        if idx >= 0:
            return sig[:idx] + f"{scope}::" + sig[idx:]
        return f"{scope}::{sig}"

    def get_function_signature(
        self, function_name: str, class_name: Optional[str] = None
    ) -> List[str]:
        """Get function signatures matching the name.

        Args:
            function_name: Simple name (e.g., "foo") or qualified name
                          (e.g., "ns::MyClass::foo")
            class_name: Optional class name filter (simple or qualified name)

        Returns:
            List of signature strings
        """
        signatures = []

        has_template_args = "<" in function_name
        lookup_name = strip_template_args(function_name) if has_template_args else function_name

        is_qualified = "::" in lookup_name
        simple_name = extract_simple_name(lookup_name)

        if class_name:
            class_name = extract_simple_name(class_name)

        with self.index_lock:
            infos = self._lookup_function_infos(simple_name)
            for info in infos:
                if is_qualified:
                    info_qualified = info.qualified_name if info.qualified_name else info.name
                    if not matches_qualified_pattern(info_qualified, lookup_name):
                        continue

                if class_name is not None and not self._info_matches_class_filter(info, class_name):
                    continue

                if class_name is not None or info.parent_class:
                    scope = info.parent_class or class_name
                    assert scope is not None
                    signatures.append(self._build_scoped_signature(info, scope))
                else:
                    signatures.append(info.signature)

        return signatures
