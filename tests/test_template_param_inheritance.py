"""
Tests for template parameter inheritance tracking.

Issue: cplusplus_mcp-hnj
Problem: When template<T> class Foo : public T, and class Bar : Foo<Base>,
         get_derived_classes("Base") should find Bar through indirect inheritance.
"""

import pytest
from pathlib import Path
from mcp_server.cpp_analyzer import CppAnalyzer


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
        derived_names = [d["name"] for d in derived]

        assert "DirectDerived" in derived_names, \
            f"DirectDerived should be found as directly inheriting from BaseClass. Found: {derived_names}"

    def test_indirect_inheritance_through_template_param(self, analyzer):
        """Test that classes inheriting via template param are found."""
        analyzer.index_project()

        # DerivedFromTemplate inherits from TemplateInheritsParam<BaseClass>
        # Since TemplateInheritsParam<T> : public T, this means
        # DerivedFromTemplate indirectly inherits from BaseClass
        derived = analyzer.get_derived_classes("BaseClass", project_only=False)
        derived_names = [d["name"] for d in derived]

        assert "DerivedFromTemplate" in derived_names, \
            f"DerivedFromTemplate should be found via template param inheritance. Found: {derived_names}"

    def test_indirect_inheritance_with_multiple_bases(self, analyzer):
        """Test template with multiple bases including template param."""
        analyzer.index_project()

        # DerivedFromTemplateMulti inherits from TemplateMultipleBases<BaseClass>
        # TemplateMultipleBases<T> : public T, public AnotherBase
        # So DerivedFromTemplateMulti indirectly inherits from BaseClass
        derived = analyzer.get_derived_classes("BaseClass", project_only=False)
        derived_names = [d["name"] for d in derived]

        assert "DerivedFromTemplateMulti" in derived_names, \
            f"DerivedFromTemplateMulti should be found via template param inheritance. Found: {derived_names}"

    def test_unrelated_class_not_included(self, analyzer):
        """Verify unrelated classes are not included."""
        analyzer.index_project()

        derived = analyzer.get_derived_classes("BaseClass", project_only=False)
        derived_names = [d["name"] for d in derived]

        assert "Unrelated" not in derived_names, \
            f"Unrelated should NOT be found as derived from BaseClass. Found: {derived_names}"

    def test_qualified_name_search(self, analyzer):
        """Test with qualified class name."""
        analyzer.index_project()

        # Search using qualified name
        derived = analyzer.get_derived_classes("ns::BaseClass", project_only=False)
        derived_names = [d["name"] for d in derived]

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
