"""Integration tests for smart fallback with CppAnalyzer search methods.

Tests that SmartFallback is properly called when searches return empty results,
and that fallback suggestions flow through the full pipeline.
"""

import threading
import unittest

from mcp_server.search_engine import SearchEngine
from mcp_server.smart_fallback import SmartFallback
from mcp_server.state_manager import EnhancedQueryResult, AnalyzerStateManager, AnalyzerState
from mcp_server.symbol_info import SymbolInfo


def _create_symbol(name, kind="class", file="test.h", line=1, qualified_name=None,
                   namespace="", is_project=True):
    """Create a SymbolInfo for testing."""
    return SymbolInfo(
        name=name,
        qualified_name=qualified_name or name,
        kind=kind,
        file=file,
        line=line,
        column=0,
        is_project=is_project,
        signature=f"void {name}()" if kind == "function" else "",
        parent_class="",
        access="public",
        base_classes=[],
        start_line=line,
        end_line=line + 10,
        header_file=file if kind == "class" else None,
        header_line=line if kind == "class" else None,
        header_start_line=line if kind == "class" else None,
        header_end_line=line + 10 if kind == "class" else None,
        brief=None,
        doc_comment=None,
        namespace=namespace,
    )


class TestSmartFallbackWithSearchEngine(unittest.TestCase):
    """Test SmartFallback triggered through SearchEngine pipeline."""

    def setUp(self):
        self.class_index = {
            "Handler": [
                _create_symbol("Handler", qualified_name="app::Handler",
                               namespace="app", file="handler.h", line=5),
            ],
            "Widget": [
                _create_symbol("Widget", qualified_name="ui::Widget",
                               namespace="ui", file="Widget.h", line=10),
            ],
            "ConsoleReporter": [
                _create_symbol("ConsoleReporter", qualified_name="test::ConsoleReporter",
                               namespace="test", file="reporter.h", line=20),
            ],
            "CompactReporter": [
                _create_symbol("CompactReporter", qualified_name="test::CompactReporter",
                               namespace="test", file="reporter.h", line=40),
            ],
        }
        self.function_index = {
            "processData": [
                _create_symbol("processData", kind="function",
                               qualified_name="app::processData",
                               namespace="app", file="processor.cpp", line=15),
            ],
            "handleEvent": [
                _create_symbol("handleEvent", kind="function",
                               qualified_name="app::Handler::handleEvent",
                               namespace="app", file="handler.cpp", line=25),
            ],
        }
        self.file_index = {
            "handler.h": [self.class_index["Handler"][0]],
            "Widget.h": [self.class_index["Widget"][0]],
            "reporter.h": (
                [self.class_index["ConsoleReporter"][0]]
                + [self.class_index["CompactReporter"][0]]
            ),
            "processor.cpp": [self.function_index["processData"][0]],
            "handler.cpp": [self.function_index["handleEvent"][0]],
        }
        self.index_lock = threading.RLock()
        self.search_engine = SearchEngine(
            class_index=self.class_index,
            function_index=self.function_index,
            file_index=self.file_index,
            usr_index={},
            index_lock=self.index_lock,
        )
        self.smart_fallback = SmartFallback()

    def _search_with_fallback(self, pattern, tool_name="search_classes",
                              file_name=None, namespace=None, class_name=None):
        """Run search and generate fallback if empty."""
        if tool_name == "search_classes":
            results = self.search_engine.search_classes(pattern, file_name=file_name,
                                                        namespace=namespace)
        elif tool_name == "search_functions":
            results = self.search_engine.search_functions(pattern, file_name=file_name,
                                                          namespace=namespace,
                                                          class_name=class_name)
        else:
            results = self.search_engine.search_symbols(pattern, namespace=namespace)

        if not results or (isinstance(results, dict) and
                           not any(results.get(k) for k in ["classes", "functions"])):
            fallback = self.smart_fallback.analyze_empty_result(
                pattern=pattern,
                tool_name=tool_name,
                class_index=self.class_index,
                function_index=self.function_index,
                file_index=self.file_index,
                file_name=file_name,
                namespace=namespace,
                class_name=class_name,
            )
            return results, fallback
        return results, None

    def test_signature_pattern_triggers_fallback(self):
        """When user passes a signature, get structured suggestion."""
        results, fallback = self._search_with_fallback(
            "void processData(int x)", tool_name="search_functions"
        )
        self.assertEqual(results, [])
        self.assertIsNotNone(fallback)
        self.assertEqual(fallback.reason, "signature_detected")
        self.assertEqual(fallback.suggested_pattern, "processData")
        self.assertTrue(len(fallback.alternatives) > 0)

    def test_qualified_name_wrong_namespace(self):
        """When qualified name has wrong namespace, suggest correct one."""
        results, fallback = self._search_with_fallback(
            "wrong::ns::Handler", tool_name="search_classes"
        )
        self.assertEqual(results, [])
        self.assertIsNotNone(fallback)
        self.assertEqual(fallback.reason, "qualified_fallback")
        self.assertEqual(fallback.suggested_pattern, "Handler")
        self.assertTrue(any(
            alt["qualified_name"] == "app::Handler"
            for alt in fallback.alternatives
        ))

    def test_regex_with_dollar_anchor(self):
        """When regex uses $ anchor, suggest fullmatch-compatible version."""
        results, fallback = self._search_with_fallback(
            "Reporter$", tool_name="search_classes"
        )
        self.assertEqual(results, [])
        self.assertIsNotNone(fallback)
        self.assertEqual(fallback.reason, "regex_hint")
        self.assertEqual(fallback.suggested_pattern, ".*Reporter")
        self.assertTrue(len(fallback.alternatives) > 0)

    def test_no_fallback_when_results_found(self):
        """When search finds results, no fallback generated."""
        results, fallback = self._search_with_fallback(
            "Handler", tool_name="search_classes"
        )
        self.assertGreater(len(results), 0)
        self.assertIsNone(fallback)

    def test_no_fallback_for_unknown_pattern(self):
        """When pattern simply doesn't match anything, return None."""
        results, fallback = self._search_with_fallback(
            "TotallyUnknownSymbol", tool_name="search_classes"
        )
        self.assertEqual(results, [])
        self.assertIsNone(fallback)


