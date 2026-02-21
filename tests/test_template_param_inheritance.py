"""
Tests for template parameter inheritance tracking.

Issue: cplusplus_mcp-hnj
Problem: When template<T> class Foo : public T, and class Bar : Foo<Base>,
         get_derived_classes("Base") should find Bar through indirect inheritance.
"""

import pytest
from pathlib import Path
from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server.symbol_info import get_template_param_base_indices, SymbolInfo


@pytest.fixture
def template_param_project():
    """Get path to template parameter inheritance fixtures."""
    fixtures_path = Path(__file__).parent / "fixtures" / "template_param_inheritance"
    return fixtures_path


@pytest.fixture
def analyzer(template_param_project):
    """Create a fresh analyzer instance for testing."""
    analyzer = CppAnalyzer(str(template_param_project))
    return analyzer


class TestTemplateParamInheritanceTracking:
    """Tests for detecting template parameter inheritance via _get_template_param_inheritance_indices."""

    def test_template_param_indices_detection(self, analyzer):
        """Test that _get_template_param_inheritance_indices correctly detects template param bases."""
        analyzer.index_project()

        # TemplateInheritsParam should inherit from param 0 (T)
        indices = analyzer._get_template_param_inheritance_indices("ns::TemplateInheritsParam")
        assert 0 in indices, \
            f"TemplateInheritsParam should inherit from param 0, got {indices}"

    def test_template_multiple_bases_indices_detection(self, analyzer):
        """Test detection for templates with multiple bases including template param."""
        analyzer.index_project()

        # TemplateMultipleBases inherits from T (param 0) and AnotherBase
        # Only T should be detected as template param base
        indices = analyzer._get_template_param_inheritance_indices("ns::TemplateMultipleBases")
        assert 0 in indices, \
            f"TemplateMultipleBases should inherit from param 0, got {indices}"
        # Should only have index 0 (the template param), not other indices
        assert len(indices) == 1, \
            f"Should only have one template param base, got {indices}"


class TestGetDerivedClassesWithTemplateParamInheritance:
    """Tests for get_derived_classes finding indirect inheritance."""

    def test_direct_inheritance_still_works(self, analyzer):
        """Verify direct inheritance detection still works."""
        analyzer.index_project()

        # DirectDerived directly inherits from BaseClass
        derived = analyzer.get_derived_classes("BaseClass", project_only=False)
        derived_names = [d["qualified_name"].split("::")[-1] for d in derived]

        assert "DirectDerived" in derived_names, \
            f"DirectDerived should be found as directly inheriting from BaseClass. Found: {derived_names}"

    def test_indirect_inheritance_through_template_param(self, analyzer):
        """Test that classes inheriting via template param are found."""
        analyzer.index_project()

        # DerivedFromTemplate inherits from TemplateInheritsParam<BaseClass>
        # Since TemplateInheritsParam<T> : public T, this means
        # DerivedFromTemplate indirectly inherits from BaseClass
        derived = analyzer.get_derived_classes("BaseClass", project_only=False)
        derived_names = [d["qualified_name"].split("::")[-1] for d in derived]

        assert "DerivedFromTemplate" in derived_names, \
            f"DerivedFromTemplate should be found via template param inheritance. Found: {derived_names}"

    def test_indirect_inheritance_with_multiple_bases(self, analyzer):
        """Test template with multiple bases including template param."""
        analyzer.index_project()

        # DerivedFromTemplateMulti inherits from TemplateMultipleBases<BaseClass>
        # TemplateMultipleBases<T> : public T, public AnotherBase
        # So DerivedFromTemplateMulti indirectly inherits from BaseClass
        derived = analyzer.get_derived_classes("BaseClass", project_only=False)
        derived_names = [d["qualified_name"].split("::")[-1] for d in derived]

        assert "DerivedFromTemplateMulti" in derived_names, \
            f"DerivedFromTemplateMulti should be found via template param inheritance. Found: {derived_names}"

    def test_unrelated_class_not_included(self, analyzer):
        """Verify unrelated classes are not included."""
        analyzer.index_project()

        derived = analyzer.get_derived_classes("BaseClass", project_only=False)
        derived_names = [d["qualified_name"].split("::")[-1] for d in derived]

        assert "Unrelated" not in derived_names, \
            f"Unrelated should NOT be found as derived from BaseClass. Found: {derived_names}"

    def test_qualified_name_search(self, analyzer):
        """Test with qualified class name."""
        analyzer.index_project()

        # Search using qualified name
        derived = analyzer.get_derived_classes("ns::BaseClass", project_only=False)
        derived_names = [d["qualified_name"].split("::")[-1] for d in derived]

        # Should still find the derived classes
        assert "DirectDerived" in derived_names or "DerivedFromTemplate" in derived_names, \
            f"Should find derived classes with qualified name search. Found: {derived_names}"


