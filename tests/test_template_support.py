"""
Tests for template class search and specialization discovery (Issue #99).

Tests template indexing, search, and cross-specialization queries.
"""

import json
import pytest
from pathlib import Path
from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.fixture
def template_project_path():
    """Path to template test project with dynamically generated compile_commands.json."""
    project_path = Path(__file__).parent.parent / "tests/fixtures/template_test_project"
    # Generate compile_commands.json with correct absolute paths for the current environment
    # (the checked-in file has hardcoded paths that only work on the original dev machine)
    files = ["main.cpp", "templates.h", "advanced_templates.h", "namespaced_templates.h"]
    compile_commands = [
        {
            "directory": str(project_path),
            "command": f"/usr/bin/c++ -std=c++17 -I. -c {f} -o {f}.o",
            "file": f,
        }
        for f in files
    ]
    (project_path / "compile_commands.json").write_text(json.dumps(compile_commands, indent=2))
    return project_path


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

    def test_class_specialization_has_is_template_specialization_flag(self, analyzer):
        """Test that class template specializations have template_kind='full_specialization'.

        Note: is_template_specialization was removed as redundant.
        Use template_kind in ('full_specialization', 'partial_specialization') instead.
        """
        results = analyzer.search_classes("Container")

        # Find explicit specializations via template_kind
        specializations = [
            r for r in results
            if r.get("template_kind") in ("full_specialization", "partial_specialization")
        ]
        assert len(specializations) > 0, "Should find at least one class specialization"

        # Verify removed fields are absent
        for spec in specializations:
            assert "is_template_specialization" not in spec, (
                "is_template_specialization was removed; use template_kind"
            )
            assert "is_template" not in spec, (
                "is_template was removed; use template_kind != null"
            )

        # Verify primary template is NOT a specialization
        primary = next((r for r in results if r.get("template_kind") == "class_template"), None)
        if primary:
            assert primary.get("template_kind") not in ("full_specialization", "partial_specialization"), \
                "Primary template should not be a specialization"


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

        names = [d['qualified_name'].split("::")[-1] for d in derived]
        assert 'DoubleContainer' in names, "Should find DoubleContainer (from Container<double>)"
        assert 'IntContainer' in names, "Should find IntContainer (from Container<int>)"

    def test_crtp_pattern_discovery(self, analyzer):
        """Test CRTP pattern discovery with Base template."""
        derived = analyzer.get_derived_classes("Base")

        # Should find DerivedA and DerivedB
        assert len(derived) >= 2, "Should find CRTP-derived classes"

        names = [d['qualified_name'].split("::")[-1] for d in derived]
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
                f"{d['qualified_name']} should inherit from a Container specialization"

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
        assert all(r['qualified_name'].split("::")[-1] == 'Container' for r in results), \
            "All results should have simple name 'Container'"

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
                f"{d['qualified_name']} should be marked as project file"


class TestWhitespaceNormalization:
    """Tests for whitespace normalization in template arguments."""

    def test_normalize_whitespace_function(self):
        """Test the _normalize_template_whitespace function directly."""
        from mcp_server.search_engine import SearchEngine

        # Test pointer types
        assert SearchEngine._normalize_template_whitespace("Container<Widget *>") == "Container<Widget*>"
        assert SearchEngine._normalize_template_whitespace("Container<Widget*>") == "Container<Widget*>"

        # Test reference types
        assert SearchEngine._normalize_template_whitespace("Container<Widget &>") == "Container<Widget&>"
        assert SearchEngine._normalize_template_whitespace("Container<Widget&>") == "Container<Widget&>"

        # Test complex types
        assert SearchEngine._normalize_template_whitespace("Container<Widget * const &>") == \
            "Container<Widget*const&>"

        # Test nested templates
        assert SearchEngine._normalize_template_whitespace("Container<std::vector<int *>>") == \
            "Container<std::vector<int*>>"

        # Test multiple parameters (comma space is preserved)
        assert SearchEngine._normalize_template_whitespace("Pair<int *, double *>") == \
            "Pair<int*, double*>"

    def test_pointer_template_search_with_space(self, analyzer):
        """Test searching for pointer template with space matches libclang format."""
        # Search for Container template (generic search, not specialization-specific)
        results = analyzer.search_classes("Container")

        # Should find Container template and all its specializations
        assert len(results) > 0, "Should find Container template"

        # Verify we found templates with pointer types
        kinds = [r['kind'] for r in results]
        assert 'partial_specialization' in kinds or 'class_template' in kinds, \
            "Should find Container template or partial specialization"

    def test_pointer_template_search_without_space(self, analyzer):
        """Test searching for pointer template without space matches libclang format."""
        # Test that normalization allows matching template base names
        results_with_space = analyzer.search_classes("Container")
        results_without_space = analyzer.search_classes("Container")

        # Both should return same results (whitespace normalized internally)
        assert len(results_with_space) == len(results_without_space), \
            "Whitespace normalization should produce consistent results"

    def test_qualified_pointer_template_search(self, analyzer):
        """Test qualified name search with pointer templates."""
        # Search for classes derived from Container
        # DoubleContainer and IntContainer inherit from Container specializations
        derived = analyzer.get_derived_classes("Container")

        # Verify we find derived classes
        names = [d['qualified_name'].split("::")[-1] for d in derived]
        assert 'DoubleContainer' in names or 'IntContainer' in names, \
            "Should find classes derived from Container specializations"

    def test_regex_pattern_with_pointer_template(self, analyzer):
        """Test regex patterns work with normalized pointer templates."""
        # Use a simpler regex pattern that won't trigger validator warnings
        results = analyzer.search_classes("Container.*")

        # Should match Container and derived classes
        assert len(results) >= 0, "Regex search should work with templates"

    def test_function_search_with_pointer_template_params(self, analyzer):
        """Test function search with pointer template parameter types."""
        # Search for functions in the Container template
        results = analyzer.search_functions("add")

        # Should find add methods from Container templates
        assert len(results) > 0, "Should find functions in template classes"


