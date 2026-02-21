#!/usr/bin/env python3
"""
Tests for signature_pattern parameter in search_functions and search_symbols.

This module tests the case-insensitive substring matching against function signatures,
allowing users to filter by parameter types, return types, or any part of the signature.
"""

import os
import sys
import threading
import unittest

# Add the mcp_server directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp_server.search_engine import SearchEngine
from mcp_server.symbol_info import SymbolInfo


class TestSignaturePattern(unittest.TestCase):
    """Test signature_pattern filtering in search_functions."""

    def setUp(self):
        """Set up test fixtures with functions having various signatures."""
        self.function_symbols = {
            "processData": [
                self._create_function_info(
                    "processData",
                    "MyProject/processor.cpp",
                    10,
                    "void processData(const std::string &input, int count)",
                )
            ],
            "calculateArea": [
                self._create_function_info(
                    "calculateArea",
                    "MyProject/math.cpp",
                    20,
                    "double calculateArea(double width, double height)",
                )
            ],
            "getWidget": [
                self._create_function_info(
                    "getWidget",
                    "MyProject/ui.cpp",
                    30,
                    "Widget * getWidget(const std::string &name)",
                )
            ],
            "setCallback": [
                self._create_function_info(
                    "setCallback",
                    "MyProject/events.cpp",
                    40,
                    "void setCallback(std::function<void(int)> callback)",
                )
            ],
            "handleEvent": [
                self._create_function_info(
                    "handleEvent",
                    "MyProject/events.cpp",
                    50,
                    "bool handleEvent(const Event &event)",
                )
            ],
            "noSignature": [
                self._create_function_info(
                    "noSignature",
                    "MyProject/misc.cpp",
                    60,
                    "",
                )
            ],
            "nullSignature": [
                self._create_function_info(
                    "nullSignature",
                    "MyProject/misc.cpp",
                    70,
                    None,
                )
            ],
        }

        self.index_lock = threading.RLock()
        self.search_engine = SearchEngine(
            class_index={},
            function_index=self.function_symbols,
            file_index={},
            usr_index={},
            index_lock=self.index_lock,
        )

    def _create_function_info(self, name, file, line, signature):
        """Helper to create a SymbolInfo for a function."""
        return SymbolInfo(
            name=name,
            qualified_name=name,
            kind="function",
            file=file,
            line=line,
            column=0,
            is_project=True,
            signature=signature,
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

    def test_substring_match(self):
        """Test basic substring matching against signatures."""
        results = self.search_engine.search_functions(".*", signature_pattern="std::string")
        names = {r["qualified_name"].split("::")[-1] for r in results}
        self.assertEqual(names, {"processData", "getWidget"})

    def test_case_insensitive(self):
        """Test that signature matching is case-insensitive."""
        results_lower = self.search_engine.search_functions(
            ".*", signature_pattern="std::string"
        )
        results_upper = self.search_engine.search_functions(
            ".*", signature_pattern="STD::STRING"
        )
        results_mixed = self.search_engine.search_functions(
            ".*", signature_pattern="Std::String"
        )
        names_lower = {r["qualified_name"].split("::")[-1] for r in results_lower}
        names_upper = {r["qualified_name"].split("::")[-1] for r in results_upper}
        names_mixed = {r["qualified_name"].split("::")[-1] for r in results_mixed}
        self.assertEqual(names_lower, names_upper)
        self.assertEqual(names_lower, names_mixed)

    def test_return_type_match(self):
        """Test matching against return type in signature."""
        results = self.search_engine.search_functions(".*", signature_pattern="double")
        names = {r["qualified_name"].split("::")[-1] for r in results}
        self.assertEqual(names, {"calculateArea"})

    def test_special_characters_literal(self):
        """Test that special characters are matched literally (not as regex)."""
        # Match pointer syntax
        results = self.search_engine.search_functions(".*", signature_pattern="Widget *")
        names = {r["qualified_name"].split("::")[-1] for r in results}
        self.assertEqual(names, {"getWidget"})

        # Match reference syntax
        results = self.search_engine.search_functions(".*", signature_pattern="&")
        names = {r["qualified_name"].split("::")[-1] for r in results}
        self.assertIn("processData", names)
        self.assertIn("getWidget", names)
        self.assertIn("handleEvent", names)

    def test_template_angle_brackets(self):
        """Test matching angle brackets in template types."""
        results = self.search_engine.search_functions(
            ".*", signature_pattern="std::function<void(int)>"
        )
        names = {r["qualified_name"].split("::")[-1] for r in results}
        self.assertEqual(names, {"setCallback"})

    def test_no_match_returns_empty(self):
        """Test that non-matching pattern returns empty results."""
        results = self.search_engine.search_functions(
            ".*", signature_pattern="NonExistentType"
        )
        self.assertEqual(len(results), 0)

    def test_empty_signature_excluded(self):
        """Test that functions with empty signatures are excluded when pattern specified."""
        results = self.search_engine.search_functions(".*", signature_pattern="void")
        names = {r["qualified_name"].split("::")[-1] for r in results}
        # noSignature has "" signature, nullSignature has None — neither should match
        self.assertNotIn("noSignature", names)
        self.assertNotIn("nullSignature", names)
        # processData and setCallback have "void" in their signatures
        self.assertIn("processData", names)
        self.assertIn("setCallback", names)

    def test_none_preserves_existing_behavior(self):
        """Test that signature_pattern=None returns all matching functions (no filtering)."""
        results_with_none = self.search_engine.search_functions(
            ".*", signature_pattern=None
        )
        results_default = self.search_engine.search_functions(".*")
        self.assertEqual(len(results_with_none), len(results_default))

    def test_combined_with_name_pattern(self):
        """Test that signature_pattern AND name pattern are both applied (AND logic)."""
        # Name pattern: starts with "get" or "set"
        results = self.search_engine.search_functions(
            "get.*", signature_pattern="std::string"
        )
        names = {r["qualified_name"].split("::")[-1] for r in results}
        # Only getWidget matches both "get.*" name AND "std::string" in signature
        self.assertEqual(names, {"getWidget"})

    def test_combined_with_max_results(self):
        """Test that signature_pattern works correctly with max_results truncation."""
        # Get all functions with "void" in signature (should be processData, setCallback)
        results_all = self.search_engine.search_functions(
            ".*", signature_pattern="void"
        )
        self.assertGreaterEqual(len(results_all), 2)

        # Now limit to 1 result
        results_limited, total_count = self.search_engine.search_functions(
            ".*", signature_pattern="void", max_results=1
        )
        self.assertEqual(len(results_limited), 1)
        self.assertEqual(total_count, len(results_all))

    def test_bool_return_type(self):
        """Test matching bool return type."""
        results = self.search_engine.search_functions(".*", signature_pattern="bool")
        names = {r["qualified_name"].split("::")[-1] for r in results}
        self.assertEqual(names, {"handleEvent"})


class TestSignaturePatternSearchSymbols(unittest.TestCase):
    """Test that search_symbols passes signature_pattern to functions only."""

    def setUp(self):
        """Set up test fixtures with both classes and functions."""
        self.class_symbols = {
            "StringProcessor": [
                SymbolInfo(
                    name="StringProcessor",
                    kind="class",
                    file="MyProject/processor.h",
                    line=5,
                    column=0,
                    is_project=True,
                    signature="",
                    parent_class="",
                    access="public",
                    base_classes=[],
                    start_line=5,
                    end_line=50,
                    header_file="MyProject/processor.h",
                    header_line=5,
                    header_start_line=5,
                    header_end_line=50,
                    brief=None,
                    doc_comment=None,
                )
            ],
        }

        self.function_symbols = {
            "process": [
                SymbolInfo(
                    name="process",
                    kind="function",
                    file="MyProject/processor.cpp",
                    line=10,
                    column=0,
                    is_project=True,
                    signature="void process(const std::string &input)",
                    parent_class="",
                    access="public",
                    base_classes=[],
                    start_line=10,
                    end_line=20,
                    header_file=None,
                    header_line=None,
                    header_start_line=None,
                    header_end_line=None,
                    brief=None,
                    doc_comment=None,
                )
            ],
            "calculate": [
                SymbolInfo(
                    name="calculate",
                    kind="function",
                    file="MyProject/math.cpp",
                    line=30,
                    column=0,
                    is_project=True,
                    signature="int calculate(int a, int b)",
                    parent_class="",
                    access="public",
                    base_classes=[],
                    start_line=30,
                    end_line=40,
                    header_file=None,
                    header_line=None,
                    header_start_line=None,
                    header_end_line=None,
                    brief=None,
                    doc_comment=None,
                )
            ],
        }

        self.index_lock = threading.RLock()
        self.search_engine = SearchEngine(
            class_index=self.class_symbols,
            function_index=self.function_symbols,
            file_index={},
            usr_index={},
            index_lock=self.index_lock,
        )

    def test_search_symbols_filters_functions_only(self):
        """Test that signature_pattern filters functions but classes remain unaffected."""
        results = self.search_engine.search_symbols(
            ".*", signature_pattern="std::string"
        )
        # Classes should still be returned (signature_pattern doesn't apply to classes)
        self.assertEqual(len(results["classes"]), 1)
        self.assertEqual(results["classes"][0]["qualified_name"].split("::")[-1], "StringProcessor")
        # Only "process" function has std::string in signature
        self.assertEqual(len(results["functions"]), 1)
        self.assertEqual(results["functions"][0]["qualified_name"].split("::")[-1], "process")

    def test_search_symbols_none_preserves_behavior(self):
        """Test that signature_pattern=None in search_symbols returns everything."""
        results = self.search_engine.search_symbols(".*", signature_pattern=None)
        self.assertEqual(len(results["classes"]), 1)
        self.assertEqual(len(results["functions"]), 2)

    def test_search_symbols_no_function_match(self):
        """Test that non-matching signature_pattern empties functions but keeps classes."""
        results = self.search_engine.search_symbols(
            ".*", signature_pattern="NonExistentType"
        )
        # Classes should still be returned
        self.assertEqual(len(results["classes"]), 1)
        # No functions match
        self.assertEqual(len(results["functions"]), 0)


class TestSignaturePatternWithFileIndex(unittest.TestCase):
    """Test signature_pattern works in the file_name branch (file_index path)."""

    def setUp(self):
        """Set up test fixtures with file_index populated."""
        func1 = SymbolInfo(
            name="readFile",
            kind="function",
            file="MyProject/io.cpp",
            line=10,
            column=0,
            is_project=True,
            signature="std::string readFile(const char *path)",
            parent_class="",
            access="public",
            base_classes=[],
            start_line=10,
            end_line=20,
            header_file=None,
            header_line=None,
            header_start_line=None,
            header_end_line=None,
            brief=None,
            doc_comment=None,
        )
        func2 = SymbolInfo(
            name="writeFile",
            kind="function",
            file="MyProject/io.cpp",
            line=25,
            column=0,
            is_project=True,
            signature="bool writeFile(const char *path, const std::string &data)",
            parent_class="",
            access="public",
            base_classes=[],
            start_line=25,
            end_line=35,
            header_file=None,
            header_line=None,
            header_start_line=None,
            header_end_line=None,
            brief=None,
            doc_comment=None,
        )

        self.file_index = {
            "MyProject/io.cpp": [func1, func2],
        }

        self.index_lock = threading.RLock()
        self.search_engine = SearchEngine(
            class_index={},
            function_index={},
            file_index=self.file_index,
            usr_index={},
            index_lock=self.index_lock,
        )

    def test_file_name_branch_with_signature_pattern(self):
        """Test that signature_pattern works when file_name triggers file_index path."""
        results = self.search_engine.search_functions(
            "", file_name="io.cpp", signature_pattern="bool"
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["qualified_name"].split("::")[-1], "writeFile")

    def test_file_name_branch_no_match(self):
        """Test no match in file_index path."""
        results = self.search_engine.search_functions(
            "", file_name="io.cpp", signature_pattern="double"
        )
        self.assertEqual(len(results), 0)

    def test_file_name_branch_all_match(self):
        """Test that both functions match when pattern is in both signatures."""
        results = self.search_engine.search_functions(
            "", file_name="io.cpp", signature_pattern="const char *"
        )
        names = {r["qualified_name"].split("::")[-1] for r in results}
        self.assertEqual(names, {"readFile", "writeFile"})


if __name__ == "__main__":
    unittest.main()
