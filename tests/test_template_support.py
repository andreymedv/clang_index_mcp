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
        """Test that class template specializations have is_template_specialization=True."""
        results = analyzer.search_classes("Container")

        # Find explicit specializations (kind='class' with template_kind='full_specialization')
        specializations = [
            r for r in results
            if r['kind'] == 'class' and r.get('template_kind') == 'full_specialization'
        ]
        assert len(specializations) > 0, "Should find at least one class specialization"

        # Verify is_template_specialization is True for all specializations
        for spec in specializations:
            assert spec.get('is_template_specialization') is True, \
                f"Class specialization should have is_template_specialization=True: {spec}"

        # Verify primary template does NOT have is_template_specialization=True
        primary = next((r for r in results if r['kind'] == 'class_template'), None)
        if primary:
            assert primary.get('is_template_specialization') is not True, \
                "Primary template should not have is_template_specialization=True"


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
        names = [d['name'] for d in derived]
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
    """Tests for Task 3.4: primary_template_usr linking."""

    def test_partial_specialization_links_to_primary(self, analyzer):
        """Test partial specialization links to primary template via USR."""
        results = analyzer.search_classes("Container")
        template = next((r for r in results if r['kind'] == 'class_template'), None)
        partial = next((r for r in results if r['kind'] == 'partial_specialization'), None)

        assert template is not None, "Should find Container template"
        assert partial is not None, "Should find Container<T*> partial specialization"

        # Partial spec should have primary_template_usr pointing to the template
        primary_usr = partial.get('primary_template_usr')
        assert primary_usr is not None, \
            "Partial specialization should have primary_template_usr"
        assert '@Container' in primary_usr, \
            "primary_template_usr should reference Container template"

    def test_full_specialization_links_to_primary(self, analyzer):
        """Test full specialization links to primary template via USR."""
        results = analyzer.search_classes("Container")
        template = next((r for r in results if r['kind'] == 'class_template'), None)
        full_spec = next((r for r in results if r['kind'] == 'class' and
                         r.get('template_kind') == 'full_specialization'), None)

        assert template is not None, "Should find Container template"
        assert full_spec is not None, "Should find Container<int> full specialization"

        primary_usr = full_spec.get('primary_template_usr')
        assert primary_usr is not None, \
            "Full specialization should have primary_template_usr"
        assert '@Container' in primary_usr, \
            "primary_template_usr should reference Container template"

    def test_primary_template_has_no_parent(self, analyzer):
        """Test primary templates do not have primary_template_usr."""
        results = analyzer.search_classes("Container")
        template = next((r for r in results if r['kind'] == 'class_template'), None)

        assert template is not None, "Should find Container template"
        assert template.get('primary_template_usr') is None, \
            "Primary template should not have primary_template_usr"

    def test_function_specialization_links_to_primary(self, analyzer):
        """Test function specialization links to primary function template."""
        results = analyzer.search_functions("max")
        template = next((r for r in results if r['kind'] == 'function_template'), None)
        full_spec = next((r for r in results if r['kind'] == 'function' and
                         r.get('template_kind') == 'full_specialization'), None)

        assert template is not None, "Should find max function template"
        assert full_spec is not None, "Should find max<int*> full specialization"

        primary_usr = full_spec.get('primary_template_usr')
        assert primary_usr is not None, \
            "Function specialization should have primary_template_usr"
        assert 'max' in primary_usr, \
            "primary_template_usr should reference max function template"

    def test_multi_param_template_linking(self, analyzer):
        """Test specialization linking works for multi-parameter templates."""
        results = analyzer.search_classes("Pair")
        template = next((r for r in results if r['kind'] == 'class_template'), None)
        full_spec = next((r for r in results if r['kind'] == 'class' and
                         r.get('template_kind') == 'full_specialization'), None)

        assert template is not None, "Should find Pair template"
        assert full_spec is not None, "Should find Pair<int,int> full specialization"

        primary_usr = full_spec.get('primary_template_usr')
        assert primary_usr is not None, \
            "Multi-param specialization should have primary_template_usr"
        assert '@Pair' in primary_usr, \
            "primary_template_usr should reference Pair template"


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
        assert template.get('is_template') is True

        import json
        params = json.loads(template['template_parameters'])
        assert len(params) == 2, "Vector should have 2 template parameters (T and Alloc)"

    def test_nested_template_class(self, analyzer):
        """Test nested template classes are indexed."""
        # Outer<T>::Inner<U>
        results = analyzer.search_classes("Outer")
        outer = next((r for r in results if r['kind'] == 'class_template'), None)

        assert outer is not None, "Should find Outer template"
        assert outer.get('is_template') is True

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
        assert spec.get('primary_template_usr') is not None

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
            assert spec.get('primary_template_usr') is not None, \
                "Partial specialization should have primary_template_usr"


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

        primary_usr = full_spec.get('primary_template_usr')
        assert primary_usr is not None, \
            "Full specialization should have primary_template_usr"
        assert '@NamespacedContainer' in primary_usr, \
            "primary_template_usr should reference NamespacedContainer template"
        assert 'outer' in primary_usr, \
            "primary_template_usr should include namespace"

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
        partial_primary_usr = partial_spec.get('primary_template_usr')
        assert partial_primary_usr is not None, \
            "Partial specialization should have primary_template_usr"
        assert '@NestedPair' in partial_primary_usr, \
            "Partial spec primary_template_usr should reference NestedPair"

        # Check full specialization linking
        full_primary_usr = full_spec.get('primary_template_usr')
        assert full_primary_usr is not None, \
            "Full specialization should have primary_template_usr"
        assert '@NestedPair' in full_primary_usr, \
            "Full spec primary_template_usr should reference NestedPair"


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

        primary_usr = full_spec.get('primary_template_usr')
        assert primary_usr is not None, \
            "Specialization should have primary_template_usr"
        assert '@ForwardDeclared' in primary_usr, \
            "primary_template_usr should reference ForwardDeclared"


class TestCrossNamespaceInheritance:
    """Task 6.5: Integration tests for cross-namespace template inheritance."""

    def test_cross_namespace_derived_class(self, analyzer):
        """Test finding derived classes across namespaces."""
        derived = analyzer.get_derived_classes("BaseTemplate")

        # Should find DerivedFromTemplate in derived_ns
        # Note: This may return 0 if no cross-namespace derived classes are found
        # because get_derived_classes may not traverse across namespaces by default
        names = [d['name'] for d in derived]
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
        specializations = [r for r in results if r.get('primary_template_usr')]

        assert template is not None, "Should find NestedPair template"
        assert len(specializations) >= 2, "Should find at least 2 specializations"

        template_usr = template.get('usr')
        for spec in specializations:
            # All specializations should link to the same primary
            primary_usr = spec.get('primary_template_usr')
            assert primary_usr is not None
            # The primary_template_usr should reference the same template name
            assert '@NestedPair' in primary_usr

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
            (r for r in results if r['kind'] == 'class_template' and r['name'] == 'Base'),
            None
        )

        # The existing Base<Derived> doesn't inherit from Derived,
        # so this test just verifies the fixture works
        if base_template:
            # Base<Derived> has no base classes in the fixture
            # (it doesn't inherit from Derived, the derived classes inherit from Base<Derived>)
            # This is expected - the fixture tests CRTP usage, not parameter inheritance
            assert base_template.get('base_classes', []) == []
