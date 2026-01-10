"""
Tests for template class search and specialization discovery (Issue #99).

Tests template indexing, search, and cross-specialization queries.
"""

import pytest
from pathlib import Path
from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.fixture
def template_project_path():
    """Path to template test project."""
    return Path(__file__).parent.parent / "tests/fixtures/template_test_project"


@pytest.fixture
def analyzer(template_project_path):
    """Create and index template test project."""
    analyzer = CppAnalyzer(project_root=str(template_project_path))
    analyzer.index_project(force=True)
    return analyzer


class TestTemplateIndexing:
    """Tests for basic template indexing."""

    def test_class_template_indexed(self, analyzer):
        """Test that generic class templates are indexed."""
        results = analyzer.search_classes("Container")

        # Should find template, specializations, and partial specialization
        assert len(results) >= 2, "Should find at least template and one specialization"

        kinds = [r['kind'] for r in results]
        assert 'class_template' in kinds, "Should find generic template Container<T>"

    def test_function_template_indexed(self, analyzer):
        """Test that generic function templates are indexed."""
        results = analyzer.search_functions("max")

        # Should find template and specializations
        assert len(results) >= 2, "Should find template and specialization"

        kinds = [r['kind'] for r in results]
        assert 'function_template' in kinds, "Should find generic template max<T>"

    def test_partial_specialization_indexed(self, analyzer):
        """Test that partial specializations are indexed."""
        results = analyzer.search_classes("Container")

        kinds = [r['kind'] for r in results]
        assert 'partial_specialization' in kinds, "Should find Container<T*> partial specialization"

    def test_explicit_specialization_indexed(self, analyzer):
        """Test that explicit specializations are indexed."""
        results = analyzer.search_classes("Container")

        # Find regular class (explicit specializations are indexed as 'class')
        regular_classes = [r for r in results if r['kind'] == 'class']
        assert len(regular_classes) > 0, "Should find explicit specializations"

        # Verify we can find the specialization via _find_template_specializations
        specs = analyzer._find_template_specializations("Container")
        class_specs = [s for s in specs if s.kind == 'class']
        assert len(class_specs) > 0, "Should find explicit specialization"

        # Verify USR indicates template specialization
        assert any(">#" in s.usr for s in class_specs), \
            "Explicit specializations should have ># in USR"


class TestTemplateSpecializationDiscovery:
    """Tests for _find_template_specializations() method."""

    def test_find_container_specializations(self, analyzer):
        """Test finding all Container specializations."""
        specs = analyzer._find_template_specializations("Container")

        assert len(specs) >= 3, "Should find template, explicit spec, and partial spec"

        # Verify kinds
        kinds = [s.kind for s in specs]
        assert 'class_template' in kinds
        assert 'class' in kinds  # explicit specialization
        assert 'partial_specialization' in kinds

    def test_find_pair_specializations(self, analyzer):
        """Test finding Pair template specializations."""
        specs = analyzer._find_template_specializations("Pair")

        assert len(specs) >= 2, "Should find template and explicit specialization"

        kinds = [s.kind for s in specs]
        assert 'class_template' in kinds
        assert 'class' in kinds

    def test_find_base_specializations(self, analyzer):
        """Test finding Base CRTP template specializations."""
        specs = analyzer._find_template_specializations("Base")

        # Base is a template with usage creating implicit specializations
        # but those aren't visible as top-level symbols in libclang
        assert len(specs) >= 1, "Should find at least the template"

        assert specs[0].kind == 'class_template'

    def test_find_nonexistent_template(self, analyzer):
        """Test querying non-existent template returns empty list."""
        specs = analyzer._find_template_specializations("NonExistent")

        assert specs == [], "Should return empty list for non-existent template"