class TestFallbackInEnhancedQueryResult(unittest.TestCase):
    """Test that FallbackResult integrates with EnhancedQueryResult."""

    def test_create_empty_with_fallback(self):
        """EnhancedQueryResult.create_empty should format fallback metadata."""
        from mcp_server.smart_fallback import FallbackResult

        fallback = FallbackResult(
            reason="signature_detected",
            searched_for="void process(int x)",
            hint="Use just the name 'process'.",
            suggested_pattern="process",
            alternatives=[{"name": "process", "qualified_name": "app::process",
                          "file": "test.cpp", "line": 10}],
        )
        result = EnhancedQueryResult.create_empty([], fallback=fallback)
        d = result.to_dict()

        self.assertEqual(d["data"], [])
        self.assertIn("metadata", d)
        self.assertEqual(d["metadata"]["status"], "empty")
        self.assertIn("fallback", d["metadata"])
        fb = d["metadata"]["fallback"]
        self.assertEqual(fb["reason"], "signature_detected")
        self.assertEqual(fb["suggested_pattern"], "process")
        self.assertTrue(len(fb["alternatives"]) == 1)

    def test_create_empty_without_fallback(self):
        """Without fallback, create_empty returns generic suggestions."""
        result = EnhancedQueryResult.create_empty([])
        d = result.to_dict()

        self.assertIn("metadata", d)
        self.assertIn("suggestions", d["metadata"])
        self.assertNotIn("fallback", d["metadata"])

    def test_create_empty_with_none_fallback(self):
        """Explicit None fallback behaves like no fallback."""
        result = EnhancedQueryResult.create_empty([], fallback=None)
        d = result.to_dict()

        self.assertIn("suggestions", d["metadata"])
        self.assertNotIn("fallback", d["metadata"])


if __name__ == "__main__":
    unittest.main()
