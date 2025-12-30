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

    def search_classes(
        self, pattern: str, project_only: bool = True, file_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search for classes matching a pattern.

        Pattern matching modes:
        - Empty string ("") matches ALL classes (useful with file_name filter)
        - Plain text (no regex metacharacters) performs exact match (case-insensitive)
        - Regex patterns (with .*+?[]{}()| etc.) use anchored full-match
        """
        # Validate pattern for ReDoS prevention (only if it's a regex pattern)
        if self._is_pattern(pattern):
            RegexValidator.validate_or_raise(pattern)

        results = []

        for name, infos in self.class_index.items():
            if self._matches(pattern, name):
                for info in infos:
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

        Pattern matching modes:
        - Empty string ("") matches ALL functions (useful with file_name filter)
        - Plain text (no regex metacharacters) performs exact match (case-insensitive)
        - Regex patterns (with .*+?[]{}()| etc.) use anchored full-match
        """
        # Validate pattern for ReDoS prevention (only if it's a regex pattern)
        if self._is_pattern(pattern):
            RegexValidator.validate_or_raise(pattern)

        results = []

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

                    if not project_only or info.is_project:
                        # Filter by class name if specified
                        if class_name and info.parent_class != class_name:
                            continue

                        # Filter by pattern
                        if not self._matches(pattern, info.name):
                            continue

                        results.append(
                            {
                                "name": info.name,
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
                        )
        else:
            # Original logic: search function_index
            for name, infos in self.function_index.items():
                if self._matches(pattern, name):
                    for info in infos:
                        if not project_only or info.is_project:
                            # Filter by class name if specified
                            if class_name and info.parent_class != class_name:
                                continue

                            results.append(
                                {
                                    "name": info.name,
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
                            )

        return results

    def search_symbols(
        self, pattern: str, project_only: bool = True, symbol_types: Optional[List[str]] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Search for any symbols matching a pattern.

        Pattern matching modes:
        - Empty string ("") matches ALL symbols of specified types
        - Plain text (no regex metacharacters) performs exact match (case-insensitive)
        - Regex patterns (with .*+?[]{}()| etc.) use anchored full-match
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
