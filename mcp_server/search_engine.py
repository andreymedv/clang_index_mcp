"""Search functionality for C++ symbols."""

import re
import threading
from typing import Dict, List, Optional, Any, Tuple, Union, cast
from .symbol_info import (
    SymbolInfo,
    build_location_objects,
    get_template_param_base_indices,
    is_richer_definition,
)
from .regex_validator import RegexValidator


class SearchEngine:
    """Handles searching for C++ symbols."""

    def __init__(
        self,
        class_index: Dict[str, List[SymbolInfo]],
        function_index: Dict[str, List[SymbolInfo]],
        file_index: Dict[str, List[SymbolInfo]],
        usr_index: Dict[str, SymbolInfo],
        index_lock: threading.RLock,
        cache_manager=None,  # Phase 1.3: Type Alias Tracking support
    ):
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
            primary_info = self.usr_index.get(primary_template_usr)
            if primary_info:
                return primary_info.qualified_name or primary_info.name
        return None

    @staticmethod
    def _is_pattern(text: str) -> bool:
        """Check if text contains regex metacharacters that indicate it's a pattern.

        Returns True if text contains regex special chars (*, +, ?, ., [, etc.)
        Returns False for plain text (should use exact matching)
        """
        # Check for common regex metacharacters
        # This list includes characters that users would use for pattern matching
        regex_chars = r".*+?[]{}()|\^$"
        return any(char in text for char in regex_chars)

    @staticmethod
    def _matches(pattern: str, name: str) -> bool:
        """Check if name matches pattern using exact or pattern matching.

        - If pattern is empty: match all (returns True)
        - If pattern has no regex metacharacters: exact match (case-insensitive)
        - If pattern has regex metacharacters: regex fullmatch (anchored pattern matching)

        Using fullmatch instead of search provides more intuitive behavior:
        - "View.*" matches "View", "ViewManager" (starts with View)
        - "View.*" does NOT match "ListView" (doesn't start with View)
        - ".*View.*" matches all of the above (contains View anywhere)
        """
        # Empty pattern matches all symbols (useful with file_name filter)
        if not pattern:
            return True

        if SearchEngine._is_pattern(pattern):
            # Pattern matching: use regex fullmatch (anchored at both ends)
            regex = re.compile(pattern, re.IGNORECASE)
            return regex.fullmatch(name) is not None
        else:
            # Exact matching: case-insensitive equality
            return name.lower() == pattern.lower()

    @staticmethod
    def _normalize_template_whitespace(name: str) -> str:
        """
        Normalize whitespace in template arguments for consistent matching.

        libclang stores template arguments with spaces around pointer/reference operators
        (e.g., 'Container<Widget *>' not 'Container<Widget*>'), but users naturally
        search without spaces. This method normalizes both to enable matching.

        Args:
            name: Type name or pattern that may contain template arguments

        Returns:
            Name with normalized whitespace in template arguments

        Examples:
            'Container<Widget *>' → 'Container<Widget*>'
            'Container<Widget * const &>' → 'Container<Widget*const&>'
            'std::vector<int *>' → 'std::vector<int*>'
            'Container<Widget*>' → 'Container<Widget*>' (unchanged)

        Note:
            Only normalizes spaces around *, &, and && operators.
            Preserves spaces in type names like 'unsigned int', 'const char'.
        """
        # Remove spaces before * and & operators
        name = re.sub(r"\s+\*", "*", name)
        name = re.sub(r"\s+&", "&", name)

        # Remove spaces after * and & operators (but keep meaningful spaces)
        # Use lookahead to avoid removing spaces before keywords/types
        name = re.sub(r"\*\s+", "*", name)
        name = re.sub(r"&\s+", "&", name)

        return name

    @staticmethod
    def _detect_pattern_type(pattern: str) -> str:
        """
        Detect pattern type for qualified name search optimization.

        Phase 2 (Qualified Names): Component-based pattern matching.

        Returns:
            "exact": Leading :: means exact match in global namespace (e.g., "::View")
            "unqualified": No :: means match unqualified name only (e.g., "View")
            "suffix": Contains :: means component-based suffix match (e.g., "ui::View")
            "regex": Contains regex metacharacters (e.g., "app::.*::View")

        Examples:
            _detect_pattern_type("::View") → "exact"
            _detect_pattern_type("View") → "unqualified"
            _detect_pattern_type("ui::View") → "suffix"
            _detect_pattern_type("app::.*::View") → "regex"

        Task: T2.1.2 (Qualified Names Phase 2)
        """
        # Empty pattern handled by caller
        if not pattern:
            return "unqualified"

        # Leading :: → exact match in global namespace
        if pattern.startswith("::"):
            return "exact"

        # Check for regex metacharacters
        regex_chars = set(".*+?[]{}()|\\^$")
        if any(c in pattern for c in regex_chars):
            return "regex"

        # No :: → match unqualified name
        if "::" not in pattern:
            return "unqualified"

        # Contains :: but not leading, no regex → component-based suffix match
        return "suffix"

    @staticmethod
    def matches_qualified_pattern(qualified_name: str, pattern: str) -> bool:
        """
        Match qualified name against pattern using component-based suffix matching.

        Phase 2 (Qualified Names): Intelligent pattern matching with 4 modes.

        Matching Rules:
            1. Leading "::" → exact match (global namespace)
               "::View" matches only "View" (not "ns::View")

            2. No "::" → match unqualified name only
               "View" matches "View", "ns::View", "ns1::ns2::View"

            3. "::" in pattern → component-based suffix match
               "ui::View" matches "app::ui::View", "legacy::ui::View"
               but NOT "myui::View" (component boundary respected)

            4. Regex metacharacters → regex fullmatch
               "app::.*::View" matches "app::core::View", "app::ui::View"

        Args:
            qualified_name: Fully qualified symbol name (e.g., "app::ui::View")
            pattern: Search pattern (e.g., "ui::View", "::View", "View", ".*::View")

        Returns:
            True if qualified_name matches pattern, False otherwise

        Examples:
            matches_qualified_pattern("app::ui::View", "ui::View") → True (suffix)
            matches_qualified_pattern("app::ui::View", "::View") → False (not global)
            matches_qualified_pattern("app::ui::View", "View") → True (unqualified)
            matches_qualified_pattern("app::ui::View", "app::.*::View") → True (regex)
            matches_qualified_pattern("myui::View", "ui::View") → False (boundary)

        Template whitespace normalization:
            Handles libclang's spacing in template arguments:
            - "Container<Widget *>" matches pattern "Container<Widget*>"
            - "PointerHolder<Widget *>" matches pattern "PointerHolder<Widget*>"

        Task: T2.1.1 (Qualified Names Phase 2)
        """
        # Empty pattern matches everything
        if not pattern:
            return True

        # Normalize whitespace in template arguments for both name and pattern
        # This allows "Container<Widget*>" to match "Container<Widget *>"
        qualified_name = SearchEngine._normalize_template_whitespace(qualified_name)
        pattern = SearchEngine._normalize_template_whitespace(pattern)

        pattern_type = SearchEngine._detect_pattern_type(pattern)

        # 1. Exact match: leading ::
        if pattern_type == "exact":
            # Remove leading :: from pattern and compare with qualified_name
            return qualified_name == pattern[2:]

        # 2. Regex match (case-insensitive for consistency with other modes)
        if pattern_type == "regex":
            try:
                return bool(re.fullmatch(pattern, qualified_name, re.IGNORECASE))
            except re.error:
                # Invalid regex → no match
                return False

        # 3. Unqualified match: no ::
        if pattern_type == "unqualified":
            # Extract unqualified name from qualified_name
            unqualified = qualified_name.split("::")[-1]
            return unqualified.lower() == pattern.lower()

        # 4. Suffix match: component-based
        if pattern_type == "suffix":
            q_parts = qualified_name.split("::")
            p_parts = pattern.split("::")

            # Pattern longer than name → cannot match
            if len(p_parts) > len(q_parts):
                return False

            # Check that last N components match (case-insensitive)
            q_suffix = q_parts[-len(p_parts) :]
            return [p.lower() for p in q_suffix] == [p.lower() for p in p_parts]

        # Fallback (should never reach here)
        return False

    def expand_type_name(self, type_name: str) -> List[str]:
        """
        Expand a type name to include all equivalent type names (aliases and canonical).

        Phase 1.3: Type Alias Tracking - Infrastructure for automatic search unification

        This method enables future parameter type filtering to automatically find functions
        using both aliases and canonical types. For example, searching for "ErrorCallback"
        will also find functions using "std::function<void(const Error&)>".

        Args:
            type_name: Type name to expand (can be alias or canonical type)

        Returns:
            List of equivalent type names including:
            - The original type name
            - All aliases pointing to it (if it's a canonical type)
            - The canonical type (if it's an alias)

        Example:
            type_name = "ErrorCallback"
            returns ["ErrorCallback", "std::function<void(const Error&)>"]

            type_name = "std::function<void(const Error&)>"
            returns ["std::function<void(const Error&)>", "ErrorCallback"]
        """
        if not self.cache_manager:
            # No cache manager available, return original name only
            return [type_name]

        expanded_names = [type_name]

        try:
            # Check if this is an alias (has a canonical type)
            canonical = self.cache_manager.get_canonical_for_alias(type_name)
            if canonical and canonical != type_name:
                expanded_names.append(canonical)

            # Check if this is a canonical type (has aliases)
            aliases = self.cache_manager.get_aliases_for_canonical(type_name)
            if aliases:
                for alias in aliases:
                    if alias not in expanded_names:
                        expanded_names.append(alias)

            # Also check if the canonical type itself has aliases
            if canonical:
                aliases_of_canonical = self.cache_manager.get_aliases_for_canonical(canonical)
                if aliases_of_canonical:
                    for alias in aliases_of_canonical:
                        if alias not in expanded_names:
                            expanded_names.append(alias)

        except Exception as e:
            # Alias lookup failures are not critical, just log and continue
            from . import diagnostics

            diagnostics.debug(f"Failed to expand type name '{type_name}': {e}")

        return expanded_names

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

    def search_classes(
        self,
        pattern: str,
        project_only: bool = True,
        file_name: Optional[str] = None,
        namespace: Optional[str] = None,
        max_results: Optional[int] = None,
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
            pattern: Search pattern (qualified, unqualified, or regex)
            project_only: Only return symbols from project files
            file_name: Optional file name filter
            namespace: Optional namespace filter with partial matching support.
                      Supports suffix matching at :: boundaries (case-sensitive).
                      Examples:
                        - "builders" matches "myapp::builders" (suffix)
                        - "myapp::builders" matches "TopLevel::myapp::builders" (suffix)
                        - "" (empty string) matches only global namespace
            max_results: Optional maximum number of results to return. When specified,
                        returns tuple (results, total_count) for truncation tracking.

        Returns:
            If max_results is None: List of matching class dictionaries
            If max_results is set: Tuple of (truncated list, total count before truncation)

        Task: T2.2.1 (Qualified Names Phase 2)
        """
        # Validate regex patterns for ReDoS prevention
        pattern_type = self._detect_pattern_type(pattern)
        if pattern_type == "regex":
            RegexValidator.validate_or_raise(pattern)

        results = []

        # Iterate all classes and use qualified pattern matching
        with self.index_lock:
            for name, infos in self.class_index.items():
                for info in infos:
                    # Use qualified pattern matching (Phase 2)
                    # Fallback to info.name if qualified_name is empty (backward compatibility)
                    qualified_name = info.qualified_name if info.qualified_name else info.name
                    if not self.matches_qualified_pattern(qualified_name, pattern):
                        continue

                    # Apply filters
                    if not project_only or info.is_project:
                        # Filter by file name if specified
                        if file_name:
                            # Match if the file path ends with the specified file_name
                            # This supports full paths, relative paths, or just filenames
                            if not info.file.endswith(file_name):
                                continue

                        # Filter by namespace if specified (supports partial matching)
                        if namespace is not None:
                            if not self._matches_namespace(info.namespace, namespace):
                                continue

                        results.append(
                            {
                                "name": info.name,
                                "qualified_name": info.qualified_name,  # Phase 2: Qualified name
                                "namespace": info.namespace,  # Phase 2: Namespace portion
                                "kind": info.kind,
                                "is_project": info.is_project,
                                "base_classes": info.base_classes,
                                # Phase 3: Overload metadata
                                "is_template_specialization": info.is_template_specialization,
                                # v13.0: Template tracking
                                "is_template": info.is_template,
                                "template_kind": info.template_kind,
                                "template_parameters": info.template_parameters,
                                "specialization_of": self._resolve_specialization_of(
                                    info.primary_template_usr
                                ),
                                # Location objects (replaces flat file/line/start_line/end_line/header_*)
                                **build_location_objects(info),
                                # Phase 2: Documentation
                                "brief": info.brief,
                                "doc_comment": info.doc_comment,
                            }
                        )

        # Handle max_results truncation
        if max_results is not None:
            total_count = len(results)
            truncated_results = results[:max_results]
            return (truncated_results, total_count)

        return results

    def search_functions(
        self,
        pattern: str,
        project_only: bool = True,
        class_name: Optional[str] = None,
        file_name: Optional[str] = None,
        namespace: Optional[str] = None,
        max_results: Optional[int] = None,
        signature_pattern: Optional[str] = None,
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
            pattern: Search pattern (qualified, unqualified, or regex)
            project_only: Only return symbols from project files
            class_name: Optional class name filter (for methods)
            file_name: Optional file name filter
            namespace: Optional namespace filter with partial matching support.
                      Supports suffix matching at :: boundaries (case-sensitive).
                      For methods, matches the namespace + class (e.g., "app::Database").
                      Examples:
                        - "builders" matches "myapp::builders" (suffix)
                        - "Handler" matches "app::Handler" (suffix)
                        - "" (empty string) matches only global namespace
            max_results: Optional maximum number of results to return. When specified,
                        returns tuple (results, total_count) for truncation tracking.

        Returns:
            If max_results is None: List of matching function dictionaries
            If max_results is set: Tuple of (truncated list, total count before truncation)

        Task: T2.2.2 (Qualified Names Phase 2)
        """
        # Validate regex patterns for ReDoS prevention
        pattern_type = self._detect_pattern_type(pattern)
        if pattern_type == "regex":
            RegexValidator.validate_or_raise(pattern)

        # Normalize class_name: extract simple name from qualified name
        # parent_class is stored as simple name (e.g., "Widget"), but users may pass
        # qualified name (e.g., "myapp::builders::Widget")
        if class_name:
            class_name = self._extract_simple_name(class_name)

        results = []

        # Helper to create result dict
        def _create_result(info: SymbolInfo) -> Dict[str, Any]:
            return {
                "name": info.name,
                "qualified_name": info.qualified_name,  # Phase 2: Qualified name
                "namespace": info.namespace,  # Phase 2: Namespace portion
                "kind": info.kind,
                "signature": info.signature,
                "is_project": info.is_project,
                "parent_class": info.parent_class,
                # Phase 3: Overload metadata
                "is_template_specialization": info.is_template_specialization,
                # v13.0: Template tracking
                "is_template": info.is_template,
                "template_kind": info.template_kind,
                "template_parameters": info.template_parameters,
                "specialization_of": self._resolve_specialization_of(info.primary_template_usr),
                # Location objects (replaces flat file/line/start_line/end_line/header_*)
                **build_location_objects(info),
                # Phase 5: Virtual/abstract indicators
                "is_virtual": info.is_virtual,
                "is_pure_virtual": info.is_pure_virtual,
                "is_const": info.is_const,
                "is_static": info.is_static,
                "is_definition": info.is_definition,
                # Phase 2: Documentation
                "brief": info.brief,
                "doc_comment": info.doc_comment,
            }

        # CRITICAL FIX FOR ISSUE #8:
        # When file_name is specified, search file_index instead of function_index
        # This ensures we find declarations in headers even when definition-wins
        # removed them from function_index
        if file_name:
            # Search file_index for file-specific queries
            with self.index_lock:
                for file_path, infos in self.file_index.items():
                    # Match if the file path ends with the specified file_name
                    if not file_path.endswith(file_name):
                        continue

                    for info in infos:
                        # Only include functions (not classes)
                        if info.kind not in ("function", "method"):
                            continue

                        # Use qualified pattern matching (Phase 2)
                        # Fallback to info.name if qualified_name is empty (backward compatibility)
                        qualified_name = info.qualified_name if info.qualified_name else info.name

                        # For backward compatibility: regex patterns can match EITHER qualified or unqualified name
                        # This allows "test.*" to match both "testFunction" and "TestClass::testMethod"
                        matches = self.matches_qualified_pattern(qualified_name, pattern)
                        if not matches and pattern_type == "regex":
                            # Also try matching against unqualified name for backward compatibility
                            matches = self.matches_qualified_pattern(info.name, pattern)

                        if not matches:
                            continue

                        if not project_only or info.is_project:
                            # Filter by class name if specified
                            if class_name and info.parent_class != class_name:
                                continue

                            # Filter by namespace if specified (supports partial matching)
                            if namespace is not None:
                                if not self._matches_namespace(info.namespace, namespace):
                                    continue

                            # Filter by signature substring (case-insensitive)
                            if signature_pattern is not None:
                                if signature_pattern.lower() not in (info.signature or "").lower():
                                    continue

                            results.append(_create_result(info))
        else:
            # Original logic: search function_index
            with self.index_lock:
                for name, infos in self.function_index.items():
                    for info in infos:
                        # Use qualified pattern matching (Phase 2)
                        # Fallback to info.name if qualified_name is empty (backward compatibility)
                        qualified_name = info.qualified_name if info.qualified_name else info.name

                        # For backward compatibility: regex patterns can match EITHER qualified or unqualified name
                        # This allows "test.*" to match both "testFunction" and "TestClass::testMethod"
                        matches = self.matches_qualified_pattern(qualified_name, pattern)
                        if not matches and pattern_type == "regex":
                            # Also try matching against unqualified name for backward compatibility
                            matches = self.matches_qualified_pattern(info.name, pattern)

                        if not matches:
                            continue

                        if not project_only or info.is_project:
                            # Filter by class name if specified
                            if class_name and info.parent_class != class_name:
                                continue

                            # Filter by namespace if specified (supports partial matching)
                            if namespace is not None:
                                if not self._matches_namespace(info.namespace, namespace):
                                    continue

                            # Filter by signature substring (case-insensitive)
                            if signature_pattern is not None:
                                if signature_pattern.lower() not in (info.signature or "").lower():
                                    continue

                            results.append(_create_result(info))

        # Handle max_results truncation
        if max_results is not None:
            total_count = len(results)
            truncated_results = results[:max_results]
            return (truncated_results, total_count)

        return results

    def search_symbols(
        self,
        pattern: str,
        project_only: bool = True,
        symbol_types: Optional[List[str]] = None,
        namespace: Optional[str] = None,
        max_results: Optional[int] = None,
        signature_pattern: Optional[str] = None,
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
            pattern: Search pattern (qualified, unqualified, or regex)
            project_only: Only return symbols from project files
            symbol_types: Optional list of symbol types to filter (e.g., ["class", "function"])
            namespace: Optional namespace filter with partial matching support.
                      Supports suffix matching at :: boundaries (case-sensitive).
                      Examples:
                        - "builders" matches "myapp::builders" (suffix)
                        - "" (empty string) matches only global namespace
            max_results: Optional maximum number of results to return (across all types).
                        When specified, returns tuple (results, total_count) for truncation tracking.

        Returns:
            If max_results is None: Dictionary with "classes" and "functions" keys
            If max_results is set: Tuple of (truncated dict, total count before truncation)

        Note:
            Delegates to search_classes() and search_functions() which implement
            qualified pattern matching. See those methods for detailed behavior.

        Task: T2.2.3 (Qualified Names Phase 2)
        """
        results: Dict[str, List[Dict[str, Any]]] = {"classes": [], "functions": []}

        # Filter symbol types
        search_classes = not symbol_types or any(t in ["class", "struct"] for t in symbol_types)
        search_functions = not symbol_types or any(
            t in ["function", "method"] for t in symbol_types
        )

        if search_classes:
            results["classes"] = cast(
                List[Dict[str, Any]],
                self.search_classes(pattern, project_only, namespace=namespace),
            )

        if search_functions:
            results["functions"] = cast(
                List[Dict[str, Any]],
                self.search_functions(
                    pattern, project_only, namespace=namespace, signature_pattern=signature_pattern
                ),
            )

        # Handle max_results truncation (truncate combined results)
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

    @staticmethod
    def _strip_template_args(name: str) -> str:
        """Strip template argument suffix from a name.

        Examples:
            "Container<int>" → "Container"
            "ns::Container<int>" → "ns::Container"
            "std::map<int, std::string>" → "std::map"
            "Widget" → "Widget" (unchanged)
        """
        idx = name.find("<")
        if idx == -1:
            return name
        return name[:idx]

    @staticmethod
    def _extract_simple_name(qualified_name: str) -> str:
        """Extract simple name from qualified name, ignoring template arguments.

        Examples:
            "myapp::builders::Widget" → "Widget"
            "std::vector" → "vector"
            "Container<int>" → "Container"
            "ns::Container<int>" → "Container"
            "Widget" → "Widget" (already simple)
        """
        name = qualified_name
        # Strip template argument suffix: "Container<int>" → "Container"
        # Guard with endswith(">") to avoid mangling "operator<" or "operator<="
        if "<" in name and name.endswith(">"):
            name = name[: name.index("<")]
        if "::" not in name:
            return name
        return name.split("::")[-1]

    def get_class_info(self, class_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a class.

        Args:
            class_name: Simple name (e.g., "Widget") or qualified name
                       (e.g., "myapp::builders::Widget")

        Returns:
            Class info dict or None if not found
        """
        with self.index_lock:
            # Strip template arguments for lookup: class_index and qualified_names
            # don't include template args (e.g., "Container<int>" → lookup "Container")
            has_template_args = "<" in class_name
            lookup_name = self._strip_template_args(class_name) if has_template_args else class_name

            # Handle both simple and qualified names
            # class_index is keyed by simple name, so extract it from qualified input
            is_qualified = "::" in lookup_name
            simple_name = self._extract_simple_name(lookup_name)

            # Try direct lookup first (fast path)
            infos = self.class_index.get(simple_name, [])
            if not infos:
                # Case-insensitive fallback: search for matching key
                simple_name_lower = simple_name.lower()
                for key in self.class_index:
                    if key.lower() == simple_name_lower:
                        infos = self.class_index[key]
                        simple_name = key  # Use the actual key for method lookup
                        break
            if not infos:
                return None

            # If qualified name was provided, find match using qualified pattern matching
            # This supports partially qualified names (e.g., "builders::Widget"
            # matches "myapp::builders::Widget").
            # Use lookup_name (without template args) since stored qualified_names also
            # don't include template args.
            info = None
            if is_qualified:
                # Collect all matching candidates
                matching_candidates = []
                for candidate in infos:
                    candidate_qualified = (
                        candidate.qualified_name if candidate.qualified_name else candidate.name
                    )
                    if self.matches_qualified_pattern(candidate_qualified, lookup_name):
                        matching_candidates.append(candidate)

                if not matching_candidates:
                    return None  # No match for qualified name

                # Apply definition-wins logic: prefer richest definition
                # (Fix for cplusplus_mcp-2u9, cplusplus_mcp-5tl)
                info = None
                for candidate in matching_candidates:
                    if candidate.is_definition:
                        if info is None or is_richer_definition(candidate, info):
                            info = candidate

                # Fall back to first match if no definition found
                if info is None:
                    info = matching_candidates[0]

            else:
                # Check for ambiguity when using simple name
                if len(infos) > 1:
                    # When user provides template args (e.g., "Container<int>"),
                    # prefer explicit specializations over the primary template
                    if has_template_args:
                        specializations = [c for c in infos if c.is_template_specialization]
                        if len(specializations) == 1:
                            info = specializations[0]
                        elif len(specializations) > 1:
                            return {
                                "error": f"Ambiguous template specialization '{class_name}'",
                                "is_ambiguous": True,
                                "matches": [
                                    {
                                        "name": m.name,
                                        "qualified_name": (
                                            m.qualified_name if m.qualified_name else m.name
                                        ),
                                        "namespace": m.namespace,
                                        "kind": m.kind,
                                        "file": m.file,
                                        "line": m.line,
                                    }
                                    for m in specializations
                                ],
                                "suggestion": "Use qualified name to disambiguate",
                            }

                    if info is None:
                        # Multiple classes with same simple name - ambiguous
                        return {
                            "error": f"Ambiguous class name '{class_name}'",
                            "is_ambiguous": True,
                            "matches": [
                                {
                                    "name": m.name,
                                    "qualified_name": (
                                        m.qualified_name if m.qualified_name else m.name
                                    ),
                                    "namespace": m.namespace,
                                    "kind": m.kind,
                                    "file": m.file,
                                    "line": m.line,
                                }
                                for m in infos
                            ],
                            "suggestion": "Use qualified name to disambiguate",
                        }

                if info is None:
                    # Apply definition-wins logic: prefer richest definition
                    # (Fix for cplusplus_mcp-2u9, cplusplus_mcp-5tl)
                    for candidate in infos:
                        if candidate.is_definition:
                            if info is None or is_richer_definition(candidate, info):
                                info = candidate

                    # Fall back to first match if no definition found
                    if info is None:
                        info = infos[0]

            # For method lookup, we need to match parent_class
            # parent_class is stored as simple name (from cursor.spelling)
            # To disambiguate classes with same simple name, also check qualified_name prefix
            class_qualified_name = info.qualified_name

            # Find all methods of this class
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
                        {
                            "name": func_info.name,
                            "signature": func_info.signature,
                            "access": func_info.access,
                            # Phase 3: Overload metadata
                            "is_template_specialization": func_info.is_template_specialization,
                            # v13.0: Template tracking
                            "is_template": func_info.is_template,
                            "template_kind": func_info.template_kind,
                            "template_parameters": func_info.template_parameters,
                            "specialization_of": self._resolve_specialization_of(
                                func_info.primary_template_usr
                            ),
                            # Location objects (replaces flat line/start_line/end_line/header_*)
                            **build_location_objects(func_info),
                            # Phase 5: Virtual/abstract indicators
                            "is_virtual": func_info.is_virtual,
                            "is_pure_virtual": func_info.is_pure_virtual,
                            "is_const": func_info.is_const,
                            "is_static": func_info.is_static,
                            "is_definition": func_info.is_definition,
                            # Phase 2: Documentation for methods
                            "brief": func_info.brief,
                            "doc_comment": func_info.doc_comment,
                        }
                    )

        def _method_sort_line(m: Dict[str, Any]) -> int:
            """Extract line number for sorting from declaration or definition."""
            loc: Dict[str, Any] = m.get("declaration") or m.get("definition") or {}
            return int(loc.get("line", 0))

        return {
            "name": info.name,
            "qualified_name": info.qualified_name,
            "namespace": info.namespace,
            "kind": info.kind,
            "base_classes": info.base_classes,
            "template_param_base_indices": get_template_param_base_indices(info),
            "methods": sorted(methods, key=_method_sort_line),
            "members": [],  # TODO: Implement member variable indexing
            "is_project": info.is_project,
            # v13.0: Template tracking for class
            "is_template": info.is_template,
            "template_kind": info.template_kind,
            "template_parameters": info.template_parameters,
            "specialization_of": self._resolve_specialization_of(info.primary_template_usr),
            # Location objects (replaces flat file/line/start_line/end_line/header_*)
            **build_location_objects(info),
            # Phase 2: Documentation for class
            "brief": info.brief,
            "doc_comment": info.doc_comment,
        }

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

        # Strip template arguments for lookup: function_index uses names without template args
        # e.g., "max<int*>" → lookup "max", "ns::Class::foo<T>" → "foo"
        has_template_args = "<" in function_name
        lookup_name = (
            self._strip_template_args(function_name) if has_template_args else function_name
        )

        # function_index is keyed by simple name, so extract it from qualified input
        is_qualified = "::" in lookup_name
        simple_name = self._extract_simple_name(lookup_name)

        # Normalize class_name: extract simple name from qualified name
        # parent_class is stored as simple name
        if class_name:
            class_name = self._extract_simple_name(class_name)

        with self.index_lock:
            # Try direct lookup first (fast path)
            infos = self.function_index.get(simple_name, [])
            if not infos:
                # Case-insensitive fallback: search for matching key
                simple_name_lower = simple_name.lower()
                for key in self.function_index:
                    if key.lower() == simple_name_lower:
                        infos = self.function_index[key]
                        break
            for info in infos:
                # If qualified name was provided, filter using qualified pattern matching
                # This supports partially qualified names (e.g., "MyClass::foo"
                # matches "ns::MyClass::foo").
                # Use lookup_name (without template args) since stored qualified_names
                # also don't include template args.
                if is_qualified:
                    info_qualified = info.qualified_name if info.qualified_name else info.name
                    if not self.matches_qualified_pattern(info_qualified, lookup_name):
                        continue
                # Match by parent_class or qualified_name prefix for class filtering
                if class_name is not None:
                    if info.parent_class != class_name:
                        # Fallback: check qualified_name for out-of-line methods
                        if not (
                            info.qualified_name
                            and (
                                info.qualified_name.startswith(class_name + "::")
                                or ("::" + class_name + "::") in info.qualified_name
                            )
                        ):
                            continue
                if class_name is not None or info.parent_class:
                    # Inject class scope into human-readable signature
                    # e.g., "void foo(int x)" -> "void MyClass::foo(int x)"
                    scope = info.parent_class or class_name
                    target = f"{info.name}("
                    idx = info.signature.find(target)
                    if idx >= 0:
                        sig = info.signature[:idx] + f"{scope}::" + info.signature[idx:]
                    else:
                        sig = f"{scope}::{info.signature}"
                    signatures.append(sig)
                else:
                    signatures.append(info.signature)

        return signatures
