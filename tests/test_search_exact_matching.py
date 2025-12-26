#!/usr/bin/env python3
"""
Tests for Issue #4: Exact matching by default in search_classes and search_functions.

This module tests the intelligent pattern detection and exact matching behavior
introduced to fix Issue #4 (Class Search Substring Matching).
"""

import os
import sys
import unittest

# Add the mcp_server directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mcp_server.search_engine import SearchEngine
from mcp_server.symbol_info import SymbolInfo


class TestSearchEnginePatternDetection(unittest.TestCase):
    """Test pattern detection logic in SearchEngine."""

    def test_is_pattern_detects_regex_metacharacters(self):
        """Test that _is_pattern correctly identifies regex metacharacters."""
        # These should be detected as patterns
        patterns = [
            ".*View.*",
            "View.*",
            ".*View",
            "My.*Class",
            "get.*",
            "foo+",
            "bar?",
            "test[abc]",
            "x{2,}",
            "(a|b)",
            "^start",
            "end$",
            "a.b",
            "test\\w+",
        ]
        for pattern in patterns:
            with self.subTest(pattern=pattern):
                self.assertTrue(
                    SearchEngine._is_pattern(pattern),
                    f"Expected '{pattern}' to be detected as a pattern"
                )

    def test_is_pattern_plain_text(self):
        """Test that plain text without metacharacters is not detected as pattern."""
        plain_texts = [
            "View",
            "MyClass",
            "getValue",
            "SimpleClassName",
            "function_name",
            "CamelCase",
            "UPPER_CASE",
            "lower_case",
            "number123",
        ]
        for text in plain_texts:
            with self.subTest(text=text):
                self.assertFalse(
                    SearchEngine._is_pattern(text),
                    f"Expected '{text}' to be plain text, not a pattern"
                )


class TestSearchEngineMatching(unittest.TestCase):
    """Test matching logic in SearchEngine."""

    def test_exact_match_case_insensitive(self):
        """Test exact matching with case insensitivity."""
        test_cases = [
            ("View", "View", True),
            ("View", "view", True),
            ("View", "VIEW", True),
            ("View", "vIeW", True),
            ("View", "ViewManager", False),
            ("View", "ListView", False),
            ("View", "PreviewPanel", False),
            ("getValue", "getValue", True),
            ("getValue", "getvalue", True),
            ("getValue", "GETVALUE", True),
            ("getValue", "getValueFromCache", False),
            ("getValue", "setValue", False),
        ]
        for pattern, name, expected in test_cases:
            with self.subTest(pattern=pattern, name=name):
                result = SearchEngine._matches(pattern, name)
                self.assertEqual(
                    result, expected,
                    f"_matches('{pattern}', '{name}') returned {result}, expected {expected}"
                )

    def test_pattern_match_with_regex(self):
        """Test pattern matching with regex metacharacters using fullmatch."""
        test_cases = [
            # Substring matching with .*
            (".*View.*", "View", True),
            (".*View.*", "ViewManager", True),
            (".*View.*", "ListView", True),
            (".*View.*", "PreviewPanel", True),
            (".*View.*", "MyClass", False),

            # Prefix matching with .*
            ("View.*", "View", True),
            ("View.*", "ViewManager", True),
            ("View.*", "ViewPort", True),
            ("View.*", "ListView", False),  # Doesn't start with View

            # Suffix matching with .*
            (".*View", "View", True),
            (".*View", "ListView", True),
            (".*View", "TreeView", True),
            (".*View", "ViewManager", False),  # Doesn't end with View

            # Function name patterns
            ("get.*", "getValue", True),
            ("get.*", "getWidth", True),
            ("get.*", "getter", True),
            ("get.*", "setValue", False),

            # Character classes
            ("test[123]", "test1", True),
            ("test[123]", "test2", True),
            ("test[123]", "test4", False),

            # Quantifiers
            ("x+", "x", True),
            ("x+", "xx", True),
            ("x+", "xxx", True),
            ("x+", "y", False),
        ]
        for pattern, name, expected in test_cases:
            with self.subTest(pattern=pattern, name=name):
                result = SearchEngine._matches(pattern, name)
                self.assertEqual(
                    result, expected,
                    f"_matches('{pattern}', '{name}') returned {result}, expected {expected}"
                )


