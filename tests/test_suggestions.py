"""
Unit tests for mcp_server/suggestions.py — conditional next-step suggestions.
"""

import pytest
from mcp_server import suggestions
from mcp_server.state_manager import EnhancedQueryResult


# ---------------------------------------------------------------------------
# for_get_class_info
# ---------------------------------------------------------------------------


def test_get_class_info_no_suggestions_for_empty_result():
    assert suggestions.for_get_class_info({}) == []


def test_get_class_info_no_suggestions_on_error():
    assert suggestions.for_get_class_info({"error": "Not found"}) == []


def test_get_class_info_no_suggestions_for_none():
    assert suggestions.for_get_class_info(None) == []  # type: ignore[arg-type]


def test_get_class_info_no_base_class_suggestion():
    result = {
        "qualified_name": "Child",
        "base_classes": ["BaseA"],
        "methods": [],
    }
    hints = suggestions.for_get_class_info(result)
    assert not any("base class" in h for h in hints)
    assert not any("get_class_info('BaseA')" in h for h in hints)


def test_get_class_info_pure_virtual_suggestion():
    result = {
        "qualified_name": "IInterface",
        "base_classes": [],
        "methods": [
            {"prototype": "virtual void foo() = 0", "attributes": ["pure_virtual", "virtual"]},
            {"prototype": "void bar()", "attributes": []},
        ],
    }
    hints = suggestions.for_get_class_info(result)
    assert any("implementation tree" in h for h in hints)
    assert any("get_class_hierarchy('IInterface')" in h for h in hints)
    assert not any("find_symbols_by_pattern" in h and "pure virtual" in h for h in hints)


def test_get_class_info_pimpl_suggestion_from_notes():
    result = {
        "qualified_name": "DOM::Document",
        "methods": [],
        "notes": (
            "Uses PIMPL pattern. Private implementation class is "
            "DOM::DocumentImpl in CoreDOM/Private/DOM_DocumentImpl.h."
        ),
    }
    hints = suggestions.for_get_class_info(result)
    assert any("get_class_info('DOM::DocumentImpl')" in h for h in hints)
    assert any("PIMPL" in h for h in hints)


def test_get_class_info_no_pure_virtual_no_suggestion():
    result = {
        "qualified_name": "Concrete",
        "base_classes": [],
        "methods": [
            {"prototype": "void foo()", "attributes": []},
        ],
    }
    hints = suggestions.for_get_class_info(result)
    assert not any("pure virtual" in h for h in hints)


def test_get_class_info_many_methods_suggestion():
    result = {
        "qualified_name": "BigClass",
        "base_classes": [],
        "methods": [{"prototype": f"void m{i}()", "attributes": []} for i in range(11)],
    }
    hints = suggestions.for_get_class_info(result)
    assert any("filter" in h and "find_symbols_by_pattern" in h for h in hints)


def test_get_class_info_few_methods_no_filter_suggestion():
    result = {
        "qualified_name": "SmallClass",
        "base_classes": [],
        "methods": [{"prototype": f"void m{i}()", "attributes": []} for i in range(5)],
    }
    hints = suggestions.for_get_class_info(result)
    assert not any("filter" in h for h in hints)


def test_get_class_info_no_suggestions_for_leaf_class():
    """Leaf class with no bases and few methods should produce no suggestions."""
    result = {
        "qualified_name": "LeafClass",
        "base_classes": [],
        "methods": [{"prototype": "void run()", "attributes": []}],
    }
    hints = suggestions.for_get_class_info(result)
    assert hints == []


# ---------------------------------------------------------------------------
# for_search_classes
# ---------------------------------------------------------------------------


def test_search_classes_empty_returns_no_hints():
    assert suggestions.for_search_classes([]) == []


def test_search_classes_single_result():
    results = [{"qualified_name": "ns::MyClass", "name": "MyClass"}]
    hints = suggestions.for_search_classes(results)
    assert hints == []


def test_search_classes_three_results():
    results = [
        {"qualified_name": "A"},
        {"qualified_name": "B"},
        {"qualified_name": "C"},
    ]
    hints = suggestions.for_search_classes(results)
    assert hints == []


