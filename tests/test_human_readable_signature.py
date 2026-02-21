"""
Tests for human-readable function signature generation.

Tests the _build_human_readable_signature() method and its helpers
(_extract_params_from_type_spelling, _extract_trailing_qualifiers).
"""

import pytest
from unittest.mock import Mock

from mcp_server.cpp_analyzer import CppAnalyzer


class TestExtractParamsFromTypeSpelling:
    """Test the static helper that extracts params from C type notation."""

    def test_simple_params(self):
        assert CppAnalyzer._extract_params_from_type_spelling("void (int, double)") == "int, double"

    def test_no_params(self):
        assert CppAnalyzer._extract_params_from_type_spelling("void ()") == ""

    def test_single_param(self):
        assert (
            CppAnalyzer._extract_params_from_type_spelling("int (const char *)") == "const char *"
        )

    def test_reference_param(self):
        result = CppAnalyzer._extract_params_from_type_spelling("void (const std::string &)")
        assert result == "const std::string &"

    def test_function_pointer_param(self):
        """Nested parens from function pointer params should be handled."""
        result = CppAnalyzer._extract_params_from_type_spelling("void (void (*)(int), int)")
        assert result == "void (*)(int), int"

    def test_empty_string(self):
        assert CppAnalyzer._extract_params_from_type_spelling("") == ""

    def test_none_input(self):
        assert CppAnalyzer._extract_params_from_type_spelling(None) == ""

    def test_no_parens(self):
        assert CppAnalyzer._extract_params_from_type_spelling("int") == ""

    def test_template_params(self):
        """Template angle brackets in params should be preserved."""
        result = CppAnalyzer._extract_params_from_type_spelling(
            "void (std::map<int, int>, std::vector<std::string>)"
        )
        assert result == "std::map<int, int>, std::vector<std::string>"

    def test_const_method_type(self):
        """Const qualifier after closing paren should not be included in params."""
        result = CppAnalyzer._extract_params_from_type_spelling("void (int) const")
        assert result == "int"


class TestExtractTrailingQualifiers:
    """Test the static helper that extracts const/noexcept/etc. qualifiers."""

    def test_const_qualifier(self):
        result = CppAnalyzer._extract_trailing_qualifiers("void (int) const")
        assert result.strip() == "const"

    def test_no_qualifier(self):
        result = CppAnalyzer._extract_trailing_qualifiers("void (int)")
        assert result == ""

    def test_const_noexcept(self):
        result = CppAnalyzer._extract_trailing_qualifiers("void (int) const noexcept")
        assert "const" in result
        assert "noexcept" in result

    def test_empty_string(self):
        assert CppAnalyzer._extract_trailing_qualifiers("") == ""

    def test_none_input(self):
        assert CppAnalyzer._extract_trailing_qualifiers(None) == ""

    def test_nested_parens_only_checks_outermost(self):
        """Qualifier extraction should use the last top-level close paren."""
        result = CppAnalyzer._extract_trailing_qualifiers("void (void (*)(int)) const")
        assert result.strip() == "const"