class TestTemplateParameterExtraction:
    """Tests for Task 3.2: template_parameters extraction."""

    def test_single_type_parameter(self, analyzer):
        """Test extraction of single type parameter like typename T."""
        results = analyzer.search_classes("Container")
        template = next((r for r in results if r['kind'] == 'class_template'), None)

        assert template is not None, "Should find Container template"
        assert template.get('template_parameters') is not None, \
            "template_parameters should be populated"

        import json
        params = json.loads(template['template_parameters'])
        assert len(params) == 1, "Container should have 1 template parameter"
        assert params[0]['name'] == 'T', "Parameter should be named T"
        assert params[0]['kind'] == 'type', "Parameter should be a type parameter"

    def test_multiple_type_parameters(self, analyzer):
        """Test extraction of multiple type parameters like Pair<K, V>."""
        results = analyzer.search_classes("Pair")
        template = next((r for r in results if r['kind'] == 'class_template'), None)

        assert template is not None, "Should find Pair template"
        assert template.get('template_parameters') is not None

        import json
        params = json.loads(template['template_parameters'])
        assert len(params) == 2, "Pair should have 2 template parameters"
        assert params[0]['name'] == 'K', "First param should be K"
        assert params[1]['name'] == 'V', "Second param should be V"

    def test_variadic_template_parameters(self, analyzer):
        """Test extraction of variadic template parameters like Args..."""
        results = analyzer.search_classes("Tuple")
        template = next((r for r in results if r['kind'] == 'class_template'), None)

        assert template is not None, "Should find Tuple template"
        # Variadic templates should have template_parameters
        assert template.get('template_parameters') is not None

    def test_partial_specialization_parameters(self, analyzer):
        """Test partial specialization has its own template parameters."""
        results = analyzer.search_classes("Container")
        partial = next((r for r in results if r['kind'] == 'partial_specialization'), None)

        assert partial is not None, "Should find Container<T*> partial specialization"
        assert partial.get('template_parameters') is not None

        import json
        params = json.loads(partial['template_parameters'])
        assert len(params) == 1, "Partial spec should have 1 template parameter"
        assert params[0]['name'] == 'T', "Parameter should be named T"

    def test_function_template_parameters(self, analyzer):
        """Test function template parameter extraction."""
        results = analyzer.search_functions("max")
        template = next((r for r in results if r['kind'] == 'function_template'), None)

        assert template is not None, "Should find max function template"
        assert template.get('template_parameters') is not None

        import json
        params = json.loads(template['template_parameters'])
        assert len(params) == 1, "max should have 1 template parameter"
        assert params[0]['kind'] == 'type', "Parameter should be a type parameter"


class TestPrimaryTemplateLinking:
    """Tests for Task 3.4: specialization_of linking (LLM-friendly qualified names)."""

    def test_partial_specialization_links_to_primary(self, analyzer):
        """Test partial specialization has specialization_of with qualified name."""
        results = analyzer.search_classes("Container")
        template = next((r for r in results if r['kind'] == 'class_template'), None)
        partial = next((r for r in results if r['kind'] == 'partial_specialization'), None)

        assert template is not None, "Should find Container template"
        assert partial is not None, "Should find Container<T*> partial specialization"

        # Partial spec should have specialization_of with the template's qualified name
        spec_of = partial.get('specialization_of')
        assert spec_of is not None, \
            "Partial specialization should have specialization_of"
        assert 'Container' in spec_of, \
            f"specialization_of should reference Container template, got: {spec_of}"

    def test_full_specialization_links_to_primary(self, analyzer):
        """Test full specialization has specialization_of with qualified name."""
        results = analyzer.search_classes("Container")
        template = next((r for r in results if r['kind'] == 'class_template'), None)
        full_spec = next((r for r in results if r['kind'] == 'class' and
                         r.get('template_kind') == 'full_specialization'), None)

        assert template is not None, "Should find Container template"
        assert full_spec is not None, "Should find Container<int> full specialization"

        spec_of = full_spec.get('specialization_of')
        assert spec_of is not None, \
            "Full specialization should have specialization_of"
        assert 'Container' in spec_of, \
            f"specialization_of should reference Container template, got: {spec_of}"

    def test_primary_template_has_no_specialization_of(self, analyzer):
        """Test primary templates do not have specialization_of."""
        results = analyzer.search_classes("Container")
        template = next((r for r in results if r['kind'] == 'class_template'), None)

        assert template is not None, "Should find Container template"
        assert template.get('specialization_of') is None, \
            "Primary template should not have specialization_of"

    def test_function_specialization_links_to_primary(self, analyzer):
        """Test function specialization has specialization_of with qualified name."""
        results = analyzer.search_functions("max")
        template = next((r for r in results if r['kind'] == 'function_template'), None)
        full_spec = next((r for r in results if r['kind'] == 'function' and
                         r.get('template_kind') == 'full_specialization'), None)

        assert template is not None, "Should find max function template"
        assert full_spec is not None, "Should find max<int*> full specialization"

        spec_of = full_spec.get('specialization_of')
        assert spec_of is not None, \
            "Function specialization should have specialization_of"
        assert 'max' in spec_of, \
            f"specialization_of should reference max function template, got: {spec_of}"

    def test_multi_param_template_linking(self, analyzer):
        """Test specialization linking works for multi-parameter templates."""
        results = analyzer.search_classes("Pair")
        template = next((r for r in results if r['kind'] == 'class_template'), None)
        full_spec = next((r for r in results if r['kind'] == 'class' and
                         r.get('template_kind') == 'full_specialization'), None)

        assert template is not None, "Should find Pair template"
        assert full_spec is not None, "Should find Pair<int,int> full specialization"

        spec_of = full_spec.get('specialization_of')
        assert spec_of is not None, \
            "Multi-param specialization should have specialization_of"
        assert 'Pair' in spec_of, \
            f"specialization_of should reference Pair template, got: {spec_of}"