class TestParseTemplateArgs:
    """Tests for the _parse_template_args helper method."""

    def test_simple_args(self, analyzer):
        """Test parsing simple template arguments."""
        args = analyzer._parse_template_args("A, B, C")
        assert args == ["A", "B", "C"]

    def test_nested_templates(self, analyzer):
        """Test parsing nested template arguments."""
        args = analyzer._parse_template_args("A<B, C>, D")
        assert args == ["A<B, C>", "D"]

    def test_deeply_nested(self, analyzer):
        """Test parsing deeply nested template arguments."""
        args = analyzer._parse_template_args("A<B<C, D>, E>, F")
        assert args == ["A<B<C, D>, E>", "F"]

    def test_single_arg(self, analyzer):
        """Test parsing single template argument."""
        args = analyzer._parse_template_args("SomeClass")
        assert args == ["SomeClass"]

    def test_qualified_names(self, analyzer):
        """Test parsing qualified names as arguments."""
        args = analyzer._parse_template_args("ns::A, ns::B<ns::C>")
        assert args == ["ns::A", "ns::B<ns::C>"]


class TestCheckTemplateParamInheritance:
    """Tests for _check_template_param_inheritance helper method."""

    def test_no_template_returns_false(self, analyzer):
        """Test that non-template base class returns False."""
        result = analyzer._check_template_param_inheritance("BaseClass", "SomeTarget")
        assert result is False

    def test_unknown_template_returns_false(self, analyzer):
        """Test that unknown template returns False."""
        # Need to index first to populate template_param_bases
        analyzer.index_project()
        result = analyzer._check_template_param_inheritance("UnknownTemplate<SomeClass>", "SomeClass")
        assert result is False

    def test_matching_template_arg(self, analyzer):
        """Test matching when template arg equals target."""
        analyzer.index_project()

        # After indexing, TemplateInheritsParam should be in template_param_bases
        # So TemplateInheritsParam<BaseClass> should inherit from BaseClass
        result = analyzer._check_template_param_inheritance(
            "ns::TemplateInheritsParam<ns::BaseClass>", "ns::BaseClass"
        )
        assert result is True, "Should detect inheritance through template param"

    def test_simple_name_match(self, analyzer):
        """Test matching with simple names."""
        analyzer.index_project()

        # Should match even with different qualification
        result = analyzer._check_template_param_inheritance(
            "ns::TemplateInheritsParam<ns::BaseClass>", "BaseClass"
        )
        assert result is True, "Should detect inheritance with simple name target"


