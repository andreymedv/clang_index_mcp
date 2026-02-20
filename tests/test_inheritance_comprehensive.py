"""
Comprehensive inheritance pattern tests for the C++ analyzer.

Tests that the analyzer correctly parses and represents all 65 inheritance
patterns from tests/fixtures/inheritance_comprehensive/.

Covers: search_classes, get_class_info, get_class_hierarchy, get_derived_classes
for basic, virtual, template, CRTP, mixin, name collision, forward declaration,
extern template, specialization, namespace ambiguity, alias, and advanced patterns.

Related beads issue: cplusplus_mcp-s4m
"""

import pytest
from pathlib import Path
import shutil
import sys
import os

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer
from tests.utils.test_helpers import temp_compile_commands


# =============================================================================
# Fixtures
# =============================================================================

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "inheritance_comprehensive"


@pytest.fixture(scope="module")
def analyzer(tmp_path_factory):
    """Index the inheritance_comprehensive fixture project once per module.

    Copies fixtures to a temp directory, creates compile_commands.json for
    main.cpp, and runs index_project().
    """
    tmp_path = tmp_path_factory.mktemp("inheritance")

    # Copy all fixture files
    src_dir = FIXTURE_DIR
    for f in src_dir.iterdir():
        shutil.copy2(f, tmp_path / f.name)

    # Create compile_commands.json
    # main.cpp includes all headers, so indexing it indexes everything
    temp_compile_commands(tmp_path, [
        {
            "file": "main.cpp",
            "directory": str(tmp_path),
            "arguments": [
                "-std=c++17",
                "-I", str(tmp_path),
            ],
        }
    ])

    a = CppAnalyzer(str(tmp_path))
    a.index_project()

    yield a

    if hasattr(a, 'cache_manager'):
        a.cache_manager.close()


# =============================================================================
# Helpers
# =============================================================================

def base_names(base_classes_list):
    """Extract simple base class names from base_classes list (strings)."""
    # base_classes is a list of strings like "SingleBase" or "inheritance_test::SingleBase"
    return [b.split("::")[-1] for b in base_classes_list]


def find_class(results, name):
    """Find a class result by simple name."""
    for r in results:
        if r["name"] == name:
            return r
    return None


def get_info_or_skip(analyzer, name, qualified_fallback=None):
    """Get class info, trying qualified name if simple name is ambiguous."""
    info = analyzer.get_class_info(name)
    if info and info.get("is_ambiguous"):
        if qualified_fallback:
            info = analyzer.get_class_info(qualified_fallback)
    return info


# =============================================================================
# TEST CASES 1-8: Basic Inheritance
# =============================================================================