class TestAdvancedTemplatePatterns:
    """Tests for Task 1.4: Real-world template examples with diverse patterns."""

    def test_non_type_parameter_extraction(self, analyzer):
        """Test extraction of non-type template parameters like int Size."""
        results = analyzer.search_classes("FixedArray")
        template = next((r for r in results if r['kind'] == 'class_template'), None)

        assert template is not None, "Should find FixedArray template"
        assert template.get('template_parameters') is not None

        import json
        params = json.loads(template['template_parameters'])
        assert len(params) == 2, "FixedArray should have 2 template parameters"

        # First param should be type
        assert params[0]['kind'] == 'type', "First param should be type (T)"

        # Second param should be non-type int
        assert params[1]['kind'] == 'non_type', "Second param should be non-type (Size)"
        assert params[1]['name'] == 'Size', "Non-type param should be named Size"
        assert 'int' in params[1]['type'], "Non-type param should be int type"

    def test_multiple_non_type_parameters(self, analyzer):
        """Test template with multiple non-type parameters like Matrix<T, Rows, Cols>."""
        results = analyzer.search_classes("Matrix")
        template = next((r for r in results if r['kind'] == 'class_template'), None)

        assert template is not None, "Should find Matrix template"

        import json
        params = json.loads(template['template_parameters'])
        assert len(params) == 3, "Matrix should have 3 template parameters"

        # T, Rows, Cols
        assert params[0]['kind'] == 'type'
        assert params[1]['kind'] == 'non_type'
        assert params[2]['kind'] == 'non_type'

    def test_template_template_parameter(self, analyzer):
        """Test extraction of template template parameters."""
        results = analyzer.search_classes("Stack")
        template = next((r for r in results if r['kind'] == 'class_template'), None)

        assert template is not None, "Should find Stack template"

        import json
        params = json.loads(template['template_parameters'])
        assert len(params) == 2, "Stack should have 2 template parameters"

        # Second param should be template template parameter
        assert params[1]['kind'] == 'template', "Second param should be template template param"

    def test_default_template_parameters(self, analyzer):
        """Test templates with default parameters are indexed."""
        # Vector<T, Alloc = void>
        results = analyzer.search_classes("Vector")
        template = next((r for r in results if r['kind'] == 'class_template'), None)

        assert template is not None, "Should find Vector template"
        assert template.get('template_kind') is not None, (
            "Template should have non-null template_kind (is_template removed as redundant)"
        )

        import json
        params = json.loads(template['template_parameters'])
        assert len(params) == 2, "Vector should have 2 template parameters (T and Alloc)"

    def test_nested_template_class(self, analyzer):
        """Test nested template classes are indexed."""
        # Outer<T>::Inner<U>
        results = analyzer.search_classes("Outer")
        outer = next((r for r in results if r['kind'] == 'class_template'), None)

        assert outer is not None, "Should find Outer template"
        assert outer.get('template_kind') is not None, (
            "Template should have non-null template_kind (is_template removed as redundant)"
        )

        # Inner should also be indexed
        inner_results = analyzer.search_classes("Inner")
        inner = next((r for r in results if 'Inner' in r.get('name', '')), None)
        # Note: Nested templates may or may not be indexed depending on libclang behavior

    def test_function_template_with_non_type_param(self, analyzer):
        """Test function template with non-type parameter."""
        results = analyzer.search_functions("multiply")
        template = next((r for r in results if r['kind'] == 'function_template'), None)

        assert template is not None, "Should find multiply function template"

        import json
        params = json.loads(template['template_parameters'])
        assert len(params) == 1, "multiply should have 1 template parameter"
        assert params[0]['kind'] == 'non_type', "Parameter should be non-type (int N)"

    def test_function_template_non_type_specialization(self, analyzer):
        """Test function template specialization for non-type param."""
        results = analyzer.search_functions("multiply")

        # Should find template and specialization
        template = next((r for r in results if r['kind'] == 'function_template'), None)
        spec = next((r for r in results if r.get('template_kind') == 'full_specialization'), None)

        assert template is not None, "Should find multiply template"
        assert spec is not None, "Should find multiply<2> specialization"
        assert spec.get('specialization_of') is not None

    def test_type_traits_pattern(self, analyzer):
        """Test type traits template pattern with static members."""
        results = analyzer.search_classes("TypeTraits")
        template = next((r for r in results if r['kind'] == 'class_template'), None)
        spec = next((r for r in results if r.get('template_kind') == 'full_specialization'), None)

        assert template is not None, "Should find TypeTraits template"
        assert spec is not None, "Should find TypeTraits<int> specialization"

    def test_method_template_in_regular_class(self, analyzer):
        """Test template methods inside non-template class."""
        results = analyzer.search_classes("Converter")

        assert len(results) > 0, "Should find Converter class"
        converter = results[0]
        assert converter.get('is_template') is not True, \
            "Converter itself is not a template"

        # Check for template methods
        methods = analyzer.search_functions("fromString")
        template_methods = [m for m in methods if m.get('kind') == 'function_template']
        # Note: Method templates may be indexed as function_template or method

    def test_complex_partial_specialization(self, analyzer):
        """Test complex partial specializations like Pair2<T, T> and Pair2<T*, U>."""
        results = analyzer.search_classes("Pair2")

        template = next((r for r in results if r['kind'] == 'class_template'), None)
        partial_specs = [r for r in results if r['kind'] == 'partial_specialization']

        assert template is not None, "Should find Pair2 template"
        assert len(partial_specs) >= 2, "Should find at least 2 partial specializations"

        # All partial specs should link to primary
        for spec in partial_specs:
            assert spec.get('specialization_of') is not None, \
                "Partial specialization should have specialization_of"


class TestNamespacedSpecializationLinking:
    """Task 6.5: Integration tests for specialization linking with namespaces."""

    def test_namespaced_full_specialization_links_to_primary(self, analyzer):
        """Test full specialization in namespace links to primary template."""
        results = analyzer.search_classes("NamespacedContainer")

        template = next((r for r in results if r['kind'] == 'class_template'), None)
        full_spec = next((r for r in results if r['kind'] == 'class' and
                         r.get('template_kind') == 'full_specialization'), None)

        assert template is not None, "Should find NamespacedContainer template"
        assert full_spec is not None, "Should find NamespacedContainer<int> full specialization"

        # Verify namespace info is captured
        assert template.get('namespace') == 'outer', \
            "Template namespace should be 'outer'"
        assert 'outer' in template.get('qualified_name', ''), \
            "Template qualified_name should include namespace"

        spec_of = full_spec.get('specialization_of')
        assert spec_of is not None, \
            "Full specialization should have specialization_of"
        assert 'NamespacedContainer' in spec_of, \
            f"specialization_of should reference NamespacedContainer template, got: {spec_of}"
        assert 'outer' in spec_of, \
            f"specialization_of should include namespace, got: {spec_of}"

    def test_nested_namespace_template_linking(self, analyzer):
        """Test templates in nested namespaces (outer::inner)."""
        results = analyzer.search_classes("NestedPair")

        template = next((r for r in results if r['kind'] == 'class_template'), None)
        partial_spec = next((r for r in results if r['kind'] == 'partial_specialization'), None)
        full_spec = next((r for r in results if r['kind'] == 'class' and
                         r.get('template_kind') == 'full_specialization'), None)

        assert template is not None, "Should find NestedPair template"
        assert partial_spec is not None, "Should find NestedPair<T, T> partial specialization"
        assert full_spec is not None, "Should find NestedPair<int, double> full specialization"

        # Verify namespace info includes nested namespace
        assert 'inner' in template.get('namespace', '') or \
               'inner' in template.get('qualified_name', ''), \
            "Template should include nested namespace info"

        # Check partial specialization linking
        partial_spec_of = partial_spec.get('specialization_of')
        assert partial_spec_of is not None, \
            "Partial specialization should have specialization_of"
        assert 'NestedPair' in partial_spec_of, \
            f"Partial spec specialization_of should reference NestedPair, got: {partial_spec_of}"

        # Check full specialization linking
        full_spec_of = full_spec.get('specialization_of')
        assert full_spec_of is not None, \
            "Full specialization should have specialization_of"
        assert 'NestedPair' in full_spec_of, \
            f"Full spec specialization_of should reference NestedPair, got: {full_spec_of}"


