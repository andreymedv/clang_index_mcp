"""Search functionality for C++ symbols."""

import re
from typing import Dict, List, Optional, Any
from collections import defaultdict
from .symbol_info import SymbolInfo
from .regex_validator import RegexValidator, RegexValidationError


class SearchEngine:
    """Handles searching for C++ symbols."""

    def __init__(
        self,
        class_index: Dict[str, List[SymbolInfo]],
        function_index: Dict[str, List[SymbolInfo]],
        file_index: Dict[str, List[SymbolInfo]],
        usr_index: Dict[str, SymbolInfo],
    ):
        self.class_index = class_index
        self.function_index = function_index
        self.file_index = file_index
        self.usr_index = usr_index

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

        Task: T2.1.1 (Qualified Names Phase 2)
        """
        # Empty pattern matches everything
        if not pattern:
            return True

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
            q_suffix = q_parts[-len(p_parts):]
            return [p.lower() for p in q_suffix] == [p.lower() for p in p_parts]

        # Fallback (should never reach here)
        return False

    def search_classes(
        self, pattern: str, project_only: bool = True, file_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
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

        Returns:
            List of matching class dictionaries with qualified_name and namespace fields

        Task: T2.2.1 (Qualified Names Phase 2)
        """
        # Validate regex patterns for ReDoS prevention
        pattern_type = self._detect_pattern_type(pattern)
        if pattern_type == "regex":
            RegexValidator.validate_or_raise(pattern)

        results = []

        # Iterate all classes and use qualified pattern matching
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

                    results.append(
                        {
                            "name": info.name,
                            "qualified_name": info.qualified_name,  # Phase 2: Qualified name
                            "namespace": info.namespace,  # Phase 2: Namespace portion
                            "kind": info.kind,
                            "file": info.file,
                            "line": info.line,
                            "is_project": info.is_project,
                            "base_classes": info.base_classes,
                            # Phase 1: Line ranges
                            "start_line": info.start_line,
                            "end_line": info.end_line,
                            "header_file": info.header_file,
                            "header_line": info.header_line,
                            "header_start_line": info.header_start_line,
                            "header_end_line": info.header_end_line,
                            # Phase 2: Documentation
                            "brief": info.brief,
                            "doc_comment": info.doc_comment,
                        }
                    )

        return results

    def search_functions(
        self,
        pattern: str,
        project_only: bool = True,
        class_name: Optional[str] = None,
        file_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
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

        Returns:
            List of matching function dictionaries with qualified_name and namespace fields

        Task: T2.2.2 (Qualified Names Phase 2)
        """
        # Validate regex patterns for ReDoS prevention
        pattern_type = self._detect_pattern_type(pattern)
        if pattern_type == "regex":
            RegexValidator.validate_or_raise(pattern)

        results = []

        # Helper to create result dict
        def _create_result(info: SymbolInfo) -> Dict[str, Any]:
            return {
                "name": info.name,
                "qualified_name": info.qualified_name,  # Phase 2: Qualified name
                "namespace": info.namespace,  # Phase 2: Namespace portion
                "kind": info.kind,
                "file": info.file,
                "line": info.line,
                "signature": info.signature,
                "is_project": info.is_project,
                "parent_class": info.parent_class,
                # Phase 1: Line ranges
                "start_line": info.start_line,
                "end_line": info.end_line,
                "header_file": info.header_file,
                "header_line": info.header_line,
                "header_start_line": info.header_start_line,
                "header_end_line": info.header_end_line,
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

                        results.append(_create_result(info))
        else:
            # Original logic: search function_index
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

                        results.append(_create_result(info))

        return results

    def search_symbols(
        self, pattern: str, project_only: bool = True, symbol_types: Optional[List[str]] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
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

        Returns:
            Dictionary with "classes" and "functions" keys containing matching symbols
            Each symbol includes qualified_name and namespace fields (Phase 2)

        Note:
            Delegates to search_classes() and search_functions() which implement
            qualified pattern matching. See those methods for detailed behavior.

        Task: T2.2.3 (Qualified Names Phase 2)
        """
        results = {"classes": [], "functions": []}

        # Filter symbol types
        search_classes = not symbol_types or any(t in ["class", "struct"] for t in symbol_types)
        search_functions = not symbol_types or any(
            t in ["function", "method"] for t in symbol_types
        )

        if search_classes:
            results["classes"] = self.search_classes(pattern, project_only)

        if search_functions:
            results["functions"] = self.search_functions(pattern, project_only)

        return results

    def get_symbols_in_file(self, file_path: str) -> List[SymbolInfo]:
        """Get all symbols in a specific file"""
        return self.file_index.get(file_path, [])

    def get_class_info(self, class_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a class"""
        infos = self.class_index.get(class_name, [])
        if not infos:
            return None

        # Return the first match (could be enhanced to handle multiple matches)
        info = infos[0]

        # Find all methods of this class
        methods = []
        for name, func_infos in self.function_index.items():
            for func_info in func_infos:
                if func_info.parent_class == class_name:
                    methods.append(
                        {
                            "name": func_info.name,
                            "signature": func_info.signature,
                            "access": func_info.access,
                            "line": func_info.line,
                            # Phase 1: Line ranges for methods
                            "start_line": func_info.start_line,
                            "end_line": func_info.end_line,
                            "header_line": func_info.header_line,
                            "header_start_line": func_info.header_start_line,
                            "header_end_line": func_info.header_end_line,
                            # Phase 2: Documentation for methods
                            "brief": func_info.brief,
                            "doc_comment": func_info.doc_comment,
                        }
                    )

        return {
            "name": info.name,
            "kind": info.kind,
            "file": info.file,
            "line": info.line,
            "base_classes": info.base_classes,
            "methods": sorted(methods, key=lambda x: x["line"]),
            "members": [],  # TODO: Implement member variable indexing
            "is_project": info.is_project,
            # Phase 1: Line ranges for class
            "start_line": info.start_line,
            "end_line": info.end_line,
            "header_file": info.header_file,
            "header_line": info.header_line,
            "header_start_line": info.header_start_line,
            "header_end_line": info.header_end_line,
            # Phase 2: Documentation for class
            "brief": info.brief,
            "doc_comment": info.doc_comment,
        }

    def get_function_signature(
        self, function_name: str, class_name: Optional[str] = None
    ) -> List[str]:
        """Get function signatures matching the name"""
        signatures = []

        for info in self.function_index.get(function_name, []):
            if class_name is None or info.parent_class == class_name:
                if info.parent_class:
                    signatures.append(f"{info.parent_class}::{info.name}{info.signature}")
                else:
                    signatures.append(f"{info.name}{info.signature}")

        return signatures