class TestBuildHumanReadableSignature:
    """Test the full signature builder with mocked cursors."""

    @pytest.fixture
    def analyzer(self, tmp_path):
        """Create a CppAnalyzer for testing."""
        return CppAnalyzer(str(tmp_path))

    def _make_cursor(
        self,
        name="testFunc",
        type_spelling="void (int, double)",
        result_type_spelling="void",
        args=None,
    ):
        """Create a mock cursor with the given properties."""
        cursor = Mock()
        cursor.spelling = name
        cursor.type.spelling = type_spelling
        cursor.result_type.spelling = result_type_spelling

        if args is None:
            # Default: empty args (will fall back to type_spelling extraction)
            cursor.get_arguments = Mock(return_value=[])
        else:
            mock_args = []
            for arg_type, arg_name in args:
                arg = Mock()
                arg.type.spelling = arg_type
                arg.spelling = arg_name
                mock_args.append(arg)
            cursor.get_arguments = Mock(return_value=mock_args)

        return cursor

    def test_simple_function_with_named_params(self, analyzer):
        cursor = self._make_cursor(
            name="processData",
            type_spelling="void (int, const std::string &)",
            result_type_spelling="void",
            args=[("int", "x"), ("const std::string &", "y")],
        )
        result = analyzer._build_human_readable_signature(cursor)
        assert result == "void processData(int x, const std::string & y)"

    def test_zero_arg_function(self, analyzer):
        cursor = self._make_cursor(
            name="doSomething",
            type_spelling="void ()",
            result_type_spelling="void",
            args=[],
        )
        result = analyzer._build_human_readable_signature(cursor)
        assert result == "void doSomething()"

    def test_const_method(self, analyzer):
        cursor = self._make_cursor(
            name="getValue",
            type_spelling="int () const",
            result_type_spelling="int",
            args=[],
        )
        result = analyzer._build_human_readable_signature(cursor)
        assert result == "int getValue() const"

    def test_template_function_fallback(self, analyzer):
        """When get_arguments() returns empty for templates, fall back to type.spelling."""
        cursor = self._make_cursor(
            name="convert",
            type_spelling="void (int, double)",
            result_type_spelling="void",
            args=[],  # Templates often return empty args
        )
        result = analyzer._build_human_readable_signature(cursor)
        assert result == "void convert(int, double)"

    def test_function_pointer_param(self, analyzer):
        """Nested parens from function pointer params should be handled."""
        cursor = self._make_cursor(
            name="registerCallback",
            type_spelling="void (void (*)(int), int)",
            result_type_spelling="void",
            args=[("void (*)(int)", "callback"), ("int", "priority")],
        )
        result = analyzer._build_human_readable_signature(cursor)
        assert result == "void registerCallback(void (*)(int) callback, int priority)"

    def test_unnamed_params(self, analyzer):
        """Params without names should just show the type."""
        cursor = self._make_cursor(
            name="process",
            type_spelling="void (int, double)",
            result_type_spelling="void",
            args=[("int", ""), ("double", "")],
        )
        result = analyzer._build_human_readable_signature(cursor)
        assert result == "void process(int, double)"

    def test_no_cursor_type(self, analyzer):
        """Should return empty string if cursor.type is None."""
        cursor = Mock()
        cursor.spelling = "testFunc"
        cursor.type = None
        result = analyzer._build_human_readable_signature(cursor)
        assert result == ""

    def test_reference_and_pointer_params(self, analyzer):
        cursor = self._make_cursor(
            name="transfer",
            type_spelling="bool (int *, const std::string &)",
            result_type_spelling="bool",
            args=[("int *", "data"), ("const std::string &", "name")],
        )
        result = analyzer._build_human_readable_signature(cursor)
        assert result == "bool transfer(int * data, const std::string & name)"

    def test_no_return_type(self, analyzer):
        """Constructor-like: result_type might be empty."""
        cursor = self._make_cursor(
            name="MyClass",
            type_spelling="void (int)",
            result_type_spelling="",
            args=[("int", "value")],
        )
        # When result_type is empty string, we still get "void" prefix
        # because result_type_spelling returns "" which is falsy
        result = analyzer._build_human_readable_signature(cursor)
        assert result == "MyClass(int value)"

    def test_get_arguments_raises_exception(self, analyzer):
        """Should fall back to type.spelling extraction if get_arguments fails."""
        cursor = Mock()
        cursor.spelling = "testFunc"
        cursor.type.spelling = "void (int, double)"
        cursor.result_type.spelling = "void"
        cursor.get_arguments = Mock(side_effect=Exception("not available"))

        result = analyzer._build_human_readable_signature(cursor)
        assert result == "void testFunc(int, double)"


class TestHumanReadableSignatureIntegration:
    """Integration tests verifying end-to-end signature format with real libclang."""

    @pytest.fixture
    def project_dir(self, tmp_path):
        """Create a temporary project with C++ source files."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        (src_dir / "functions.cpp").write_text("""
void simpleFunction(int x, double y) {}

int noParams() { return 42; }

class MyClass {
public:
    void method(const char* msg) const {}
    static int staticMethod(int a, int b) { return a + b; }
    virtual void virtualMethod(int x) {}
};
""")
        return tmp_path

    def test_signatures_are_human_readable(self, project_dir):
        """Verify that prototype uses human-readable format."""
        analyzer = CppAnalyzer(str(project_dir))
        analyzer.index_project()

        # Check a simple function
        results = analyzer.search_functions("simpleFunction")
        assert len(results) > 0
        proto = results[0].get("prototype", "")
        # Should contain function name and param names
        assert "simpleFunction" in proto
        assert "int" in proto
        assert "double" in proto
        # Should NOT be the old C type notation like "void (int, double)"
        # The old format would not contain the function name
        assert proto != "void (int, double)"

    def test_zero_arg_function_signature(self, project_dir):
        """Verify zero-arg function has proper prototype."""
        analyzer = CppAnalyzer(str(project_dir))
        analyzer.index_project()

        results = analyzer.search_functions("noParams")
        assert len(results) > 0
        proto = results[0].get("prototype", "")
        assert "noParams" in proto
        assert "()" in proto

    def test_const_method_signature(self, project_dir):
        """Verify const qualifier is preserved in prototype."""
        analyzer = CppAnalyzer(str(project_dir))
        analyzer.index_project()

        results = analyzer.search_functions("method")
        # Find the one from MyClass
        my_results = [r for r in results if r.get("parent_class") == "MyClass"]
        if my_results:
            proto = my_results[0].get("prototype", "")
            assert "const" in proto

    def test_get_function_signature_tool_format(self, project_dir):
        """Verify get_function_signature returns human-readable format with class scope."""
        analyzer = CppAnalyzer(str(project_dir))
        analyzer.index_project()

        sigs = analyzer.get_function_signature("simpleFunction")
        assert len(sigs) > 0
        # Should be a complete human-readable signature
        sig = sigs[0]
        assert "simpleFunction" in sig
        assert "(" in sig

    def test_get_function_signature_with_class_scope(self, project_dir):
        """Verify class scope is injected into method signatures."""
        analyzer = CppAnalyzer(str(project_dir))
        analyzer.index_project()

        sigs = analyzer.get_function_signature("staticMethod", class_name="MyClass")
        if sigs:
            sig = sigs[0]
            assert "MyClass::" in sig
            assert "staticMethod" in sig
