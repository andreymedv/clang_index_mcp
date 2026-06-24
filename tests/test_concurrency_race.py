import threading
import time
import pytest
from clang_index_mcp.cpp_analyzer import CppAnalyzer
from clang_index_mcp._mcp.state_manager import AnalyzerStateManager
from clang_index_mcp._symbols.model import SymbolInfo


def test_dict_size_changed_race():
    analyzer = CppAnalyzer("/tmp/dummy")
    analyzer.context.symbol_store.class_index["MyClass"] = [
        SymbolInfo("MyClass", "class", "dummy.cpp", 1, 1, qualified_name="MyClass")
    ]

    stop_event = threading.Event()
    race_detected = False

    def background_indexer():
        i = 0
        while not stop_event.is_set():
            key = f"Class_{i}"
            with analyzer.context.concurrency.index_lock:
                analyzer.context.symbol_store.class_index[key] = [
                    SymbolInfo(key, "class", "dummy.cpp", 1, 1)
                ]
                # Keep dict small to avoid slow iteration in the main thread
                if len(analyzer.context.symbol_store.class_index) > 100:
                    oldest = f"Class_{i - 100}"
                    analyzer.context.symbol_store.class_index.pop(oldest, None)
            i += 1

    t = threading.Thread(target=background_indexer)
    t.start()

    try:
        for _ in range(1000):
            try:
                analyzer.search_classes("NonExistentClass")
            except RuntimeError as e:
                if "dictionary changed size during iteration" in str(e):
                    race_detected = True
                    break
                raise
    finally:
        stop_event.set()
        t.join()

    # The unmodified code should have a race condition.
    # If the test is running on unmodified code, it should fail here, or we just assert it doesn't fail AFTER the fix.
    # We want the test to pass ONLY if the race is fixed.
    assert not race_detected, "RuntimeError: dictionary changed size during iteration"