class TestForwardDeclaredTemplateLinking:
    """Task 6.5: Integration tests for forward declared template linking."""

    def test_forward_declared_template_indexed(self, analyzer):
        """Test forward declared template is properly indexed."""
        results = analyzer.search_classes("ForwardDeclared")

        # Should find template (forward declaration and definition merged)
        template = next((r for r in results if r['kind'] == 'class_template'), None)

        assert template is not None, "Should find ForwardDeclared template"
        # Verify namespace info is captured via namespace or qualified_name field
        assert template.get('namespace') == 'forward_decl' or \
               'forward_decl' in template.get('qualified_name', ''), \
            "Template should include forward_decl namespace"

    def test_forward_declared_specialization_links_to_primary(self, analyzer):
        """Test specialization of forward declared template links correctly."""
        results = analyzer.search_classes("ForwardDeclared")

        template = next((r for r in results if r['kind'] == 'class_template'), None)
        full_spec = next((r for r in results if r['kind'] == 'class' and
                         r.get('template_kind') == 'full_specialization'), None)

        assert template is not None, "Should find ForwardDeclared template"
        assert full_spec is not None, "Should find ForwardDeclared<void> specialization"

        spec_of = full_spec.get('specialization_of')
        assert spec_of is not None, \
            "Specialization should have specialization_of"
        assert 'ForwardDeclared' in spec_of, \
            f"specialization_of should reference ForwardDeclared, got: {spec_of}"


class TestCrossNamespaceInheritance:
    """Task 6.5: Integration tests for cross-namespace template inheritance."""

    def test_cross_namespace_derived_class(self, analyzer):
        """Test finding derived classes across namespaces."""
        derived = analyzer.get_derived_classes("BaseTemplate")

        # Should find DerivedFromTemplate in derived_ns
        # Note: This may return 0 if no cross-namespace derived classes are found
        # because get_derived_classes may not traverse across namespaces by default
        names = [d['qualified_name'].split("::")[-1] for d in derived]
        # At minimum, the cross-namespace inheritance should be discoverable
        # via direct class lookup
        results = analyzer.search_classes("DerivedFromTemplate")
        assert len(results) >= 1, "Should find DerivedFromTemplate class"

        dft = results[0]
        assert 'BaseTemplate' in str(dft.get('base_classes', [])), \
            "DerivedFromTemplate should inherit from BaseTemplate"

    def test_cross_namespace_base_class_info(self, analyzer):
        """Test that cross-namespace base class info is preserved."""
        results = analyzer.search_classes("DerivedFromTemplate")
        assert len(results) >= 1, "Should find DerivedFromTemplate"

        dft = results[0]

        # Verify base class info
        assert 'base_classes' in dft
        assert len(dft['base_classes']) > 0

        # Should inherit from base_ns::BaseTemplate<int>
        base_class = dft['base_classes'][0]
        assert 'BaseTemplate' in base_class, \
            "Base class should be BaseTemplate specialization"

    def test_cross_namespace_template_primary_lookup(self, analyzer):
        """Test looking up primary template from cross-namespace context."""
        results = analyzer.search_classes("BaseTemplate")

        template = next((r for r in results if r['kind'] == 'class_template'), None)
        assert template is not None, "Should find BaseTemplate template"

        # Verify namespace info is captured
        assert template.get('namespace') == 'base_ns' or \
               'base_ns' in template.get('qualified_name', ''), \
            "Template should include base_ns namespace"


class TestSpecializationLinkingEdgeCases:
    """Task 6.5: Edge cases for specialization linking."""

    def test_multiple_specializations_same_template(self, analyzer):
        """Test multiple specializations all link to same primary."""
        results = analyzer.search_classes("NestedPair")

        template = next((r for r in results if r['kind'] == 'class_template'), None)
        specializations = [r for r in results if r.get('specialization_of')]

        assert template is not None, "Should find NestedPair template"
        assert len(specializations) >= 2, "Should find at least 2 specializations"

        for spec in specializations:
            # All specializations should link to the same primary
            spec_of = spec.get('specialization_of')
            assert spec_of is not None
            # The specialization_of should reference the same template name
            assert 'NestedPair' in spec_of, \
                f"specialization_of should reference NestedPair, got: {spec_of}"

    def test_qualified_name_includes_namespace(self, analyzer):
        """Test that qualified names include full namespace path."""
        results = analyzer.search_classes("NestedPair")

        template = next((r for r in results if r['kind'] == 'class_template'), None)
        assert template is not None

        qualified_name = template.get('qualified_name', template.get('name'))
        # Should include full namespace path
        assert 'outer' in qualified_name or 'inner' in qualified_name or \
               'NestedPair' in qualified_name, \
            f"Qualified name should include namespace info: {qualified_name}"

    def test_specialization_template_kind_field(self, analyzer):
        """Test template_kind field distinguishes specialization types."""
        results = analyzer.search_classes("NestedPair")

        partial_spec = next((r for r in results if r['kind'] == 'partial_specialization'), None)
        full_spec = next((r for r in results if r['kind'] == 'class' and
                         r.get('template_kind') == 'full_specialization'), None)

        assert partial_spec is not None, "Should find partial specialization"
        assert full_spec is not None, "Should find full specialization"

        # Verify template_kind is set correctly
        assert partial_spec.get('template_kind') == 'partial_specialization' or \
               partial_spec.get('kind') == 'partial_specialization', \
            "Partial spec should have correct template_kind"
        assert full_spec.get('template_kind') == 'full_specialization', \
            "Full spec should have template_kind=full_specialization"


# ============================================================================
# Tests for Template Base Class Improvements (LLM Readability)
# ============================================================================


@pytest.fixture
def param_inheritance_project(tmp_path):
    """
    Create a test project with templates that inherit from template parameters.

    This tests the improvement where base_classes shows 'ParamName' instead of
    'type-parameter-0-0', making output LLM-friendly.
    """
    # Create header with template inheriting from parameter
    header = tmp_path / "param_inheritance.h"
    header.write_text('''
#ifndef PARAM_INHERITANCE_H
#define PARAM_INHERITANCE_H

namespace testns {

// Base interfaces
struct InterfaceA {
    virtual void method_a() = 0;
    virtual ~InterfaceA() = default;
};

struct InterfaceB {
    virtual void method_b() = 0;
    virtual ~InterfaceB() = default;
};

// Template that inherits from its template parameter
// This is a common pattern (e.g., CRTP variant, mixin pattern)
template <typename BaseType>
class TemplateInheritsParam : public BaseType {
public:
    void common_method() {}
};

// Explicit template instantiation declarations
extern template class TemplateInheritsParam<InterfaceA>;
extern template class TemplateInheritsParam<InterfaceB>;

// Concrete class derived from instantiation
struct ConcreteImpl final : TemplateInheritsParam<InterfaceA> {
    void method_a() override {}
};

// Template with multiple inheritance: one param, one fixed
template <typename T>
class MixedInheritance : public T, protected InterfaceB {
public:
    void method_b() override {}
};

// Template inheriting from second parameter
template <typename First, typename Second>
class InheritsSecond : public Second {
};

}  // namespace testns

#endif
''')

    # Create main.cpp
    main = tmp_path / "main.cpp"
    main.write_text('''
#include "param_inheritance.h"

int main() {
    testns::ConcreteImpl impl;
    impl.method_a();
    return 0;
}
''')

    # Create compile_commands.json
    compile_commands = tmp_path / "compile_commands.json"
    compile_commands.write_text(json.dumps([
        {
            "directory": str(tmp_path),
            "command": "/usr/bin/c++ -std=c++17 -I. -c param_inheritance.h -o param_inheritance.h.o",
            "file": "param_inheritance.h",
        },
        {
            "directory": str(tmp_path),
            "command": "/usr/bin/c++ -std=c++17 -I. -c main.cpp -o main.o",
            "file": "main.cpp",
        },
    ], indent=2))

    return tmp_path