def test_search_classes_more_than_three_results():
    results = [{"qualified_name": f"Class{i}"} for i in range(5)]
    hints = suggestions.for_search_classes(results, pattern="Widget")
    # Only top match suggested when >3 results
    assert len(hints) == 1
    assert "get_class_info('Class0')" in hints[0]
    assert "top match" in hints[0]


def test_search_classes_uses_name_fallback():
    results = [
        {"qualified_name": "Class0"},
        {"qualified_name": "Class1"},
        {"qualified_name": "Class2"},
        {"name": "FallbackClass"},
    ]
    hints = suggestions.for_search_classes(results, pattern="Widget")
    assert len(hints) == 1
    assert "get_class_info('Class0')" in hints[0]


def test_search_classes_no_hints_for_file_enumeration():
    results = [{"qualified_name": f"Class{i}"} for i in range(5)]
    hints = suggestions.for_search_classes(results, pattern="", file_name="CoreDOM/Tests/")
    assert hints == []


def test_search_classes_no_hints_for_namespace_enumeration():
    results = [{"qualified_name": f"Class{i}"} for i in range(5)]
    hints = suggestions.for_search_classes(results, pattern="", namespace="DOM")
    assert hints == []


# ---------------------------------------------------------------------------
# for_search_functions
# ---------------------------------------------------------------------------


def test_search_functions_empty_returns_no_hints():
    assert suggestions.for_search_functions([]) == []


def test_search_functions_no_parent_class():
    results = [{"qualified_name": "freeFunc", "parent_class": None}]
    hints = suggestions.for_search_functions(results)
    assert hints == []


def test_search_functions_with_parent_class():
    results = [{"qualified_name": "MyClass::foo", "parent_class": "MyClass"}]
    hints = suggestions.for_search_functions(results)
    assert hints == []


def test_search_functions_unique_parents_capped_at_2():
    results = [
        {"qualified_name": "A::foo", "parent_class": "A"},
        {"qualified_name": "B::bar", "parent_class": "B"},
        {"qualified_name": "C::baz", "parent_class": "C"},
    ]
    hints = suggestions.for_search_functions(results)
    assert hints == []


def test_search_functions_deduplicates_parent_class():
    results = [
        {"qualified_name": "Widget::show", "parent_class": "Widget"},
        {"qualified_name": "Widget::hide", "parent_class": "Widget"},
    ]
    hints = suggestions.for_search_functions(results)
    assert hints == []


# ---------------------------------------------------------------------------
# for_get_incoming_calls
# ---------------------------------------------------------------------------


def test_get_incoming_calls_empty_callers_no_hints():
    assert suggestions.for_get_incoming_calls("doThing", {"callers": []}) == []


def test_get_incoming_calls_non_empty_callers():
    result_data = {"callers": [{"caller": "main", "file": "a.cpp", "line": 10}]}
    hints = suggestions.for_get_incoming_calls("doThing", result_data)
    assert len(hints) == 1
    assert "get_functions_called_by('doThing')" in hints[0]
    assert "complements" in hints[0]


def test_get_incoming_calls_non_dict_result_no_hints():
    hints = suggestions.for_get_incoming_calls("doThing", [])  # type: ignore[arg-type]
    assert hints == []


def test_get_incoming_calls_uses_qualified_name_in_hint():
    result_data = {"callers": [{"caller": "main", "file": "a.cpp", "line": 10}]}
    hints = suggestions.for_get_incoming_calls(
        "build", result_data, qualified_name="NS::Cls::build"
    )
    assert len(hints) == 1
    assert "get_functions_called_by('NS::Cls::build')" in hints[0]
    assert "build" not in hints[0].replace("NS::Cls::build", "")


def test_get_incoming_calls_falls_back_to_function_name_when_no_qualified():
    result_data = {"callers": [{"caller": "main", "file": "a.cpp", "line": 10}]}
    hints = suggestions.for_get_incoming_calls("doThing", result_data, qualified_name=None)
    assert "get_functions_called_by('doThing')" in hints[0]


# ---------------------------------------------------------------------------
# for_get_outgoing_calls
# ---------------------------------------------------------------------------


def test_get_outgoing_calls_empty_callees_no_hints():
    assert suggestions.for_get_outgoing_calls("process", {"callees": []}) == []


