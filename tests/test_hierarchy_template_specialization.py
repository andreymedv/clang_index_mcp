"""
Regression tests for cplusplus_mcp-jqqq: get_class_hierarchy must not collapse
template specializations.

Before the fix, T<A1> and T<A2> merged into a single 'T' node (specialization
symbols are stored with template arguments stripped from their names), so
down('A1') wrongly listed D2 as a descendant and edges lacked the template
arguments ('T' instead of 'T<A1>').

Design under test: specializations are first-class inheritance-graph nodes
keyed with their template arguments (T<A1>, T<A2>). The class template is an
aggregation hub linked via instantiates / specialization_of, which does NOT
participate in inheritance reachability. Specialization nodes are synthesized
from base_classes strings when no specialization symbol is indexed.

Both fixture variants are exercised:
  tests/fixtures/hierarchy_template_spec/with_instantiation
  tests/fixtures/hierarchy_template_spec/without_instantiation
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
from tests.utils.test_helpers import temp_compile_commands

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "hierarchy_template_spec"


def _index_variant(tmp_path_factory, variant: str):
    """Copy one fixture variant to a temp dir and index it."""
    tmp_path = tmp_path_factory.mktemp(f"hier_spec_{variant}")
    shutil.copytree(FIXTURE_DIR / variant, tmp_path, dirs_exist_ok=True)

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

    analyzer = CppAnalyzer(str(tmp_path))
    analyzer.index_project()
    return analyzer


def _close_analyzer(analyzer):
    if hasattr(analyzer, "cache_manager"):
        cache_dir = analyzer.cache_manager.cache_dir
        analyzer.cache_manager.close()
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def analyzer_with_specs(tmp_path_factory):
    """Fixture variant WITH `template class T<A1>;` explicit instantiations."""
    analyzer = _index_variant(tmp_path_factory, "with_instantiation")
    yield analyzer
    _close_analyzer(analyzer)


@pytest.fixture(scope="module")
def analyzer_without_specs(tmp_path_factory):
    """Fixture variant WITHOUT explicit instantiations (synthesized spec nodes)."""
    analyzer = _index_variant(tmp_path_factory, "without_instantiation")
    yield analyzer
    _close_analyzer(analyzer)


@pytest.fixture(params=["with_instantiation", "without_instantiation"])
def analyzer(request, analyzer_with_specs, analyzer_without_specs):
    """Run every test against both fixture variants."""
    if request.param == "with_instantiation":
        return analyzer_with_specs
    return analyzer_without_specs


def get_keys(result):
    return set(result.get("classes", {}))


def get_node(result, key):
    node = result["classes"].get(key)
    assert node is not None, f"node '{key}' missing from {sorted(result.get('classes', {}))}"
    return node


class TestSpecializationNodesAreDistinct:
    """T<A1> and T<A2> must be separate nodes; branches never mix."""

    def test_down_a1_contains_only_its_branch(self, analyzer):
        result = analyzer.get_class_hierarchy("A1", direction="down")
        assert "error" not in result
        assert get_keys(result) == {"A1", "T<A1>", "D1"}

    def test_down_a1_excludes_sibling_branch_from_payload(self, analyzer):
        result = analyzer.get_class_hierarchy("A1", direction="down")
        payload = json.dumps(result)
        assert "D2" not in payload
        assert "T<A2>" not in payload
        assert '"T":' not in payload  # bare template must not appear as a node key

    def test_a1_derived_is_the_specialization(self, analyzer):
        result = analyzer.get_class_hierarchy("A1", direction="down")
        node_a1 = get_node(result, "A1")
        assert node_a1["derived_classes"] == ["T<A1>"]

    def test_spec_node_fields(self, analyzer):
        result = analyzer.get_class_hierarchy("A1", direction="down")
        node = get_node(result, "T<A1>")
        assert node["base_classes"] == ["A1"]
        assert node["derived_classes"] == ["D1"]
        assert node["specialization_of"] == "T"
        assert node["template_arguments"] == ["A1"]
        assert node["kind"] == "full_specialization"

    def test_edges_keep_template_arguments(self, analyzer):
        result = analyzer.get_class_hierarchy("A1", direction="down")
        node_d1 = get_node(result, "D1")
        assert node_d1["base_classes"] == ["T<A1>"]


class TestUpwardTraversalIsAsymmetric:
    """up('D1') must reach A1 through T<A1> (previously stopped at T/P)."""

    def test_up_d1_reaches_a1_via_specialization(self, analyzer):
        result = analyzer.get_class_hierarchy("D1", direction="up")
        assert "error" not in result
        assert get_keys(result) == {"D1", "T<A1>", "A1"}
        assert get_node(result, "D1")["base_classes"] == ["T<A1>"]
        node_spec = get_node(result, "T<A1>")
        assert node_spec["base_classes"] == ["A1"]
        assert node_spec["specialization_of"] == "T"
        assert get_node(result, "A1")["qualified_name"] == "A1"

    def test_up_d2_reaches_a2_not_a1(self, analyzer):
        result = analyzer.get_class_hierarchy("D2", direction="up")
        assert get_keys(result) == {"D2", "T<A2>", "A2"}
        assert get_node(result, "T<A2>")["base_classes"] == ["A2"]
        assert "A1" not in json.dumps(result)


class TestTemplateHubAggregation:
    """Querying the class template aggregates its instantiations via a
    non-inheritance edge; descendants are reached through the spec chains."""

    def test_down_T_includes_both_instantiation_chains(self, analyzer):
        result = analyzer.get_class_hierarchy("T", direction="down")
        assert "error" not in result
        assert get_keys(result) == {"T", "T<A1>", "T<A2>", "D1", "D2"}

    def test_hub_instantiates_list(self, analyzer):
        result = analyzer.get_class_hierarchy("T", direction="down")
        node_t = get_node(result, "T")
        assert node_t["instantiates"] == ["T<A1>", "T<A2>"]
        assert node_t["kind"] == "class_template"

    def test_descendants_reachable_through_spec_chains(self, analyzer):
        result = analyzer.get_class_hierarchy("T", direction="down")
        assert get_node(result, "T<A1>")["derived_classes"] == ["D1"]
        assert get_node(result, "T<A2>")["derived_classes"] == ["D2"]
        assert get_node(result, "D1")["base_classes"] == ["T<A1>"]
        assert get_node(result, "D2")["base_classes"] == ["T<A2>"]

    def test_aggregation_edge_not_traversed_upward(self, analyzer):
        """up('D1') reaches A1 but never hops through the hub to T<A2>/D2."""
        result = analyzer.get_class_hierarchy("D1", direction="up")
        assert get_keys(result) == {"D1", "T<A1>", "A1"}
        assert "T<A2>" not in json.dumps(result)
        assert "instantiates" not in json.dumps(result)


class TestDirectSpecializationQuery:
    """A specialization key is a valid query entry point."""

    def test_query_T_A1_both(self, analyzer):
        result = analyzer.get_class_hierarchy("T<A1>", direction="both")
        assert "error" not in result
        assert get_keys(result) == {"T<A1>", "A1", "D1"}

    def test_unknown_arg_specialization_synthesizes(self, analyzer):
        result = analyzer.get_class_hierarchy("T<Missing>", direction="both")
        assert "error" not in result  # synthesized as long as primary T exists
        assert "T<Missing>" in get_keys(result)


class TestNamespacedSpecializationKeys:
    """Template-name portion and arguments are resolved to qualified names."""

    def test_down_namespaced(self, analyzer):
        result = analyzer.get_class_hierarchy("ns::NA", direction="down")
        assert "error" not in result
        assert get_keys(result) == {"ns::NA", "ns::NT<ns::NA>", "ns::ND"}
        assert get_node(result, "ns::NA")["derived_classes"] == ["ns::NT<ns::NA>"]
        assert get_node(result, "ns::ND")["base_classes"] == ["ns::NT<ns::NA>"]
        assert get_node(result, "ns::NT<ns::NA>")["specialization_of"] == "ns::NT"


class TestVariantAgreement:
    """Indexed specializations and synthesized ones must produce the same graph."""

    def test_down_a1_identical(self, analyzer_with_specs, analyzer_without_specs):
        with_specs = analyzer_with_specs.get_class_hierarchy("A1", direction="down")
        without = analyzer_without_specs.get_class_hierarchy("A1", direction="down")
        assert get_keys(with_specs) == get_keys(without)
        for key in get_keys(with_specs):
            assert with_specs["classes"][key]["base_classes"] == without["classes"][key][
                "base_classes"
            ]
            assert with_specs["classes"][key]["derived_classes"] == without["classes"][key][
                "derived_classes"
            ]

    def test_up_d1_identical(self, analyzer_with_specs, analyzer_without_specs):
        with_specs = analyzer_with_specs.get_class_hierarchy("D1", direction="up")
        without = analyzer_without_specs.get_class_hierarchy("D1", direction="up")
        assert get_keys(with_specs) == get_keys(without)