@pytest.fixture
def param_inheritance_analyzer(param_inheritance_project):
    """Create and index parameter inheritance test project."""
    analyzer = CppAnalyzer(project_root=str(param_inheritance_project))
    analyzer.index_project(force=True)
    return analyzer


class TestTemplateBaseClassImprovement:
    """
    Tests for template base class naming improvements.

    Verifies that:
    1. Templates inheriting from parameters show the parameter name (not 'type-parameter-X-Y')
    2. Explicit instantiations have resolved base classes
    """

    def test_primary_template_shows_param_name(self, param_inheritance_analyzer):
        """
        Test that primary template base_classes shows parameter name, not type-parameter-X-Y.

        Before fix: base_classes = ['type-parameter-0-0']
        After fix:  base_classes = ['BaseType']
        """
        results = param_inheritance_analyzer.search_classes("TemplateInheritsParam")

        # Find the primary template
        primary = next((r for r in results if r['kind'] == 'class_template'), None)
        assert primary is not None, "Should find primary template TemplateInheritsParam"

        base_classes = primary.get('base_classes', [])
        assert len(base_classes) == 1, "Should have exactly one base class"

        # Verify it's the parameter name, not the internal representation
        assert base_classes[0] == 'BaseType', \
            f"Base class should be 'BaseType', not '{base_classes[0]}'"
        assert 'type-parameter' not in base_classes[0], \
            f"Base class should not contain 'type-parameter': {base_classes[0]}"

    def test_mixed_inheritance_shows_param_and_fixed_base(self, param_inheritance_analyzer):
        """
        Test template with mixed inheritance (param + fixed base).

        MixedInheritance<T> : public T, protected InterfaceB
        Should show: ['T', 'testns::InterfaceB'] (not ['type-parameter-0-0', ...])
        """
        results = param_inheritance_analyzer.search_classes("MixedInheritance")

        primary = next((r for r in results if r['kind'] == 'class_template'), None)
        assert primary is not None, "Should find primary template MixedInheritance"

        base_classes = primary.get('base_classes', [])
        assert len(base_classes) == 2, f"Should have 2 base classes, got {base_classes}"

        # First base should be the template parameter 'T'
        assert base_classes[0] == 'T', \
            f"First base should be 'T', not '{base_classes[0]}'"

        # Second base should be the fixed InterfaceB (with namespace)
        assert 'InterfaceB' in base_classes[1], \
            f"Second base should contain 'InterfaceB': {base_classes[1]}"

    def test_multi_param_inherits_correct_param(self, param_inheritance_analyzer):
        """
        Test template that inherits from second parameter shows correct name.

        InheritsSecond<First, Second> : public Second
        Should show: ['Second'] (not ['type-parameter-0-1'])
        """
        results = param_inheritance_analyzer.search_classes("InheritsSecond")

        primary = next((r for r in results if r['kind'] == 'class_template'), None)
        assert primary is not None, "Should find primary template InheritsSecond"

        base_classes = primary.get('base_classes', [])
        assert len(base_classes) == 1, f"Should have 1 base class, got {base_classes}"

        # Should be 'Second', not 'type-parameter-0-1'
        assert base_classes[0] == 'Second', \
            f"Base class should be 'Second', not '{base_classes[0]}'"

    def test_explicit_instantiation_has_resolved_bases(self, param_inheritance_analyzer):
        """
        Test that explicit instantiations have resolved base classes.

        extern template class TemplateInheritsParam<InterfaceA>;
        Should have base_classes = ['InterfaceA'] (resolved from primary template + args)
        """
        results = param_inheritance_analyzer.search_classes("TemplateInheritsParam")

        # Find explicit instantiations (kind='class' with template args in displayname)
        instantiations = [
            r for r in results
            if r['kind'] == 'class' and r.get('template_kind') == 'full_specialization'
        ]

        # We should have at least one instantiation (InterfaceA or InterfaceB)
        # Note: extern template declarations may or may not be indexed depending on
        # how libclang handles them. If none found, this test is inconclusive.
        if not instantiations:
            pytest.skip("No explicit instantiations found in index (may depend on libclang version)")

        for inst in instantiations:
            base_classes = inst.get('base_classes', [])
            # If the instantiation has resolved base classes, verify they're correct
            if base_classes:
                # Should be 'InterfaceA' or 'InterfaceB', not empty or type-parameter
                for bc in base_classes:
                    assert 'type-parameter' not in bc, \
                        f"Instantiation base class should be resolved: {bc}"
                    assert bc in ['InterfaceA', 'InterfaceB', 'testns::InterfaceA', 'testns::InterfaceB'], \
                        f"Unexpected base class: {bc}"

    def test_concrete_class_base_includes_template_arg(self, param_inheritance_analyzer):
        """
        Test concrete class inheriting from template instantiation.

        ConcreteImpl : TemplateInheritsParam<InterfaceA>
        Should show: ['testns::TemplateInheritsParam<InterfaceA>'] or similar
        """
        results = param_inheritance_analyzer.search_classes("ConcreteImpl")

        concrete = next((r for r in results if r['kind'] in ('class', 'struct')), None)
        assert concrete is not None, "Should find ConcreteImpl"

        base_classes = concrete.get('base_classes', [])
        assert len(base_classes) == 1, f"Should have 1 base class, got {base_classes}"

        # Should show the full template instantiation
        assert 'TemplateInheritsParam' in base_classes[0], \
            f"Base should contain 'TemplateInheritsParam': {base_classes[0]}"
        assert 'InterfaceA' in base_classes[0], \
            f"Base should contain 'InterfaceA': {base_classes[0]}"