def test_get_outgoing_calls_non_empty_callees():
    result_data = {"callees": [{"callee": "helper", "file": "b.cpp", "line": 5}]}
    hints = suggestions.for_get_outgoing_calls("process", result_data)
    assert len(hints) == 1
    assert "get_functions_called_by('process', return_format='exact_call_line_locations')" in hints[0]
    assert "function body" in hints[0]


def test_get_outgoing_calls_non_dict_result_no_hints():
    hints = suggestions.for_get_outgoing_calls("process", [])  # type: ignore[arg-type]
    assert hints == []


def test_get_outgoing_calls_uses_qualified_name_in_hint():
    result_data = {"callees": [{"callee": "helper", "file": "b.cpp", "line": 5}]}
    hints = suggestions.for_get_outgoing_calls(
        "builder", result_data, qualified_name="NS::Doc::builder"
    )
    assert len(hints) == 1
    assert (
        "get_functions_called_by('NS::Doc::builder', return_format='exact_call_line_locations')"
        in hints[0]
    )
    assert "builder" in hints[0]
    assert "process" not in hints[0]


def test_get_outgoing_calls_falls_back_to_function_name_when_no_qualified():
    result_data = {"callees": [{"callee": "helper", "file": "b.cpp", "line": 5}]}
    hints = suggestions.for_get_outgoing_calls("process", result_data, qualified_name=None)
    assert "get_functions_called_by('process', return_format='exact_call_line_locations')" in hints[0]


# ---------------------------------------------------------------------------
# EnhancedQueryResult.to_dict() smoke tests
# ---------------------------------------------------------------------------


def test_enhanced_result_next_steps_in_metadata():
    result = EnhancedQueryResult(data=[1, 2, 3], next_steps=["do_this()", "do_that()"])
    d = result.to_dict()
    assert "metadata" in d
    assert d["metadata"]["next_steps"] == ["do_this()", "do_that()"]
    assert "data" in d


def test_enhanced_result_no_next_steps_no_metadata():
    result = EnhancedQueryResult(data=[1, 2, 3])
    d = result.to_dict()
    assert "metadata" not in d


def test_enhanced_result_create_normal_with_next_steps():
    result = EnhancedQueryResult.create_normal(data={"x": 1}, next_steps=["hint()"])
    d = result.to_dict()
    assert d["metadata"]["next_steps"] == ["hint()"]


def test_enhanced_result_create_normal_no_next_steps():
    result = EnhancedQueryResult.create_normal(data={"x": 1})
    d = result.to_dict()
    assert "metadata" not in d


# ---------------------------------------------------------------------------
# for_get_call_sites_empty
# ---------------------------------------------------------------------------


def test_get_call_sites_empty_basic():
    hints = suggestions.for_get_call_sites_empty("doThing")
    assert len(hints) == 1
    assert "doThing" in hints[0]
    assert "get_functions_called_by('doThing')" in hints[0]
    assert "search_scope='include_external_libraries'" in hints[0]


def test_get_call_sites_empty_with_class_name():
    hints = suggestions.for_get_call_sites_empty("builder", class_name="MyClass")
    assert len(hints) == 1
    assert "MyClass::builder" in hints[0]
    assert "get_functions_called_by('MyClass::builder')" in hints[0]


def test_get_call_sites_empty_no_class_name():
    hints = suggestions.for_get_call_sites_empty("process", class_name="")
    assert "get_functions_called_by('process')" in hints[0]
    assert "::" not in hints[0].split("get_functions_called_by")[1].split(")")[0]


# ---------------------------------------------------------------------------
# for_get_call_path_empty
# ---------------------------------------------------------------------------


def test_get_call_path_empty_includes_functions_and_depth():
    hints = suggestions.for_get_call_path_empty("main", "leaf", max_depth=10)
    assert len(hints) == 1
    assert "main" in hints[0]
    assert "leaf" in hints[0]
    assert "max_depth=10" in hints[0]
    assert "find_symbols_by_pattern" in hints[0]


def test_get_call_path_empty_suggests_increasing_depth():
    hints = suggestions.for_get_call_path_empty("A", "B", max_depth=5)
    assert "max_depth=5" in hints[0]
    assert "increasing max_depth" in hints[0]