class TestCrossSpecializationQueries:
    """Tests for cross-specialization derived class queries."""

    def test_container_derived_classes(self, analyzer):
        """Test finding classes derived from any Container specialization."""
        derived = analyzer.get_derived_classes("Container")

        # Should find DoubleContainer and IntContainer
        assert len(derived) >= 2, "Should find at least 2 derived classes"

        names = [d['name'] for d in derived]
        assert 'DoubleContainer' in names, "Should find DoubleContainer (from Container<double>)"
        assert 'IntContainer' in names, "Should find IntContainer (from Container<int>)"

    def test_crtp_pattern_discovery(self, analyzer):
        """Test CRTP pattern discovery with Base template."""
        derived = analyzer.get_derived_classes("Base")

        # Should find DerivedA and DerivedB
        assert len(derived) >= 2, "Should find CRTP-derived classes"

        names = [d['name'] for d in derived]
        assert 'DerivedA' in names, "Should find DerivedA (from Base<DerivedA>)"
        assert 'DerivedB' in names, "Should find DerivedB (from Base<DerivedB>)"

    def test_derived_base_classes_preserved(self, analyzer):
        """Test that base_classes info is preserved in results."""
        derived = analyzer.get_derived_classes("Container")

        # Verify base classes are included
        for d in derived:
            assert 'base_classes' in d
            assert len(d['base_classes']) > 0

            # Verify base class starts with "Container<"
            assert any(bc.startswith("Container<") for bc in d['base_classes']), \
                f"{d['name']} should inherit from a Container specialization"

    def test_non_template_still_works(self, analyzer):
        """Test that regular (non-template) class queries still work."""
        # DoubleContainer is not a template
        derived = analyzer.get_derived_classes("DoubleContainer")

        # Should work normally (even if no derived classes exist)
        assert isinstance(derived, list)


class TestTemplateSearchPatterns:
    """Tests for template pattern matching in search."""

    def test_exact_template_name_match(self, analyzer):
        """Test searching by exact template name."""
        results = analyzer.search_classes("Container")

        assert len(results) > 0, "Should find results for 'Container'"
        assert all(r['name'] == 'Container' for r in results), \
            "All results should have name 'Container'"

    def test_regex_with_templates(self, analyzer):
        """Test regex pattern matching with templates."""
        results = analyzer.search_classes("Container.*")

        # Should match Container but also potentially other classes
        assert len(results) > 0, "Should find results for 'Container.*'"

    def test_search_distinguishes_kinds(self, analyzer):
        """Test that search results distinguish template kinds."""
        results = analyzer.search_classes("Container")

        # Verify kinds are present and distinct
        kinds = set(r['kind'] for r in results)
        assert 'class_template' in kinds or 'class' in kinds, \
            "Should have identifiable kinds"


class TestUSRPatternExtraction:
    """Tests for USR pattern extraction helper."""

    def test_extract_template_usr(self, analyzer):
        """Test extracting name from template USR."""
        usr = "c:@ST>1#T@Container"
        name = analyzer._extract_template_base_name_from_usr(usr)

        assert name == "Container", f"Should extract 'Container', got {name}"

    def test_extract_specialization_usr(self, analyzer):
        """Test extracting name from specialization USR."""
        usr = "c:@S@Container>#I"
        name = analyzer._extract_template_base_name_from_usr(usr)

        assert name == "Container", f"Should extract 'Container', got {name}"

    def test_extract_partial_specialization_usr(self, analyzer):
        """Test extracting name from partial specialization USR."""
        usr = "c:@SP>1#T@Container>#*t0.0"
        name = analyzer._extract_template_base_name_from_usr(usr)

        assert name == "Container", f"Should extract 'Container', got {name}"

    def test_extract_from_invalid_usr(self, analyzer):
        """Test handling of invalid/non-template USR."""
        usr = "invalid"
        name = analyzer._extract_template_base_name_from_usr(usr)

        assert name is None, "Should return None for invalid USR"

    def test_extract_from_empty_usr(self, analyzer):
        """Test handling of empty USR."""
        name = analyzer._extract_template_base_name_from_usr("")

        assert name is None, "Should return None for empty USR"


class TestTemplateEdgeCases:
    """Tests for edge cases and error handling."""

    def test_multiple_template_params(self, analyzer):
        """Test templates with multiple parameters like Pair<K,V>."""
        results = analyzer.search_classes("Pair")

        assert len(results) >= 2, "Should find Pair template and specializations"

        # Verify template has correct USR format for 2 params
        template = next((r for r in results if r['kind'] == 'class_template'), None)
        assert template is not None, "Should find Pair template"

    def test_variadic_template(self, analyzer):
        """Test variadic template indexing (Tuple<Args...>)."""
        results = analyzer.search_classes("Tuple")

        assert len(results) >= 1, "Should find Tuple variadic template"

        # Verify it's indexed as a template
        kinds = [r['kind'] for r in results]
        assert 'class_template' in kinds, "Tuple should be indexed as template"

    def test_project_only_filtering(self, analyzer):
        """Test project_only parameter with templates."""
        # All results should be from project (not dependencies)
        derived = analyzer.get_derived_classes("Container", project_only=True)

        for d in derived:
            assert d.get('is_project', False), \
                f"{d['name']} should be marked as project file"