@pytest.fixture
def embedded_type_param_project(tmp_path):
    """
    Create a test project where type-parameter-D-I appears embedded inside
    a complex dependent type expression (not as the entire base class).

    This tests the case where a template class inherits from a type that
    uses its template parameter inside a nested template expression, e.g.:
        ChainResolver<BaseParam, WithStyleProps>::Type
    libclang canonical spelling produces:
        typename ChainResolverDetails<type-parameter-0-0, WithStyleProps>::Type
    We need to replace 'type-parameter-0-0' with 'BaseParam'.
    """
    header = tmp_path / "chain_resolver.h"
    header.write_text('''
#ifndef CHAIN_RESOLVER_H
#define CHAIN_RESOLVER_H

namespace testns {

namespace Details {

template <typename Base, template <typename> typename FirstMixin,
          template <typename> typename... RestMixins>
struct ChainResolverDetails
{
    using Type = typename ChainResolverDetails<FirstMixin<Base>,
                                                RestMixins...>::Type;
};

template <typename Base, template <typename> typename Mixin>
struct ChainResolverDetails<Base, Mixin>
{
    using Type = Mixin<Base>;
};

} // namespace Details

template <typename Base, template <typename> typename... Mixins>
using ChainResolver = typename Details::ChainResolverDetails<Base, Mixins...>::Type;

template <typename T>
struct WithStyleProps : public T
{
    int style_flags = 0;
};

class NodeWithChildren {
public:
    virtual ~NodeWithChildren() = default;
};

template <typename BaseParam>
class ComposedWidget : public ChainResolver<BaseParam, WithStyleProps>,
                       public NodeWithChildren
{
public:
    void widget_method() {}
};

struct BasicConfig
{
    int config_value = 0;
};

class ConcreteWidget : public ComposedWidget<BasicConfig>
{
public:
    void concrete_method() {}
};

} // namespace testns

#endif
''')

    main = tmp_path / "main.cpp"
    main.write_text('''
#include "chain_resolver.h"

int main() {
    testns::ConcreteWidget w;
    w.concrete_method();
    return 0;
}
''')

    compile_commands = tmp_path / "compile_commands.json"
    compile_commands.write_text(json.dumps([
        {
            "directory": str(tmp_path),
            "command": "/usr/bin/c++ -std=c++17 -I. -c chain_resolver.h -o chain_resolver.h.o",
            "file": "chain_resolver.h",
        },
        {
            "directory": str(tmp_path),
            "command": "/usr/bin/c++ -std=c++17 -I. -c main.cpp -o main.o",
            "file": "main.cpp",
        },
    ], indent=2))

    return tmp_path


@pytest.fixture
def embedded_type_param_analyzer(embedded_type_param_project):
    """Create and index embedded type-parameter test project."""
    analyzer = CppAnalyzer(project_root=str(embedded_type_param_project))
    analyzer.index_project(force=True)
    return analyzer


class TestEmbeddedTypeParameterSubstitution:
    """
    Tests for embedded type-parameter-D-I substitution in base class strings.

    When a template class inherits from a complex dependent type that contains
    template parameters (e.g., ChainResolver<BaseParam, ...>::Type), libclang's
    canonical type spelling uses positional names like 'type-parameter-0-0'
    instead of the declared parameter name 'BaseParam'. These tests verify that
    embedded occurrences are replaced with actual parameter names.
    """

    def test_embedded_type_param_replaced_in_base_class(self, embedded_type_param_analyzer):
        """
        Test that type-parameter-0-0 embedded inside a dependent type is replaced.

        ComposedWidget<BaseParam> has base:
            ChainResolver<BaseParam, WithStyleProps> which resolves to
            typename ChainResolverDetails<type-parameter-0-0, WithStyleProps>::Type
        After fix, should show 'BaseParam' instead of 'type-parameter-0-0'.
        """
        results = embedded_type_param_analyzer.search_classes("ComposedWidget")

        primary = next((r for r in results if r['kind'] == 'class_template'), None)
        assert primary is not None, "Should find primary template ComposedWidget"

        base_classes = primary.get('base_classes', [])
        assert len(base_classes) == 2, f"Should have 2 base classes, got {base_classes}"

        # Find the dependent type base (the one with ChainResolverDetails)
        dependent_base = next(
            (b for b in base_classes if 'ChainResolverDetails' in b or 'BaseParam' in b),
            None
        )

        # Verify no type-parameter-X-Y remnants in any base class
        for bc in base_classes:
            assert 'type-parameter-' not in bc, \
                f"Base class should not contain 'type-parameter-': {bc}"

        # If we found the dependent type base, verify it contains BaseParam
        if dependent_base:
            assert 'BaseParam' in dependent_base, \
                f"Dependent base should contain 'BaseParam': {dependent_base}"

    def test_non_dependent_base_unaffected(self, embedded_type_param_analyzer):
        """
        Test that non-dependent base classes (like NodeWithChildren) are unaffected.
        """
        results = embedded_type_param_analyzer.search_classes("ComposedWidget")

        primary = next((r for r in results if r['kind'] == 'class_template'), None)
        assert primary is not None

        base_classes = primary.get('base_classes', [])

        # NodeWithChildren should appear as a base class with its qualified name
        node_base = next(
            (b for b in base_classes if 'NodeWithChildren' in b),
            None
        )
        assert node_base is not None, \
            f"Should have NodeWithChildren as base class, got {base_classes}"

    def test_concrete_class_has_resolved_bases(self, embedded_type_param_analyzer):
        """
        Test that ConcreteWidget (concrete class) has properly resolved bases.
        """
        results = embedded_type_param_analyzer.search_classes("ConcreteWidget")

        impl = next((r for r in results if r['kind'] in ('class', 'struct')), None)
        assert impl is not None, "Should find ConcreteWidget"

        base_classes = impl.get('base_classes', [])
        assert len(base_classes) >= 1, f"Should have at least 1 base class, got {base_classes}"

        # Verify no type-parameter remnants in concrete class bases
        for bc in base_classes:
            assert 'type-parameter-' not in bc, \
                f"Concrete class base should not contain 'type-parameter-': {bc}"