class TestTemplateParamNameCollision:
    """Tests for cplusplus_mcp-hff: Template parameter names must not cause
    false positives in get_derived_classes().

    Scenario: template<typename Base> class Adapter : public Base
    There's also a concrete struct 'Base'. Adapter should NOT appear
    as derived from the concrete struct 'Base'.
    """

    def test_template_param_not_false_positive_in_derived(self, analyzer):
        """template<typename Base> class Adapter : Base should NOT be derived from struct Base."""
        analyzer.index_project()

        derived = analyzer.get_derived_classes("Base", project_only=False)
        derived_names = [d["qualified_name"].split("::")[-1] for d in derived]

        # Adapter has template param named 'Base' - should NOT appear
        assert "Adapter" not in derived_names, (
            f"Adapter should NOT appear as derived from concrete struct Base. "
            f"Its 'Base' base class is a template parameter, not a concrete type. "
            f"Found: {derived_names}"
        )

    def test_real_derivation_still_found_alongside_collision(self, analyzer):
        """RealDerivedFromBase actually derives from struct Base - must still be found."""
        analyzer.index_project()

        derived = analyzer.get_derived_classes("Base", project_only=False)
        derived_names = [d["qualified_name"].split("::")[-1] for d in derived]

        assert "RealDerivedFromBase" in derived_names, (
            f"RealDerivedFromBase should be found as derived from struct Base. "
            f"Found: {derived_names}"
        )

    def test_indirect_inheritance_still_works_with_collision(self, analyzer):
        """Indirect inheritance through template instantiation should still work."""
        analyzer.index_project()

        # DerivedFromTemplate inherits from TemplateInheritsParam<BaseClass>
        # which inherits from its template param T=BaseClass
        # This is INDIRECT inheritance (through instantiation), not a false positive
        derived = analyzer.get_derived_classes("BaseClass", project_only=False)
        derived_names = [d["qualified_name"].split("::")[-1] for d in derived]

        assert "DerivedFromTemplate" in derived_names, (
            f"DerivedFromTemplate should still be found through indirect inheritance. "
            f"Found: {derived_names}"
        )


class TestGetTemplateParamBaseIndices:
    """Tests for get_template_param_base_indices() helper function."""

    def test_no_template_params(self):
        """Non-template class returns empty list."""
        info = SymbolInfo(
            name="Foo", kind="struct", file="test.h", line=1, column=1,
            base_classes=["Bar"],
            template_parameters=None,
        )
        assert get_template_param_base_indices(info) == []

    def test_no_base_classes(self):
        """Template with no base classes returns empty list."""
        info = SymbolInfo(
            name="Foo", kind="class_template", file="test.h", line=1, column=1,
            base_classes=[],
            template_parameters='[{"name": "T", "kind": "type"}]',
        )
        assert get_template_param_base_indices(info) == []

    def test_single_template_param_base(self):
        """template<typename T> class Foo : T -> index 0."""
        info = SymbolInfo(
            name="Foo", kind="class_template", file="test.h", line=1, column=1,
            base_classes=["T"],
            template_parameters='[{"name": "T", "kind": "type"}]',
        )
        assert get_template_param_base_indices(info) == [0]

    def test_mixed_bases(self):
        """template<typename T> class Foo : T, Bar -> only T is template param."""
        info = SymbolInfo(
            name="Foo", kind="class_template", file="test.h", line=1, column=1,
            base_classes=["T", "Bar"],
            template_parameters='[{"name": "T", "kind": "type"}]',
        )
        assert get_template_param_base_indices(info) == [0]

    def test_multiple_template_param_bases(self):
        """template<typename T, typename U> class Foo : T, U -> indices 0, 1."""
        info = SymbolInfo(
            name="Foo", kind="class_template", file="test.h", line=1, column=1,
            base_classes=["T", "U"],
            template_parameters='[{"name": "T", "kind": "type"}, {"name": "U", "kind": "type"}]',
        )
        assert get_template_param_base_indices(info) == [0, 1]

    def test_get_class_info_has_template_param_base_indices(self, analyzer):
        """get_class_info() should include template_param_base_indices field."""
        analyzer.index_project()

        info = analyzer.get_class_info("ns::Adapter")
        assert info is not None
        assert "error" not in info

        indices = info.get("template_param_base_indices", None)
        assert indices is not None, "template_param_base_indices field should be present"
        assert 0 in indices, (
            f"Adapter's first base class is template param 'Base', "
            f"should be in indices. Got: {indices}"
        )