class TestSearchEngineIntegration(unittest.TestCase):
    """Test integration of exact matching with search_classes and search_functions."""

    def setUp(self):
        """Set up test fixtures with sample symbols."""
        # Create sample class symbols
        self.class_symbols = {
            "View": [self._create_class_info("View", "MyProject/View.h", 10)],
            "ViewManager": [self._create_class_info("ViewManager", "MyProject/ViewManager.h", 20)],
            "ListView": [self._create_class_info("ListView", "MyProject/ListView.h", 30)],
            "TreeView": [self._create_class_info("TreeView", "MyProject/TreeView.h", 40)],
            "PreviewPanel": [self._create_class_info("PreviewPanel", "MyProject/PreviewPanel.h", 50)],
            "MyClass": [self._create_class_info("MyClass", "MyProject/MyClass.h", 60)],
        }

        # Create sample function symbols
        self.function_symbols = {
            "getValue": [self._create_function_info("getValue", "MyProject/utils.cpp", 100)],
            "getWidth": [self._create_function_info("getWidth", "MyProject/utils.cpp", 110)],
            "setValue": [self._create_function_info("setValue", "MyProject/utils.cpp", 120)],
            "processData": [self._create_function_info("processData", "MyProject/processor.cpp", 130)],
        }

        # Create search engine
        self.search_engine = SearchEngine(
            class_index=self.class_symbols,
            function_index=self.function_symbols,
            file_index={},
            usr_index={}
        )

    def _create_class_info(self, name, file, line):
        """Helper to create a SymbolInfo for a class."""
        return SymbolInfo(
            name=name,
            kind="class",
            file=file,
            line=line,
            column=0,
            is_project=True,
            signature="",
            parent_class="",
            access="public",
            base_classes=[],
            start_line=line,
            end_line=line + 10,
            header_file=file,
            header_line=line,
            header_start_line=line,
            header_end_line=line + 10,
            brief=None,
            doc_comment=None,
        )

    def _create_function_info(self, name, file, line):
        """Helper to create a SymbolInfo for a function."""
        return SymbolInfo(
            name=name,
            kind="function",
            file=file,
            line=line,
            column=0,
            is_project=True,
            signature="()",
            parent_class="",
            access="public",
            base_classes=[],
            start_line=line,
            end_line=line + 5,
            header_file=None,
            header_line=None,
            header_start_line=None,
            header_end_line=None,
            brief=None,
            doc_comment=None,
        )

    def test_search_classes_exact_match(self):
        """Test that search_classes returns only exact match by default."""
        results = self.search_engine.search_classes("View")

        # Should return only "View", not "ViewManager", "ListView", etc.
        self.assertEqual(len(results), 1, f"Expected 1 result, got {len(results)}: {[r['name'] for r in results]}")
        self.assertEqual(results[0]["name"], "View")

    def test_search_classes_pattern_any(self):
        """Test pattern matching for any class."""
        # .* or .+ should match all classes
        results = self.search_engine.search_classes(".*")

        # Should return all classes
        names = {r["name"] for r in results}
        expected = {"View", "ViewManager", "ListView", "TreeView", "PreviewPanel", "MyClass"}
        self.assertEqual(names, expected)

    def test_search_classes_pattern_prefix(self):
        """Test that search_classes supports prefix pattern matching."""
        results = self.search_engine.search_classes("View.*")

        # Should return classes starting with "View"
        names = {r["name"] for r in results}
        expected = {"View", "ViewManager"}
        self.assertEqual(names, expected)

    def test_search_classes_pattern_suffix(self):
        """Test that search_classes supports suffix pattern matching."""
        results = self.search_engine.search_classes(".*View")

        # Should return classes ending with "View"
        names = {r["name"] for r in results}
        expected = {"View", "ListView", "TreeView"}
        self.assertEqual(names, expected)

    def test_search_functions_exact_match(self):
        """Test that search_functions returns only exact match by default."""
        results = self.search_engine.search_functions("getValue")

        # Should return only "getValue", not "getWidth"
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "getValue")

    def test_search_functions_pattern_prefix(self):
        """Test that search_functions supports prefix pattern matching."""
        results = self.search_engine.search_functions("get.*")

        # Should return all functions starting with "get"
        names = {r["name"] for r in results}
        expected = {"getValue", "getWidth"}
        self.assertEqual(names, expected)

    def test_case_insensitive_exact_match(self):
        """Test that exact matching is case-insensitive."""
        # Test with different cases
        test_cases = ["View", "view", "VIEW", "vIeW"]
        for pattern in test_cases:
            with self.subTest(pattern=pattern):
                results = self.search_engine.search_classes(pattern)
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["name"], "View")

    def test_no_false_positives_exact_match(self):
        """Test that exact match doesn't return substring matches."""
        # Searching for "View" should not return "ViewManager", "ListView", etc.
        results = self.search_engine.search_classes("View")

        # Verify no false positives
        names = {r["name"] for r in results}
        self.assertNotIn("ViewManager", names)
        self.assertNotIn("ListView", names)
        self.assertNotIn("TreeView", names)
        self.assertNotIn("PreviewPanel", names)

    def test_backward_compatibility_with_existing_patterns(self):
        """Test that existing regex patterns still work correctly."""
        # Common patterns that users might already be using
        test_cases = [
            (".*", 6),  # Should match all classes
            ("View.*", 2),  # Should match View, ViewManager (prefix)
            (".*View", 3),  # Should match View, ListView, TreeView (suffix)
            ("[VM].*", 3),  # Should match View, ViewManager, MyClass
        ]

        for pattern, expected_count in test_cases:
            with self.subTest(pattern=pattern):
                results = self.search_engine.search_classes(pattern)
                self.assertEqual(
                    len(results), expected_count,
                    f"Pattern '{pattern}' returned {len(results)} results, expected {expected_count}"
                )


if __name__ == '__main__':
    unittest.main()