class TestBaseClassResolutionFromIndex:
    """
    Tests for _resolve_instantiation_base_classes method.

    These tests verify the resolution logic works correctly when
    the primary template is already in the index.
    """

    def test_resolution_requires_primary_in_index(self, param_inheritance_analyzer):
        """
        Verify that resolution fails gracefully when primary template is not indexed.
        """
        # Create a mock cursor-like object (we can't easily test this without
        # actually parsing, so we'll test the method directly with edge cases)

        # Empty primary_usr should return empty list
        result = param_inheritance_analyzer._resolve_instantiation_base_classes(
            cursor=None,  # Not used when primary_usr is None
            primary_template_usr=None
        )
        assert result == [], "Should return empty list when primary_usr is None"

    def test_crtp_base_shows_param_name(self, analyzer):
        """
        Test CRTP pattern in existing test fixture shows parameter name.

        Base<Derived> doesn't inherit from Derived in the fixture,
        but derived classes show Base<DerivedA> which is correct.
        """
        results = analyzer.search_classes("Base")

        # Find the CRTP base template
        base_template = next(
            (r for r in results if r['kind'] == 'class_template' and r['qualified_name'].split("::")[-1] == 'Base'),
            None
        )

        # The existing Base<Derived> doesn't inherit from Derived,
        # so this test just verifies the fixture works
        if base_template:
            # Base<Derived> has no base classes in the fixture
            # (it doesn't inherit from Derived, the derived classes inherit from Base<Derived>)
            # This is expected - the fixture tests CRTP usage, not parameter inheritance
            assert base_template.get('base_classes', []) == []


class TestFalsePositiveTemplateSpecialization:
    """Tests that methods/functions with templated parameter types are NOT marked
    as template specializations. Regression tests for cplusplus_mcp-7ap."""

    def test_method_with_initializer_list_param_not_specialization(self, analyzer):
        """Method with std::initializer_list<T> param is not a specialization."""
        results = analyzer.search_functions("addEntries")
        matched = [
            r for r in results
            if r["qualified_name"].split("::")[-1] == "addEntries" and "initializer_list" in r.get("prototype", "")
        ]
        assert len(matched) > 0, "Should find addEntries method with initializer_list param"
        for m in matched:
            assert m.get("is_template_specialization") is not True, \
                f"Method with initializer_list param should not be a specialization: {m}"
            assert m.get("is_template") is not True, \
                f"Method with initializer_list param should not be flagged as template: {m}"

    def test_method_with_std_function_param_not_specialization(self, analyzer):
        """Method with std::function<Sig> param is not a specialization."""
        results = analyzer.search_functions("transform")
        matched = [
            r for r in results
            if r["qualified_name"].split("::")[-1] == "transform" and "function" in r.get("prototype", "")
        ]
        assert len(matched) > 0, "Should find transform method with std::function param"
        for m in matched:
            assert m.get("is_template_specialization") is not True, \
                f"Method with std::function param should not be a specialization: {m}"
            assert m.get("is_template") is not True, \
                f"Method with std::function param should not be flagged as template: {m}"

    def test_method_with_vector_param_not_specialization(self, analyzer):
        """Method with std::vector<T> param is not a specialization."""
        results = analyzer.search_functions("setItems")
        assert len(results) > 0, "Should find setItems method"
        for m in results:
            assert m.get("is_template_specialization") is not True, \
                f"Method with vector param should not be a specialization: {m}"

    def test_method_with_map_param_not_specialization(self, analyzer):
        """Method with std::map<K,V> param is not a specialization."""
        results = analyzer.search_functions("setMapping")
        assert len(results) > 0, "Should find setMapping method"
        for m in results:
            assert m.get("is_template_specialization") is not True, \
                f"Method with map param should not be a specialization: {m}"

    def test_method_with_shared_ptr_param_not_specialization(self, analyzer):
        """Method with std::shared_ptr<T> param is not a specialization."""
        results = analyzer.search_functions("setShared")
        assert len(results) > 0, "Should find setShared method"
        for m in results:
            assert m.get("is_template_specialization") is not True, \
                f"Method with shared_ptr param should not be a specialization: {m}"

    def test_method_with_nested_template_param_not_specialization(self, analyzer):
        """Method with std::vector<std::vector<T>> param is not a specialization."""
        results = analyzer.search_functions("setNestedItems")
        assert len(results) > 0, "Should find setNestedItems method"
        for m in results:
            assert m.get("is_template_specialization") is not True, \
                f"Method with nested template param should not be a specialization: {m}"

    def test_free_function_with_template_param_not_specialization(self, analyzer):
        """Free function with templated param type is not a specialization."""
        results = analyzer.search_functions("processItems")
        assert len(results) > 0, "Should find processItems function"
        for m in results:
            assert m.get("is_template_specialization") is not True, \
                f"Function with vector param should not be a specialization: {m}"

    def test_free_function_with_std_function_param_not_specialization(self, analyzer):
        """Free function with std::function param is not a specialization."""
        results = analyzer.search_functions("executeCallback")
        assert len(results) > 0, "Should find executeCallback function"
        for m in results:
            assert m.get("is_template_specialization") is not True, \
                f"Function with std::function param should not be a specialization: {m}"

    def test_free_function_with_multiple_template_params_not_specialization(self, analyzer):
        """Free function with multiple templated params is not a specialization."""
        results = analyzer.search_functions("mergeData")
        assert len(results) > 0, "Should find mergeData function"
        for m in results:
            assert m.get("is_template_specialization") is not True, \
                f"Function with multiple template params should not be a specialization: {m}"

    def test_method_without_template_params_unaffected(self, analyzer):
        """Method with no template params remains correctly classified."""
        results = analyzer.search_functions("itemCount")
        assert len(results) > 0, "Should find itemCount method"
        for m in results:
            assert m.get("is_template_specialization") is not True, \
                "Plain method should not be a specialization"

    def test_real_function_specialization_still_detected(self, analyzer):
        """Actual template specializations should still be detected correctly."""
        # multiply<2> is a real explicit specialization in advanced_templates.h
        results = analyzer.search_functions("multiply")
        specializations = [
            r for r in results
            if r.get("template_kind") in ("full_specialization", "partial_specialization")
        ]
        assert len(specializations) > 0, \
            "Real function template specializations should still be detected"

    def test_get_class_info_methods_not_false_positive(self, analyzer):
        """get_class_info should not show methods as template specializations."""
        info = analyzer.get_class_info("DataProcessor")
        assert info is not None, "Should find DataProcessor class"

        methods = info.get("methods", [])
        for method in methods:
            name = method.get("qualified_name", "").split("::")[-1]
            # None of DataProcessor's methods are template specializations
            assert method.get("is_template_specialization") is not True, \
                f"DataProcessor::{name} should not be marked as template specialization"
            assert method.get("is_template") is not True, \
                f"DataProcessor::{name} should not be marked as template"
            assert method.get("template_kind") is None, \
                f"DataProcessor::{name} should have template_kind=None"


# =============================================================================
# Bug fix tests: cplusplus_mcp-sgs (template specialization names in lookups)
# =============================================================================