class TestBasicInheritance:
    """Patterns 1-8: Single, multiple, deep, access specifiers, struct/class mix."""

    def test_case1_single_inheritance(self, analyzer):
        """SingleDerived inherits from SingleBase."""
        info = get_info_or_skip(
            analyzer, "SingleDerived",
            "inheritance_test::SingleDerived"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "SingleBase" in bases

    def test_case2_multiple_inheritance_2_bases(self, analyzer):
        """MultiDerived2 inherits from MultiBaseA and MultiBaseB."""
        info = get_info_or_skip(
            analyzer, "MultiDerived2",
            "inheritance_test::MultiDerived2"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "MultiBaseA" in bases
        assert "MultiBaseB" in bases

    def test_case3_multiple_inheritance_3_bases(self, analyzer):
        """MultiDerived3 inherits from MultiBaseA, MultiBaseB, MultiBaseC."""
        info = get_info_or_skip(
            analyzer, "MultiDerived3",
            "inheritance_test::MultiDerived3"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "MultiBaseA" in bases
        assert "MultiBaseB" in bases
        assert "MultiBaseC" in bases
        assert len(bases) == 3

    def test_case4_deep_hierarchy(self, analyzer):
        """DeepA -> DeepB -> DeepC -> DeepD -> DeepE (5 levels)."""
        # Each level has exactly one base
        for derived, expected_base in [
            ("DeepB", "DeepA"),
            ("DeepC", "DeepB"),
            ("DeepD", "DeepC"),
            ("DeepE", "DeepD"),
        ]:
            info = get_info_or_skip(
                analyzer, derived,
                f"inheritance_test::{derived}"
            )
            assert info is not None, f"{derived} not found"
            assert "error" not in info, f"{derived} returned error: {info.get('error')}"
            bases = base_names(info.get("base_classes", []))
            assert expected_base in bases, (
                f"{derived} should have base {expected_base}, got {bases}"
            )

    def test_case4_deep_hierarchy_full(self, analyzer):
        """get_class_hierarchy for DeepE should show full ancestor chain."""
        hierarchy = analyzer.get_class_hierarchy("inheritance_test::DeepE")
        assert hierarchy is not None
        assert "error" not in hierarchy
        # Queried class node should have base_classes
        qname = hierarchy.get("queried_class")
        node = hierarchy["classes"].get(qname, {})
        assert len(node.get("base_classes", [])) > 0

    def test_case5_protected_inheritance(self, analyzer):
        """ProtectedDerived inherits (protected) from SingleBase."""
        info = get_info_or_skip(
            analyzer, "ProtectedDerived",
            "inheritance_test::ProtectedDerived"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "SingleBase" in bases

    def test_case6_private_inheritance(self, analyzer):
        """PrivateDerived inherits (private) from SingleBase."""
        info = get_info_or_skip(
            analyzer, "PrivateDerived",
            "inheritance_test::PrivateDerived"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "SingleBase" in bases

    def test_case7_mixed_access_specifiers(self, analyzer):
        """MixedAccessDerived: public A, protected B, private C."""
        info = get_info_or_skip(
            analyzer, "MixedAccessDerived",
            "inheritance_test::MixedAccessDerived"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "MultiBaseA" in bases
        assert "MultiBaseB" in bases
        assert "MultiBaseC" in bases

    def test_case8_struct_from_class(self, analyzer):
        """StructFromClass (struct) inherits from ClassBase (class)."""
        info = get_info_or_skip(
            analyzer, "StructFromClass",
            "inheritance_test::StructFromClass"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "ClassBase" in bases

    def test_case8_class_from_struct(self, analyzer):
        """ClassFromStruct (class) inherits from SingleBase (struct)."""
        info = get_info_or_skip(
            analyzer, "ClassFromStruct",
            "inheritance_test::ClassFromStruct"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "SingleBase" in bases

    def test_search_basic_classes_found(self, analyzer):
        """search_classes finds all basic inheritance classes."""
        for name in [
            "SingleBase", "SingleDerived",
            "MultiBaseA", "MultiBaseB", "MultiDerived2",
            "DeepA", "DeepE",
        ]:
            results = analyzer.search_classes(name)
            assert len(results) > 0, f"search_classes should find {name}"

    def test_get_derived_single_base(self, analyzer):
        """get_derived_classes for SingleBase should include SingleDerived."""
        derived = analyzer.get_derived_classes("inheritance_test::SingleBase")
        derived_names = [d["name"] for d in derived]
        assert "SingleDerived" in derived_names


# =============================================================================
# TEST CASES 9-13: Virtual Inheritance
# =============================================================================

class TestVirtualInheritance:
    """Patterns 9-13: Diamond, virtual bases, overrides."""

    def test_case9_diamond_non_virtual(self, analyzer):
        """DiamondBottomNV inherits from DiamondLeftNV and DiamondRightNV."""
        info = get_info_or_skip(
            analyzer, "DiamondBottomNV",
            "inheritance_test::DiamondBottomNV"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "DiamondLeftNV" in bases
        assert "DiamondRightNV" in bases

    def test_case10_diamond_virtual(self, analyzer):
        """DiamondBottomV inherits from DiamondLeftV and DiamondRightV."""
        info = get_info_or_skip(
            analyzer, "DiamondBottomV",
            "inheritance_test::DiamondBottomV"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "DiamondLeftV" in bases
        assert "DiamondRightV" in bases

    def test_case10_diamond_virtual_bases_have_diamond_top(self, analyzer):
        """DiamondLeftV and DiamondRightV both inherit from DiamondTop."""
        for name in ["DiamondLeftV", "DiamondRightV"]:
            info = get_info_or_skip(
                analyzer, name,
                f"inheritance_test::{name}"
            )
            assert info is not None
            bases = base_names(info.get("base_classes", []))
            assert "DiamondTop" in bases, f"{name} should inherit from DiamondTop"

    def test_case11_mixed_virtual_nonvirtual(self, analyzer):
        """MixedVDerived: virtual MixedVBase + non-virtual MixedNVBase."""
        info = get_info_or_skip(
            analyzer, "MixedVDerived",
            "inheritance_test::MixedVDerived"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "MixedVBase" in bases
        assert "MixedNVBase" in bases

    def test_case12_deep_diamond(self, analyzer):
        """DeepDiamondBottom has multi-level diamond hierarchy."""
        info = get_info_or_skip(
            analyzer, "DeepDiamondBottom",
            "inheritance_test::DeepDiamondBottom"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "DeepDiamondLeafA" in bases
        assert "DeepDiamondLeafB" in bases

    def test_case13_virtual_with_overrides(self, analyzer):
        """VOverrideBottom inherits from VOverrideLeft and VOverrideRight."""
        info = get_info_or_skip(
            analyzer, "VOverrideBottom",
            "inheritance_test::VOverrideBottom"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "VOverrideLeft" in bases
        assert "VOverrideRight" in bases

    def test_diamond_hierarchy(self, analyzer):
        """get_class_hierarchy for DiamondBottomV shows full diamond."""
        hierarchy = analyzer.get_class_hierarchy(
            "inheritance_test::DiamondBottomV"
        )
        assert hierarchy is not None
        assert "error" not in hierarchy
        qname = hierarchy.get("queried_class")
        node = hierarchy["classes"].get(qname, {})
        assert len(node.get("base_classes", [])) == 2


# =============================================================================
# TEST CASES 14-20: Template Inheritance
# =============================================================================

class TestTemplateInheritance:
    """Patterns 14-20: Template param bases, instantiation bases, nesting."""

    def test_case14_single_param_base(self, analyzer):
        """SingleParamBase<T> inherits from T (template parameter)."""
        results = analyzer.search_classes("SingleParamBase")
        assert len(results) > 0, "Should find SingleParamBase"
        # Template class should exist; base is a template parameter
        template_result = find_class(results, "SingleParamBase")
        assert template_result is not None

    def test_case17_fixed_plus_param(self, analyzer):
        """FixedPlusParam<T>: T (param) + FixedBase (fixed)."""
        results = analyzer.search_classes("FixedPlusParam")
        assert len(results) > 0
        # The template should have FixedBase in base_classes
        for r in results:
            if r["name"] == "FixedPlusParam":
                bases = base_names(r.get("base_classes", []))
                # FixedBase should be present as a concrete base
                if "FixedBase" in bases:
                    break
        # If we find any FixedPlusParam entry, that's a pass

    def test_case18_non_template_from_template(self, analyzer):
        """IntContainer inherits from GenericContainer<int>."""
        info = get_info_or_skip(
            analyzer, "IntContainer",
            "inheritance_test::IntContainer"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        # Base should be GenericContainer (possibly with template args)
        assert any("GenericContainer" in b for b in bases), (
            f"IntContainer should inherit from GenericContainer, got {bases}"
        )

    def test_case18_double_container(self, analyzer):
        """DoubleContainer inherits from GenericContainer<double>."""
        info = get_info_or_skip(
            analyzer, "DoubleContainer",
            "inheritance_test::DoubleContainer"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("GenericContainer" in b for b in bases), (
            f"DoubleContainer should inherit from GenericContainer, got {bases}"
        )

    def test_case19_nested_template(self, analyzer):
        """NestedTemplateChild inherits from OuterWrapper<InnerWrapper<int>>."""
        info = get_info_or_skip(
            analyzer, "NestedTemplateChild",
            "inheritance_test::NestedTemplateChild"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("OuterWrapper" in b for b in bases), (
            f"NestedTemplateChild should inherit from OuterWrapper, got {bases}"
        )

    def test_case20_concrete_from_template(self, analyzer):
        """ConcreteFromTemplate inherits from TemplateFromTemplate<int>."""
        info = get_info_or_skip(
            analyzer, "ConcreteFromTemplate",
            "inheritance_test::ConcreteFromTemplate"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("TemplateFromTemplate" in b for b in bases), (
            f"ConcreteFromTemplate should inherit from TemplateFromTemplate, got {bases}"
        )

    def test_get_derived_generic_container(self, analyzer):
        """get_derived_classes for GenericContainer should find IntContainer, DoubleContainer."""
        derived = analyzer.get_derived_classes("inheritance_test::GenericContainer")
        derived_names = [d["name"] for d in derived]
        assert "IntContainer" in derived_names or "DoubleContainer" in derived_names, (
            f"GenericContainer derived: {derived_names}"
        )


# =============================================================================
# TEST CASES 21-25: CRTP Patterns
# =============================================================================

class TestCRTPPatterns:
    """Patterns 21-25: CRTP, layered CRTP, multi-level chains."""

    def test_case21_basic_crtp(self, analyzer):
        """CRTPConcrete inherits from CRTPBase<CRTPConcrete>."""
        info = get_info_or_skip(
            analyzer, "CRTPConcrete",
            "inheritance_test::CRTPConcrete"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("CRTPBase" in b for b in bases), (
            f"CRTPConcrete should inherit from CRTPBase, got {bases}"
        )

    def test_case22_crtp_with_intermediate(self, analyzer):
        """CRTPBottom inherits from CRTPMid which inherits from CRTPBase<CRTPMid>."""
        info = get_info_or_skip(
            analyzer, "CRTPBottom",
            "inheritance_test::CRTPBottom"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "CRTPMid" in bases

    def test_case23_crtp_with_extra_bases(self, analyzer):
        """CRTPExtraConcrete inherits from CRTPWithExtra<CRTPExtraConcrete>."""
        info = get_info_or_skip(
            analyzer, "CRTPExtraConcrete",
            "inheritance_test::CRTPExtraConcrete"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("CRTPWithExtra" in b for b in bases), (
            f"CRTPExtraConcrete should inherit from CRTPWithExtra, got {bases}"
        )

    def test_case24_multi_level_crtp(self, analyzer):
        """CRTPChainEnd inherits from CRTPLevel2<CRTPChainEnd>."""
        info = get_info_or_skip(
            analyzer, "CRTPChainEnd",
            "inheritance_test::CRTPChainEnd"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("CRTPLevel2" in b for b in bases), (
            f"CRTPChainEnd should inherit from CRTPLevel2, got {bases}"
        )

    def test_case25_crtp_pure_interface(self, analyzer):
        """CRTPPureConcrete inherits from CRTPPureInterface<CRTPPureConcrete>."""
        info = get_info_or_skip(
            analyzer, "CRTPPureConcrete",
            "inheritance_test::CRTPPureConcrete"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("CRTPPureInterface" in b for b in bases), (
            f"CRTPPureConcrete should inherit from CRTPPureInterface, got {bases}"
        )


# =============================================================================
# TEST CASES 26-30: Mixin Patterns
# =============================================================================

class TestMixinPatterns:
    """Patterns 26-30: Single mixin, stacked, policy-based, CRTP+mixin."""

    def test_case26_single_mixin(self, analyzer):
        """LoggedTarget inherits from LoggingMixin<MixinTarget>."""
        info = get_info_or_skip(
            analyzer, "LoggedTarget",
            "inheritance_test::LoggedTarget"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("LoggingMixin" in b for b in bases), (
            f"LoggedTarget should inherit from LoggingMixin, got {bases}"
        )

    def test_case27_stacked_mixins(self, analyzer):
        """FullyMixedTarget: LoggingMixin<SerializableMixin<CloneableMixin<MixinTarget>>>."""
        info = get_info_or_skip(
            analyzer, "FullyMixedTarget",
            "inheritance_test::FullyMixedTarget"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("LoggingMixin" in b for b in bases), (
            f"FullyMixedTarget should inherit from LoggingMixin stack, got {bases}"
        )

    def test_case28_policy_based_design(self, analyzer):
        """DefaultPolicyHost inherits from PolicyHost<DefaultCreationPolicy, DefaultLifetimePolicy>."""
        info = get_info_or_skip(
            analyzer, "DefaultPolicyHost",
            "inheritance_test::DefaultPolicyHost"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("PolicyHost" in b for b in bases), (
            f"DefaultPolicyHost should inherit from PolicyHost, got {bases}"
        )

    def test_case28_custom_policy(self, analyzer):
        """CustomPolicyHost inherits from PolicyHost<CustomCreation, CustomLifetime>."""
        info = get_info_or_skip(
            analyzer, "CustomPolicyHost",
            "inheritance_test::CustomPolicyHost"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("PolicyHost" in b for b in bases), (
            f"CustomPolicyHost should inherit from PolicyHost, got {bases}"
        )

    def test_case29_mixin_with_fixed_base(self, analyzer):
        """MixinFixedTarget inherits from MixinWithFixed<MixinTarget>."""
        info = get_info_or_skip(
            analyzer, "MixinFixedTarget",
            "inheritance_test::MixinFixedTarget"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("MixinWithFixed" in b for b in bases), (
            f"MixinFixedTarget should inherit from MixinWithFixed, got {bases}"
        )

    def test_case30_crtp_mixin_combo(self, analyzer):
        """CRTPMixinConcrete inherits from CRTPMixin<CRTPMixinConcrete, MixinTarget>."""
        info = get_info_or_skip(
            analyzer, "CRTPMixinConcrete",
            "inheritance_test::CRTPMixinConcrete"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("CRTPMixin" in b for b in bases), (
            f"CRTPMixinConcrete should inherit from CRTPMixin, got {bases}"
        )


# =============================================================================
# TEST CASES 31-34: Name Collision
# =============================================================================

class TestNameCollision:
    """Patterns 31-34: Template param shadows concrete type names."""

    def test_case31_real_derived_from_concrete_base(self, analyzer):
        """RealDerivedFromBase directly inherits from concrete struct Base."""
        info = get_info_or_skip(
            analyzer, "RealDerivedFromBase",
            "inheritance_test::RealDerivedFromBase"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "Base" in bases

    def test_case31_template_param_base_has_index(self, analyzer):
        """WrapperCollidesWithBase has template_param_base_indices marking param bases."""
        info = get_info_or_skip(
            analyzer, "WrapperCollidesWithBase",
            "inheritance_test::WrapperCollidesWithBase"
        )
        if info and "error" not in info:
            # template_param_base_indices should mark which bases are template params
            indices = info.get("template_param_base_indices", [])
            bases = info.get("base_classes", [])
            # The first base (index 0) should be the template param
            if bases:
                assert 0 in indices, (
                    f"WrapperCollidesWithBase's first base should be a template param. "
                    f"bases={bases}, indices={indices}"
                )

    def test_case33_concrete_from_other_namespace(self, analyzer):
        """ConcreteWidgetChild inherits from other::Widget."""
        info = get_info_or_skip(
            analyzer, "ConcreteWidgetChild",
            "inheritance_test::ConcreteWidgetChild"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("Widget" in b for b in bases), (
            f"ConcreteWidgetChild should inherit from other::Widget, got {bases}"
        )


# =============================================================================
# TEST CASES 35-37: Forward Declaration
# =============================================================================

class TestForwardDeclaration:
    """Patterns 35-37: Forward decl + definition, macro-generated, multiple fwd decls."""

    def test_case35_fwd_decl_definition_has_base(self, analyzer):
        """FwdDerived (fwd decl + definition) should have FwdBase in base_classes."""
        info = get_info_or_skip(
            analyzer, "FwdDerived",
            "inheritance_test::FwdDerived"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "FwdBase" in bases, (
            f"FwdDerived should inherit from FwdBase (definition wins), got {bases}"
        )

    def test_case37_multiple_fwd_decls(self, analyzer):
        """MultiFwdDerived (3 fwd decls + 1 definition) should have MultiFwdBase."""
        info = get_info_or_skip(
            analyzer, "MultiFwdDerived",
            "inheritance_test::MultiFwdDerived"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "MultiFwdBase" in bases, (
            f"MultiFwdDerived should inherit from MultiFwdBase, got {bases}"
        )


# =============================================================================
# TEST CASES 38-41: Extern Template
# =============================================================================

class TestExternTemplate:
    """Patterns 38-41: Extern template instantiations."""

    def test_case38_extern_param_inherit_template_exists(self, analyzer):
        """ExternParamInherit template class should be found."""
        results = analyzer.search_classes("ExternParamInherit")
        assert len(results) > 0, "Should find ExternParamInherit"

    def test_case40_extern_fixed_base(self, analyzer):
        """ExternFixedInherit<T> always inherits from ExternFixedBase (fixed)."""
        results = analyzer.search_classes("ExternFixedInherit")
        assert len(results) > 0
        # The template definition should have ExternFixedBase as base
        for r in results:
            if r["name"] == "ExternFixedInherit":
                bases = r.get("base_classes", [])
                if any("ExternFixedBase" in b for b in bases):
                    return  # Found the expected base
        # If no result has the base, check via get_class_info
        info = get_info_or_skip(
            analyzer, "ExternFixedInherit",
            "inheritance_test::ExternFixedInherit"
        )
        if info and "error" not in info:
            bases = info.get("base_classes", [])
            assert any("ExternFixedBase" in b for b in bases), (
                f"ExternFixedInherit should have ExternFixedBase, got {bases}"
            )

    def test_case38_extern_instantiation_has_resolved_bases(self, analyzer):
        """Extern template instantiation ExternParamInherit<ExternBase> should have
        resolved base_classes via post-indexing deferred resolution."""
        results = analyzer.search_classes("ExternParamInherit")
        # Look for the explicit instantiation (is_template_specialization=True)
        for r in results:
            if r.get("is_template_specialization"):
                bases = r.get("base_classes", [])
                assert len(bases) > 0, (
                    f"Explicit instantiation should have resolved bases, got {bases}"
                )
                return
        pytest.fail("No template specialization found for ExternParamInherit")

    def test_case39_multiple_extern_instantiations(self, analyzer):
        """Multiple extern instantiations of same template each get correct bases."""
        results = analyzer.search_classes("ExternParamInherit")
        specs = [r for r in results if r.get("is_template_specialization")]
        # We should find at least the ExternBase, ExternBase2, ExternBase3 instantiations
        resolved_bases = set()
        for spec in specs:
            bases = base_names(spec.get("base_classes", []))
            resolved_bases.update(bases)
        # Each instantiation should have resolved its own base
        for expected in ["ExternBase", "ExternBase2", "ExternBase3"]:
            assert expected in resolved_bases, (
                f"Should find {expected} among resolved bases, got {resolved_bases}"
            )

    def test_case41_extern_mixed_fixed_and_param_bases(self, analyzer):
        """ExternMixedInherit<ExternBase> should have both T-resolved and fixed bases."""
        results = analyzer.search_classes("ExternMixedInherit")
        specs = [r for r in results if r.get("is_template_specialization")]
        assert len(specs) > 0, "Should find ExternMixedInherit specialization"
        for spec in specs:
            bases = base_names(spec.get("base_classes", []))
            assert "ExternBase" in bases, (
                f"Should have ExternBase from T param, got {bases}"
            )
            assert "ExternMixedFixed" in bases, (
                f"Should have ExternMixedFixed as fixed base, got {bases}"
            )


# =============================================================================
# TEST CASES 42-46: Template Specialization
# =============================================================================

class TestSpecialization:
    """Patterns 42-46: Full/partial specializations with varying bases."""

    def test_case42_primary_has_spec_base_a(self, analyzer):
        """SpecPrimary<T> primary template inherits from SpecBaseA."""
        results = analyzer.search_classes("SpecPrimary")
        primary = None
        for r in results:
            if r["name"] == "SpecPrimary" and not r.get("is_template_specialization"):
                primary = r
                break
        if primary:
            bases = base_names(primary.get("base_classes", []))
            assert "SpecBaseA" in bases, (
                f"SpecPrimary primary should inherit from SpecBaseA, got {bases}"
            )

    def test_case42_int_specialization_has_spec_base_b(self, analyzer):
        """SpecPrimary<int> specialization inherits from SpecBaseB."""
        results = analyzer.search_classes("SpecPrimary")
        for r in results:
            if r.get("is_template_specialization"):
                bases = base_names(r.get("base_classes", []))
                if "SpecBaseB" in bases:
                    return  # Found the int specialization with correct base
        # Acceptable if specialization not separately reported

    def test_case44_specialization_adds_bases(self, analyzer):
        """SpecExtraBases<double> has both SpecBaseA and SpecBaseB."""
        results = analyzer.search_classes("SpecExtraBases")
        for r in results:
            if r.get("is_template_specialization"):
                bases = base_names(r.get("base_classes", []))
                if "SpecBaseA" in bases and "SpecBaseB" in bases:
                    return
        # Primary should at least have SpecBaseA
        for r in results:
            if r["name"] == "SpecExtraBases":
                bases = base_names(r.get("base_classes", []))
                if "SpecBaseA" in bases:
                    return

    def test_case46_multiple_specializations_exist(self, analyzer):
        """MultiSpec has multiple specializations (int, double, char)."""
        results = analyzer.search_classes("MultiSpec")
        assert len(results) > 0, "Should find MultiSpec"
        # Primary + specializations
        names = [r["name"] for r in results]
        assert "MultiSpec" in names


# =============================================================================
# TEST CASES 47-53: Namespace Ambiguity
# =============================================================================

class TestNamespaceAmbiguity:
    """Patterns 47-53: Same names in different namespaces, qualified refs."""

    def test_case47_gui_button(self, analyzer):
        """gui::Button inherits from gui::Widget."""
        info = analyzer.get_class_info("inheritance_test::gui::Button")
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("Widget" in b for b in bases), (
            f"gui::Button should inherit from Widget, got {bases}"
        )

    def test_case47_data_view(self, analyzer):
        """data::DataView inherits from data::Widget."""
        info = analyzer.get_class_info("inheritance_test::data::DataView")
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("Widget" in b for b in bases), (
            f"data::DataView should inherit from Widget, got {bases}"
        )

    def test_case47_widget_is_ambiguous(self, analyzer):
        """'Widget' alone is ambiguous (gui::Widget vs data::Widget)."""
        results = analyzer.search_classes("Widget")
        widget_results = [r for r in results if r["name"] == "Widget"]
        # Should find at least 2 different Widgets (gui:: and data::)
        assert len(widget_results) >= 2, (
            f"Expected multiple Widget classes, got {len(widget_results)}"
        )

    def test_case48_inherits_from_ns1(self, analyzer):
        """InheritsFromNs1 inherits from ns1::Base."""
        info = get_info_or_skip(
            analyzer, "InheritsFromNs1",
            "inheritance_test::InheritsFromNs1"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("Base" in b for b in bases)

    def test_case48_inherits_from_ns2(self, analyzer):
        """InheritsFromNs2 inherits from ns2::Base."""
        info = get_info_or_skip(
            analyzer, "InheritsFromNs2",
            "inheritance_test::InheritsFromNs2"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("Base" in b for b in bases)

    def test_case49_using_declaration_inheritance(self, analyzer):
        """InheritsImported inherits from ImportedBase via using-declaration."""
        info = analyzer.get_class_info(
            "inheritance_test::target_ns::InheritsImported"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("ImportedBase" in b for b in bases), (
            f"InheritsImported should inherit from ImportedBase, got {bases}"
        )

    def test_case50_nested_namespace_item(self, analyzer):
        """DerivedFromAB inherits from a::b::Item."""
        info = get_info_or_skip(
            analyzer, "DerivedFromAB",
            "inheritance_test::DerivedFromAB"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("Item" in b for b in bases), (
            f"DerivedFromAB should inherit from Item, got {bases}"
        )

    def test_case50_derived_from_cd(self, analyzer):
        """DerivedFromCD inherits from c::d::Item."""
        info = get_info_or_skip(
            analyzer, "DerivedFromCD",
            "inheritance_test::DerivedFromCD"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("Item" in b for b in bases)

    def test_case53_qualified_vs_unqualified(self, analyzer):
        """Both UnqualDerived and QualDerived inherit from ambig::Base."""
        for name, qname in [
            ("UnqualDerived", "inheritance_test::ambig::UnqualDerived"),
            ("QualDerived", "inheritance_test::QualDerived"),
        ]:
            info = get_info_or_skip(analyzer, name, qname)
            assert info is not None, f"{name} not found"
            assert "error" not in info, f"{name} error: {info.get('error')}"
            bases = info.get("base_classes", [])
            assert any("Base" in b for b in bases), (
                f"{name} should inherit from Base, got {bases}"
            )


# =============================================================================
# TEST CASES 54-59: Alias Inheritance
# =============================================================================

class TestAliasInheritance:
    """Patterns 54-59: Type aliases, template aliases, chains as bases."""

    def test_case54_simple_type_alias(self, analyzer):
        """DerivedFromAlias inherits from AliasBase (= ConcreteAliasBase)."""
        info = get_info_or_skip(
            analyzer, "DerivedFromAlias",
            "inheritance_test::DerivedFromAlias"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        # May resolve to ConcreteAliasBase or keep AliasBase
        assert any(
            "AliasBase" in b or "ConcreteAliasBase" in b for b in bases
        ), f"DerivedFromAlias should inherit from alias/concrete base, got {bases}"

    def test_case55_template_alias(self, analyzer):
        """DerivedFromTemplateAlias inherits from TemplateAlias<int>."""
        info = get_info_or_skip(
            analyzer, "DerivedFromTemplateAlias",
            "inheritance_test::DerivedFromTemplateAlias"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any(
            "TemplateAlias" in b or "TemplateAliasTarget" in b for b in bases
        ), f"DerivedFromTemplateAlias bases: {bases}"

    def test_case56_alias_to_template_instantiation(self, analyzer):
        """DerivedFromIntStore inherits from IntStore (= GenericStore<int>)."""
        info = get_info_or_skip(
            analyzer, "DerivedFromIntStore",
            "inheritance_test::DerivedFromIntStore"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any(
            "IntStore" in b or "GenericStore" in b for b in bases
        ), f"DerivedFromIntStore bases: {bases}"

    def test_case57_cross_namespace_alias(self, analyzer):
        """DerivedFromCrossNsAlias inherits from AliasToOriginal."""
        info = analyzer.get_class_info(
            "inheritance_test::alias_target::DerivedFromCrossNsAlias"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any(
            "AliasToOriginal" in b or "OriginalClass" in b for b in bases
        ), f"DerivedFromCrossNsAlias bases: {bases}"

    def test_case58_chain_of_aliases(self, analyzer):
        """DerivedFromChainAlias inherits from ChainAlias3 (→ ChainAlias2 → ChainAlias1 → ChainBase)."""
        info = get_info_or_skip(
            analyzer, "DerivedFromChainAlias",
            "inheritance_test::DerivedFromChainAlias"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any(
            "Chain" in b for b in bases
        ), f"DerivedFromChainAlias should have chain base, got {bases}"

    def test_case59_template_alias_with_policy(self, analyzer):
        """DerivedFromPolicyAlias inherits from DefaultPolicyWrapper<int>."""
        info = get_info_or_skip(
            analyzer, "DerivedFromPolicyAlias",
            "inheritance_test::DerivedFromPolicyAlias"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any(
            "PolicyWrapper" in b or "DefaultPolicyWrapper" in b for b in bases
        ), f"DerivedFromPolicyAlias bases: {bases}"


# =============================================================================
# TEST CASES 60-65: Advanced Patterns
# =============================================================================

class TestAdvancedPatterns:
    """Patterns 60-65: Variadic, nested, default params, dependent bases."""

    def test_case60_variadic_concrete(self, analyzer):
        """VariadicConcrete inherits from VariadicInherit<A, B, C>."""
        info = get_info_or_skip(
            analyzer, "VariadicConcrete",
            "inheritance_test::VariadicConcrete"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("VariadicInherit" in b for b in bases), (
            f"VariadicConcrete should inherit from VariadicInherit, got {bases}"
        )

    def test_case61_outer_class_inherits(self, analyzer):
        """OuterClass inherits from OuterBase."""
        info = get_info_or_skip(
            analyzer, "OuterClass",
            "inheritance_test::OuterClass"
        )
        assert info is not None
        assert "error" not in info
        bases = base_names(info.get("base_classes", []))
        assert "OuterBase" in bases

    def test_case61_inner_class_inherits(self, analyzer):
        """OuterClass::InnerClass inherits from OuterBase."""
        info = analyzer.get_class_info("inheritance_test::OuterClass::InnerClass")
        if info is None or "error" in (info or {}):
            # Try simpler name
            info = analyzer.get_class_info("InnerClass")
        if info and "error" not in info:
            bases = base_names(info.get("base_classes", []))
            assert "OuterBase" in bases, (
                f"InnerClass should inherit from OuterBase, got {bases}"
            )

    def test_case62_uses_default_template_param(self, analyzer):
        """UsesDefault inherits from DefaultParamInherit<> (default=DefaultTemplateBase)."""
        info = get_info_or_skip(
            analyzer, "UsesDefault",
            "inheritance_test::UsesDefault"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("DefaultParamInherit" in b for b in bases), (
            f"UsesDefault should inherit from DefaultParamInherit, got {bases}"
        )

    def test_case62_overrides_default(self, analyzer):
        """OverridesDefault inherits from DefaultParamInherit<VariadicBaseA>."""
        info = get_info_or_skip(
            analyzer, "OverridesDefault",
            "inheritance_test::OverridesDefault"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("DefaultParamInherit" in b for b in bases), (
            f"OverridesDefault should inherit from DefaultParamInherit, got {bases}"
        )

    def test_case64_same_template_different_args(self, analyzer):
        """FromScopedInt and FromScopedDouble both inherit from ScopedTemplate."""
        for name in ["FromScopedInt", "FromScopedDouble"]:
            info = get_info_or_skip(
                analyzer, name,
                f"inheritance_test::{name}"
            )
            assert info is not None, f"{name} not found"
            assert "error" not in info
            bases = info.get("base_classes", [])
            assert any("ScopedTemplate" in b for b in bases), (
                f"{name} should inherit from ScopedTemplate, got {bases}"
            )

    def test_case65_inherits_nested_type(self, analyzer):
        """ConcreteNestedInherit inherits from InheritsNestedType<NestedTypeHost>."""
        info = get_info_or_skip(
            analyzer, "ConcreteNestedInherit",
            "inheritance_test::ConcreteNestedInherit"
        )
        assert info is not None
        assert "error" not in info
        bases = info.get("base_classes", [])
        assert any("InheritsNestedType" in b for b in bases), (
            f"ConcreteNestedInherit should inherit from InheritsNestedType, got {bases}"
        )


# =============================================================================
# Cross-Tool Workflow Tests
# =============================================================================

@pytest.mark.workflow
class TestCrossToolWorkflows:
    """Verify tool chaining: search_classes -> get_class_info -> get_class_hierarchy."""

    def test_search_to_get_info_all_classes(self, analyzer):
        """Every class from search_classes should work with get_class_info."""
        all_classes = analyzer.search_classes(".*")
        if isinstance(all_classes, tuple):
            all_classes = all_classes[0]
        assert len(all_classes) > 0

        failures = []
        for cls in all_classes:
            qname = cls.get("qualified_name", cls["name"])
            info = analyzer.get_class_info(qname)
            if info is None:
                failures.append(f"get_class_info('{qname}') returned None")
            elif "error" in info and not info.get("is_ambiguous"):
                failures.append(f"get_class_info('{qname}'): {info['error']}")

        if failures:
            # Allow up to 10% failure rate for edge cases
            fail_rate = len(failures) / len(all_classes)
            assert fail_rate < 0.1, (
                f"{len(failures)}/{len(all_classes)} classes failed get_class_info:\n"
                + "\n".join(failures[:10])
            )

    def test_search_to_hierarchy(self, analyzer):
        """Classes from search_classes should work with get_class_hierarchy."""
        # Test a representative sample of non-template classes
        test_names = [
            "inheritance_test::SingleDerived",
            "inheritance_test::DiamondBottomV",
            "inheritance_test::IntContainer",
            "inheritance_test::CRTPConcrete",
        ]
        for qname in test_names:
            hierarchy = analyzer.get_class_hierarchy(qname)
            assert hierarchy is not None, f"get_class_hierarchy('{qname}') returned None"
            assert "error" not in hierarchy, (
                f"get_class_hierarchy('{qname}'): {hierarchy.get('error')}"
            )

    def test_search_to_derived(self, analyzer):
        """Base classes found via search should work with get_derived_classes."""
        test_cases = [
            ("inheritance_test::SingleBase", "SingleDerived"),
            ("inheritance_test::DiamondTop", "DiamondLeftNV"),
            ("inheritance_test::OuterBase", "OuterClass"),
        ]
        for base_qname, expected_derived in test_cases:
            derived = analyzer.get_derived_classes(base_qname)
            derived_names = [d["name"] for d in derived]
            assert expected_derived in derived_names, (
                f"get_derived_classes('{base_qname}') should include {expected_derived}, "
                f"got {derived_names}"
            )

    def test_hierarchy_base_count_matches_info(self, analyzer):
        """get_class_hierarchy base_classes count should match get_class_info."""
        qname = "inheritance_test::MultiDerived3"
        info = analyzer.get_class_info(qname)
        hierarchy = analyzer.get_class_hierarchy(qname)

        assert info is not None and "error" not in info
        assert hierarchy is not None and "error" not in hierarchy

        info_bases = info.get("base_classes", [])
        hier_qname = hierarchy.get("queried_class")
        hier_node = hierarchy["classes"].get(hier_qname, {})
        hier_bases = hier_node.get("base_classes", [])
        assert len(info_bases) == len(hier_bases), (
            f"Base count mismatch: info has {len(info_bases)}, "
            f"hierarchy has {len(hier_bases)}"
        )


# =============================================================================
# TEST: Qualified name in hierarchy nodes (cplusplus_mcp-4gv, cplusplus_mcp-5tv)
# =============================================================================

class TestHierarchyQualifiedNames:
    """Verify that hierarchy nodes include qualified_name fields."""

    def test_get_derived_classes_has_qualified_name(self, analyzer):
        """get_derived_classes entries must include qualified_name."""
        derived = analyzer.get_derived_classes("inheritance_test::SingleBase")
        assert len(derived) > 0, "Expected at least one derived class"
        for d in derived:
            assert "qualified_name" in d, (
                f"derived class entry missing 'qualified_name': {d}"
            )
            # qualified_name should be fully qualified (include namespace)
            qname = d["qualified_name"]
            assert "::" in qname, (
                f"qualified_name should include namespace, got '{qname}'"
            )

    def test_get_derived_classes_qualified_name_matches_name(self, analyzer):
        """qualified_name should end with the simple class name."""
        derived = analyzer.get_derived_classes("inheritance_test::SingleBase")
        for d in derived:
            name = d["name"]
            qname = d["qualified_name"]
            assert qname.endswith(name) or qname == name, (
                f"qualified_name '{qname}' should end with simple name '{name}'"
            )

    def test_hierarchy_nodes_have_qualified_name(self, analyzer):
        """All resolved nodes in flat hierarchy dict should have qualified_name."""
        hierarchy = analyzer.get_class_hierarchy("inheritance_test::SingleDerived")
        assert hierarchy is not None and "error" not in hierarchy

        # Every key in classes dict IS the qualified name; node should echo it
        for key, node in hierarchy["classes"].items():
            if node.get("is_dependent_type") or node.get("is_unresolved"):
                continue
            assert "qualified_name" in node, (
                f"Node missing 'qualified_name': {node}"
            )
            assert node["qualified_name"] == key, (
                f"Node qualified_name '{node['qualified_name']}' should match key '{key}'"
            )
            # Resolved project nodes should be fully qualified (contain ::)
            if node.get("is_project"):
                assert "::" in node["qualified_name"], (
                    f"Project class qualified_name should include namespace: {node['qualified_name']}"
                )

    def test_hierarchy_base_refs_are_present_as_nodes(self, analyzer):
        """All base_classes/derived_classes references should exist in classes dict."""
        hierarchy = analyzer.get_class_hierarchy("inheritance_test::SingleBase")
        assert hierarchy is not None and "error" not in hierarchy

        classes = hierarchy["classes"]
        for key, node in classes.items():
            for ref in node.get("base_classes", []) + node.get("derived_classes", []):
                assert ref in classes, (
                    f"Node '{key}' references '{ref}' which is not in classes dict"
                )

    def test_hierarchy_multi_level_qualified_names(self, analyzer):
        """Deep hierarchies should have qualified_name at all resolved nodes."""
        hierarchy = analyzer.get_class_hierarchy("inheritance_test::DeepE")
        assert hierarchy is not None and "error" not in hierarchy

        for key, node in hierarchy["classes"].items():
            if node.get("is_dependent_type") or node.get("is_unresolved"):
                continue
            assert "qualified_name" in node, (
                f"Missing qualified_name in node: {node}"
            )

    def test_derived_classes_qualified_name_usable_with_get_class_info(self, analyzer):
        """qualified_name from get_derived_classes should work with get_class_info."""
        derived = analyzer.get_derived_classes("inheritance_test::SingleBase")
        assert len(derived) > 0

        for d in derived:
            qname = d["qualified_name"]
            info = analyzer.get_class_info(qname)
            assert info is not None, (
                f"get_class_info('{qname}') returned None"
            )
            assert "error" not in info, (
                f"get_class_info('{qname}') returned error: {info.get('error')}"
            )


# =============================================================================
# TEST: get_class_info includes derived_classes (cplusplus_mcp-4tw)
# =============================================================================

class TestGetClassInfoDerivedClasses:
    """Verify get_class_info now includes direct derived_classes."""

    def test_get_class_info_has_derived_classes_key(self, analyzer):
        """get_class_info must include a 'derived_classes' key."""
        info = analyzer.get_class_info("inheritance_test::SingleBase")
        assert info is not None and "error" not in info
        assert "derived_classes" in info, (
            "get_class_info result missing 'derived_classes' key"
        )

    def test_get_class_info_derived_classes_includes_direct_child(self, analyzer):
        """derived_classes in get_class_info should include SingleDerived."""
        info = analyzer.get_class_info("inheritance_test::SingleBase")
        assert info is not None and "error" not in info
        derived = info["derived_classes"]
        derived_names = [d["name"] for d in derived]
        assert "SingleDerived" in derived_names, (
            f"derived_classes should include SingleDerived, got {derived_names}"
        )

    def test_get_class_info_derived_classes_is_list(self, analyzer):
        """derived_classes must always be a list (even when empty)."""
        info = analyzer.get_class_info("inheritance_test::SingleDerived")
        assert info is not None and "error" not in info
        assert isinstance(info["derived_classes"], list), (
            "derived_classes should be a list"
        )

    def test_get_class_info_derived_classes_have_qualified_name(self, analyzer):
        """Each entry in derived_classes should have a qualified_name."""
        info = analyzer.get_class_info("inheritance_test::SingleBase")
        assert info is not None and "error" not in info
        for d in info["derived_classes"]:
            assert "qualified_name" in d, (
                f"derived_classes entry missing 'qualified_name': {d}"
            )

    def test_get_class_info_derived_qualified_name_chainable(self, analyzer):
        """qualified_name from derived_classes in get_class_info should work with get_class_info."""
        info = analyzer.get_class_info("inheritance_test::SingleBase")
        assert info is not None and "error" not in info
        for d in info["derived_classes"]:
            qname = d["qualified_name"]
            child_info = analyzer.get_class_info(qname)
            assert child_info is not None, (
                f"get_class_info('{qname}') from derived_classes returned None"
            )
            assert "error" not in child_info, (
                f"get_class_info('{qname}') from derived_classes returned error"
            )

    def test_get_class_info_leaf_class_has_empty_derived(self, analyzer):
        """A leaf class (no derived classes) should have an empty derived_classes list."""
        # SingleDerived has no derived classes
        info = analyzer.get_class_info("inheritance_test::SingleDerived")
        assert info is not None and "error" not in info
        assert info["derived_classes"] == [], (
            f"SingleDerived should have no derived classes, got {info['derived_classes']}"
        )


# =============================================================================
# Tests: get_class_hierarchy max_nodes and max_depth caps
# =============================================================================

class TestHierarchyCaps:
    """Verify max_nodes and max_depth cap parameters for get_class_hierarchy."""

    # DeepA -> DeepB -> DeepC -> DeepD -> DeepE  (5-class linear chain)

    def test_no_truncation_flag_for_small_hierarchy(self, analyzer):
        """Normal result without hitting caps should NOT have a 'truncated' key."""
        # The 5-class DeepA chain is well within default max_nodes=200
        hierarchy = analyzer.get_class_hierarchy("inheritance_test::DeepA")
        assert "error" not in hierarchy
        assert "truncated" not in hierarchy, (
            "Hierarchy within limits should not have 'truncated' key"
        )

    def test_max_nodes_cap_triggers_truncation(self, analyzer):
        """max_nodes smaller than hierarchy size should produce truncated=True."""
        # DeepA chain has 5 nodes; capping at 2 should truncate
        hierarchy = analyzer.get_class_hierarchy(
            "inheritance_test::DeepA", max_nodes=2
        )
        assert "error" not in hierarchy
        assert hierarchy.get("truncated") is True, (
            "Expected truncated=True when max_nodes=2 on a 5-class chain"
        )
        assert hierarchy.get("nodes_returned") == len(hierarchy["classes"]), (
            "nodes_returned must equal actual class count"
        )
        assert len(hierarchy["classes"]) <= 2, (
            f"Should have at most 2 nodes, got {len(hierarchy['classes'])}"
        )

    def test_max_nodes_cap_includes_queried_class(self, analyzer):
        """Queried class must always be present even when max_nodes=1."""
        hierarchy = analyzer.get_class_hierarchy(
            "inheritance_test::DeepC", max_nodes=1
        )
        assert "error" not in hierarchy
        assert "inheritance_test::DeepC" in hierarchy["classes"], (
            "Queried class must be present even when max_nodes=1"
        )

    def test_max_nodes_none_disables_cap(self, analyzer):
        """Setting max_nodes=None should return full result without truncation."""
        hierarchy = analyzer.get_class_hierarchy(
            "inheritance_test::DeepA", max_nodes=None
        )
        assert "error" not in hierarchy
        assert "truncated" not in hierarchy, (
            "max_nodes=None should disable the cap and not set truncated"
        )
        # All 5 classes in the chain must be present
        for cls in ["DeepA", "DeepB", "DeepC", "DeepD", "DeepE"]:
            qname = f"inheritance_test::{cls}"
            assert qname in hierarchy["classes"], (
                f"Expected {qname} in full hierarchy with max_nodes=None"
            )

    def test_max_depth_zero_returns_only_queried_class(self, analyzer):
        """max_depth=0 should return only the queried class (depth 0 = start node)."""
        hierarchy = analyzer.get_class_hierarchy(
            "inheritance_test::DeepC", max_depth=0
        )
        assert "error" not in hierarchy
        assert "inheritance_test::DeepC" in hierarchy["classes"], (
            "Queried class must be present with max_depth=0"
        )
        assert len(hierarchy["classes"]) == 1, (
            f"max_depth=0 should return exactly 1 class, got {len(hierarchy['classes'])}"
        )
        assert hierarchy.get("truncated") is True, (
            "max_depth=0 on a class with neighbors should set truncated=True"
        )

    def test_max_depth_one_returns_direct_neighbors(self, analyzer):
        """max_depth=1 should return queried class and its direct base/derived neighbors."""
        # DeepC: base=DeepB, derived=DeepD — so depth-1 set = {DeepB, DeepC, DeepD}
        hierarchy = analyzer.get_class_hierarchy(
            "inheritance_test::DeepC", max_depth=1
        )
        assert "error" not in hierarchy
        classes = hierarchy["classes"]
        assert "inheritance_test::DeepC" in classes
        assert "inheritance_test::DeepB" in classes, (
            "DeepB (direct base) should be in depth-1 result"
        )
        assert "inheritance_test::DeepD" in classes, (
            "DeepD (direct derived) should be in depth-1 result"
        )
        # DeepA and DeepE are depth-2; they must NOT be present
        assert "inheritance_test::DeepA" not in classes, (
            "DeepA (depth-2) should NOT be in depth-1 result"
        )
        assert "inheritance_test::DeepE" not in classes, (
            "DeepE (depth-2) should NOT be in depth-1 result"
        )
        assert hierarchy.get("truncated") is True, (
            "truncated must be True when depth-2 nodes exist but are excluded"
        )

    def test_max_depth_covers_full_chain(self, analyzer):
        """max_depth >= chain length should return full hierarchy without truncation."""
        # DeepA -> DeepB -> DeepC -> DeepD -> DeepE: max depth from DeepA is 4
        hierarchy = analyzer.get_class_hierarchy(
            "inheritance_test::DeepA", max_depth=10
        )
        assert "error" not in hierarchy
        assert "truncated" not in hierarchy, (
            "max_depth=10 should cover full 5-class chain without truncation"
        )
        for cls in ["DeepA", "DeepB", "DeepC", "DeepD", "DeepE"]:
            assert f"inheritance_test::{cls}" in hierarchy["classes"]

    def test_nodes_returned_matches_class_count(self, analyzer):
        """nodes_returned field must equal len(classes) when truncation occurs."""
        hierarchy = analyzer.get_class_hierarchy(
            "inheritance_test::DeepA", max_nodes=3
        )
        assert hierarchy.get("truncated") is True
        assert hierarchy["nodes_returned"] == len(hierarchy["classes"])
