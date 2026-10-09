"""
Regression tests for cplusplus_mcp-2601: get_class_hierarchy edge scoping.

Before the fix, collect_hierarchy_node_data attached FULL base_classes and
derived_classes lists to every node regardless of traversal direction, so a
direction='down' query on B1 returned node D (MI: B1+B2) with
base_classes=['B1','B2'] — sibling base B2 leaked into B1's diagram without
being a node in it (symmetric leak for direction='up' via full derived lists).

Fix: edge_scope='path' (default) restricts every node's edge lists to nodes
present in the result graph, making the response a sound reachability graph;
edge_scope='full' preserves the pre-fix output exactly.

Fixture: tests/fixtures/hierarchy_edge_scope/main.cpp
  B1, B2 (abstract), D : B1, B2; E, C1, C2 : B1; M : C1, C2
"""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from clang_index_mcp.cpp_analyzer import CppAnalyzer
from tests.utils._helpers import temp_compile_commands

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "hierarchy_edge_scope"


@pytest.fixture(scope="module")
def analyzer(tmp_path_factory):
    """Index the hierarchy_edge_scope fixture project once per module."""
    tmp_path = tmp_path_factory.mktemp("hierarchy_edge_scope")
    shutil.copy2(FIXTURE_DIR / "main.cpp", tmp_path / "main.cpp")

    temp_compile_commands(
        tmp_path,
        [
            {
                "file": "main.cpp",
                "directory": str(tmp_path),
                "arguments": ["-std=c++17", "-I", str(tmp_path)],
            }
        ],
    )

    a = CppAnalyzer(str(tmp_path))
    a.index_project()

    yield a

    if hasattr(a, "cache_manager"):
        cache_dir = a.cache_manager.cache_dir
        a.cache_manager.close()
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)


# =============================================================================
# Helpers
# =============================================================================


def get_node(result, simple_name):
    """Return the node dict for a class by simple name (fails if missing)."""
    for key, data in result.get("classes", {}).items():
        if key.split("::")[-1] == simple_name:
            return data
    pytest.fail(f"{simple_name} not found in result")


def get_simple_names(result):
    """Extract set of simple class names from hierarchy result."""
    return {k.split("::")[-1] for k in result.get("classes", {})}


def simple(edges):
    """Reduce edge lists to simple names for order-independent comparison."""
    return {e.split("::")[-1] for e in edges}


# =============================================================================
# direction='down' — sibling co-base must not leak (the reported bug)
# =============================================================================


class TestPathScopeDown:
    def test_sibling_base_not_a_node(self, analyzer):
        result = analyzer.get_class_hierarchy("B1", direction="down")
        names = get_simple_names(result)
        assert {"B1", "D", "E", "C1", "C2", "M"} == names
        assert "B2" not in names

    def test_sibling_base_nowhere_in_payload(self, analyzer):
        result = analyzer.get_class_hierarchy("B1", direction="down")
        assert "B2" not in json.dumps(result)

    def test_mi_node_keeps_only_in_graph_bases(self, analyzer):
        result = analyzer.get_class_hierarchy("B1", direction="down")
        node_d = get_node(result, "D")
        assert simple(node_d["base_classes"]) == {"B1"}

    def test_start_node_has_no_bases_in_down_mode(self, analyzer):
        result = analyzer.get_class_hierarchy("B1", direction="down")
        node_b1 = get_node(result, "B1")
        assert node_b1["base_classes"] == []

    def test_mi_reached_via_several_in_graph_bases_keeps_all(self, analyzer):
        """M is genuinely MI-reached via C1 and C2, both in the traversal."""
        result = analyzer.get_class_hierarchy("B1", direction="down")
        node_m = get_node(result, "M")
        assert simple(node_m["base_classes"]) == {"C1", "C2"}

    def test_full_scope_preserves_pre_fix_output(self, analyzer):
        """edge_scope='full' must reproduce the exact pre-fix behavior."""
        result = analyzer.get_class_hierarchy("B1", direction="down", edge_scope="full")
        assert "B2" not in get_simple_names(result)
        node_d = get_node(result, "D")
        assert simple(node_d["base_classes"]) == {"B1", "B2"}
        node_b1 = get_node(result, "B1")
        assert simple(node_b1["derived_classes"]) == {"D", "E", "C1", "C2"}