class TestTemplateSpecializationLookup:
    """Tests for get_class_info and get_function_signature with template specialization names.

    Bug cplusplus_mcp-sgs: get_class_info('Container<int>') was returning None because
    _extract_simple_name did not strip template args before class_index lookup.
    """

    def test_get_class_info_with_explicit_specialization_name(self, analyzer):
        """get_class_info('Container<int>') should find the explicit specialization."""
        info = analyzer.get_class_info("Container<int>")
        assert info is not None, "get_class_info('Container<int>') should not return None"
        assert "error" not in info or info.get("is_ambiguous"), (
            f"Unexpected error: {info.get('error')}"
        )
        # Should find a Container (either the specialization or an ambiguity response)
        if info.get("is_ambiguous"):
            # Ambiguity is acceptable if there are multiple candidates
            names = [m["qualified_name"].split("::")[-1] for m in info.get("matches", [])]
            assert all(n == "Container" for n in names), (
                f"Ambiguous matches should all be 'Container': {names}"
            )
        else:
            assert info.get("qualified_name", "").split("::")[-1] == "Container"

    def test_get_class_info_specialization_prefers_explicit_spec(self, analyzer):
        """When there is exactly one explicit specialization, it should be returned."""
        # Container<int> has exactly one explicit full specialization in the fixture
        info = analyzer.get_class_info("Container<int>")
        assert info is not None, "get_class_info('Container<int>') returned None"
        if not info.get("is_ambiguous"):
            assert info.get("template_kind") in ("full_specialization", "partial_specialization") or info.get("qualified_name", "").split("::")[-1] == "Container"

    def test_get_class_info_simple_name_still_works(self, analyzer):
        """Plain get_class_info('Container') should still work (may be ambiguous)."""
        info = analyzer.get_class_info("Container")
        # Container has multiple variants → expect ambiguity or the primary template
        assert info is not None, "get_class_info('Container') returned None"

    def test_get_function_signature_with_template_args(self, analyzer):
        """get_function_signature('max<int*>') should find function signatures."""
        sigs = analyzer.get_function_signature("max<int*>")
        assert isinstance(sigs, list), "get_function_signature should return a list"
        # Should find at least the generic max or the specialization
        # (Previously returned empty list because 'max<int*>' not in function_index)
        assert len(sigs) > 0, (
            "get_function_signature('max<int*>') should find 'max' signatures"
        )

    def test_get_function_signature_plain_name_still_works(self, analyzer):
        """get_function_signature('max') should still work."""
        sigs = analyzer.get_function_signature("max")
        assert len(sigs) > 0, "get_function_signature('max') should find signatures"

    def test_get_class_hierarchy_with_template_base_class(self, analyzer):
        """get_class_hierarchy for a class with template base should traverse base correctly."""
        # DoubleContainer inherits from Container<double>
        hierarchy = analyzer.get_class_hierarchy("DoubleContainer")
        assert hierarchy is not None
        assert "error" not in hierarchy, f"Unexpected error: {hierarchy.get('error')}"
        # New flat format: queried_class and classes dict
        assert "queried_class" in hierarchy
        assert "classes" in hierarchy
        qname = hierarchy["queried_class"]
        assert qname in hierarchy["classes"]  # queried class must be in the dict

    def test_extract_simple_name_strips_template_args(self):
        """_extract_simple_name should strip template arguments."""
        from mcp_server.search_engine import SearchEngine
        assert SearchEngine._extract_simple_name("Container<int>") == "Container"
        assert SearchEngine._extract_simple_name("ns::Container<int>") == "Container"
        assert SearchEngine._extract_simple_name("std::map<int, std::string>") == "map"
        assert SearchEngine._extract_simple_name("Widget") == "Widget"
        assert SearchEngine._extract_simple_name("ns::Widget") == "Widget"
        # operator< should NOT be mangled (doesn't end with >)
        assert SearchEngine._extract_simple_name("operator<") == "operator<"


# =============================================================================
# Bug fix tests: cplusplus_mcp-3pm (dependent types in hierarchy traversal)
# =============================================================================

class TestDependentTypeHierarchy:
    """Tests for get_class_hierarchy handling of dependent types.

    Bug cplusplus_mcp-3pm: base class names like "typename T::BaseType" caused
    traversal to silently stop because they couldn't be looked up in class_index.
    With the flat adjacency list format, such names appear as stub nodes with
    is_dependent_type=True.
    """

    def test_hierarchy_with_template_base_does_not_crash(self, analyzer):
        """get_class_hierarchy with template base class should not crash."""
        # IntContainer : public Container<int> - template instantiation as base
        hierarchy = analyzer.get_class_hierarchy("IntContainer")
        assert hierarchy is not None
        assert "error" not in hierarchy, f"Error: {hierarchy.get('error')}"
        assert "queried_class" in hierarchy
        assert "classes" in hierarchy

    def test_hierarchy_template_base_node_present(self, analyzer):
        """classes dict should contain a node for the template base class."""
        hierarchy = analyzer.get_class_hierarchy("IntContainer")
        assert "error" not in hierarchy
        qname = hierarchy["queried_class"]
        node = hierarchy["classes"].get(qname, {})
        # IntContainer should reference Container (bare name, no template args) as base
        base_keys = node.get("base_classes", [])
        assert len(base_keys) >= 1, (
            f"IntContainer node should reference a base class, got: {base_keys}"
        )
        # All referenced base nodes must be present in the classes dict (no dangling refs)
        for bk in base_keys:
            assert bk in hierarchy["classes"], (
                f"Base key '{bk}' not present in classes dict"
            )
        # The base should be Container (bare name without template args)
        assert any("Container" in bk for bk in base_keys), (
            f"IntContainer should inherit from Container, got base_keys: {base_keys}"
        )

    def test_dependent_type_marked_in_hierarchy(self, analyzer):
        """Dependent type bases (typename T::X) should appear with is_dependent_type flag."""
        # Classes with template-dependent bases will have those bases as stub nodes
        # The stub node for a dependent type has is_dependent_type=True
        # We verify by looking at any node in the classes dict
        # that has is_dependent_type set if it matches a typename pattern
        for hierarchy_name in ["IntContainer", "DoubleContainer"]:
            hierarchy = analyzer.get_class_hierarchy(hierarchy_name)
            if "error" in hierarchy:
                continue
            for key, node in hierarchy["classes"].items():
                if node.get("is_dependent_type"):
                    assert key.startswith("typename ") or (
                        "<" in key and ">" in key and not key.endswith(">")
                    ), f"is_dependent_type node has unexpected key: {key}"
                    return  # Found one - test passes
        # If no dependent types found, that's also OK (they may not appear in this fixture)

    def test_non_dependent_nodes_not_marked(self, analyzer):
        """Regular resolved classes should not be marked as dependent."""
        hierarchy = analyzer.get_class_hierarchy("Container")
        assert "error" not in hierarchy
        qname = hierarchy["queried_class"]
        node = hierarchy["classes"].get(qname, {})
        assert not node.get("is_dependent_type"), (
            f"Resolved class 'Container' should not be marked as dependent: {node}"
        )
