import threading
import time
import pytest
from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server.state_manager import AnalyzerStateManager
from mcp_server.symbol_info import SymbolInfo


def test_dict_size_changed_race():
    analyzer = CppAnalyzer("/tmp/dummy")
    analyzer.class_index["MyClass"] = [
        SymbolInfo("MyClass", "class", "dummy.cpp", 1, 1, qualified_name="MyClass")
    ]

    stop_event = threading.Event()
    race_detected = False

    def background_indexer():
        i = 0
        while not stop_event.is_set():
            with analyzer.index_lock:
                analyzer.class_index[f"Class_{i}"] = [
                    SymbolInfo(f"Class_{i}", "class", "dummy.cpp", 1, 1)
                ]
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