# =============================================================================
# direction='up' — sibling derived must not leak (symmetric leak)
# =============================================================================


class TestPathScopeUp:
    def test_sibling_derived_not_a_node(self, analyzer):
        result = analyzer.get_class_hierarchy("D", direction="up")
        names = get_simple_names(result)
        assert {"D", "B1", "B2"} == names
        assert "E" not in names

    def test_sibling_derived_nowhere_in_payload(self, analyzer):
        result = analyzer.get_class_hierarchy("D", direction="up")
        assert "E" not in json.dumps(result)

    def test_ancestor_derived_scoped_to_path(self, analyzer):
        result = analyzer.get_class_hierarchy("D", direction="up")
        assert simple(get_node(result, "B1")["derived_classes"]) == {"D"}
        assert simple(get_node(result, "B2")["derived_classes"]) == {"D"}

    def test_up_traversal_relation_unaffected(self, analyzer):
        """bases are the traversal relation going up — both bases stay."""
        result = analyzer.get_class_hierarchy("D", direction="up")
        assert simple(get_node(result, "D")["base_classes"]) == {"B1", "B2"}

    def test_full_scope_preserves_pre_fix_output(self, analyzer):
        result = analyzer.get_class_hierarchy("D", direction="up", edge_scope="full")
        node_b1 = get_node(result, "B1")
        assert {"D", "E", "C1", "C2"} <= simple(node_b1["derived_classes"])


# =============================================================================
# direction='both' — leaks appear on both sides of the queried class
# =============================================================================


class TestPathScopeBoth:
    def test_both_d_scopes_derived_lists(self, analyzer):
        result = analyzer.get_class_hierarchy("D", direction="both")
        names = get_simple_names(result)
        assert {"D", "B1", "B2"} == names
        assert "E" not in json.dumps(result)
        assert simple(get_node(result, "B1")["derived_classes"]) == {"D"}

    def test_both_b1_scopes_mi_node_bases(self, analyzer):
        result = analyzer.get_class_hierarchy("B1", direction="both")
        assert simple(get_node(result, "D")["base_classes"]) == {"B1"}
        assert simple(get_node(result, "B1")["derived_classes"]) == {"D", "E", "C1", "C2"}


# =============================================================================
# Parameter handling and graph soundness
# =============================================================================


class TestEdgeScopeParameter:
    def test_default_is_path(self, analyzer):
        result = analyzer.get_class_hierarchy("B1", direction="down")
        assert result["edge_scope"] == "path"
        assert simple(get_node(result, "D")["base_classes"]) == {"B1"}

    def test_result_reports_edge_scope_full(self, analyzer):
        result = analyzer.get_class_hierarchy("B1", direction="down", edge_scope="full")
        assert result["edge_scope"] == "full"

    def test_invalid_edge_scope_returns_error(self, analyzer):
        result = analyzer.get_class_hierarchy("B1", edge_scope="bogus")
        assert "error" in result
        assert "edge_scope" in result["error"]

    def test_path_graph_is_sound_down(self, analyzer):
        """Every listed edge endpoint must be a node (path reconstruction)."""
        result = analyzer.get_class_hierarchy("B1", direction="down", max_depth=1)
        classes = result["classes"]
        for key, node in classes.items():
            for edge in node["base_classes"] + node["derived_classes"]:
                assert edge in classes, f"dangling edge {edge} on node {key}"
        # every non-start node keeps its parent link into the graph
        for key, node in classes.items():
            if key != result["queried_class"]:
                assert node["base_classes"], f"{key} lost its parent link"

    def test_path_graph_is_sound_up(self, analyzer):
        result = analyzer.get_class_hierarchy("D", direction="up")
        classes = result["classes"]
        for key, node in classes.items():
            for edge in node["base_classes"] + node["derived_classes"]:
                assert edge in classes, f"dangling edge {edge} on node {key}"
