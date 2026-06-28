"""Tests for TemplateResolver template argument resolution."""

import pytest
from clang_index_mcp._compilation.template_resolver import TemplateResolver


class TestExtractArgsFromDisplayname:
    """Test extract_args_from_displayname."""

    def test_simple_template(self):
        result = TemplateResolver.extract_args_from_displayname("MyTemplate<Arg1, Arg2>")
        assert result == ["Arg1", "Arg2"]

    def test_no_template(self):
        result = TemplateResolver.extract_args_from_displayname("PlainClass")
        assert result == []

    def test_nested_template(self):
        result = TemplateResolver.extract_args_from_displayname("Outer<Inner<T1, T2>, Arg3>")
        assert result == ["Inner<T1, T2>", "Arg3"]

    def test_single_arg(self):
        result = TemplateResolver.extract_args_from_displayname("Vec<int>")
        assert result == ["int"]

    def test_empty_args(self):
        result = TemplateResolver.extract_args_from_displayname("Template<>")
        assert result == []

    def test_complex_types(self):
        result = TemplateResolver.extract_args_from_displayname(
            "Map<std::string, std::vector<int>>"
        )
        assert result == ["std::string", "std::vector<int>"]

    def test_malformed_angles(self):
        result = TemplateResolver.extract_args_from_displayname("Class><")
        assert result == []

    def test_with_spaces(self):
        result = TemplateResolver.extract_args_from_displayname("Template< Arg1 , Arg2 >")
        assert result == ["Arg1", "Arg2"]


class TestBuildParamMapping:
    """Test build_param_mapping."""

    def test_basic_mapping(self):
        params = [{"name": "T"}, {"name": "N"}]
        args = ["int", "10"]
        result = TemplateResolver.build_param_mapping(params, args)
        assert result == {"T": "int", "N": "10"}

    def test_fewer_args_than_params(self):
        params = [{"name": "T"}, {"name": "N"}]
        args = ["int"]
        result = TemplateResolver.build_param_mapping(params, args)
        assert result == {"T": "int"}

    def test_empty_params(self):
        result = TemplateResolver.build_param_mapping([], ["int"])
        assert result == {}

    def test_empty_args(self):
        result = TemplateResolver.build_param_mapping([{"name": "T"}], [])
        assert result == {}

    def test_param_without_name(self):
        params = [{"kind": "type"}, {"name": "T"}]
        args = ["int", "float"]
        result = TemplateResolver.build_param_mapping(params, args)
        assert result == {"T": "float"}

    def test_complex_types_mapping(self):
        params = [{"name": "T"}, {"name": "Allocator"}]
        args = ["std::string", "std::allocator<std::string>"]
        result = TemplateResolver.build_param_mapping(params, args)
        assert result == {
            "T": "std::string",
            "Allocator": "std::allocator<std::string>",
        }


class TestSubstituteInBases:
    """Test substitute_in_bases."""

    def test_named_param_substitution(self):
        bases = ["T", "BaseClass"]
        param_to_arg = {"T": "int"}
        result = TemplateResolver.substitute_in_bases(bases, param_to_arg, ["int"])
        assert result == ["int", "BaseClass"]

    def test_indexed_param_substitution(self):
        bases = ["type-parameter-0-0", "BaseClass"]
        result = TemplateResolver.substitute_in_bases(bases, {}, ["int", "float"])
        assert result == ["int", "BaseClass"]

    def test_no_substitution_needed(self):
        bases = ["BaseClass1", "BaseClass2"]
        result = TemplateResolver.substitute_in_bases(bases, {}, [])
        assert result == ["BaseClass1", "BaseClass2"]

    def test_mixed_named_and_indexed(self):
        bases = ["T", "type-parameter-0-1", "FixedBase"]
        param_to_arg = {"T": "int"}
        result = TemplateResolver.substitute_in_bases(bases, param_to_arg, ["int", "float"])
        assert result == ["int", "float", "FixedBase"]

    def test_multiple_substitutions(self):
        bases = ["T", "U", "Base"]
        param_to_arg = {"T": "int", "U": "float"}
        result = TemplateResolver.substitute_in_bases(bases, param_to_arg, ["int", "float"])
        assert result == ["int", "float", "Base"]

    def test_out_of_range_index(self):
        bases = ["type-parameter-0-5"]
        result = TemplateResolver.substitute_in_bases(bases, {}, ["int"])
        assert result == ["type-parameter-0-5"]

    def test_empty_bases(self):
        result = TemplateResolver.substitute_in_bases([], {"T": "int"}, ["int"])
        assert result == []

    def test_all_resolved(self):
        bases = ["T", "U"]
        param_to_arg = {"T": "int", "U": "double"}
        result = TemplateResolver.substitute_in_bases(bases, param_to_arg, ["int", "double"])
        assert result == ["int", "double"]

    def test_template_in_base_name(self):
        bases = ["Base<T>"]
        param_to_arg = {"T": "int"}
        result = TemplateResolver.substitute_in_bases(bases, param_to_arg, ["int"])
        # Note: This doesn't do recursive substitution, just direct match
        assert result == ["Base<T>"]
