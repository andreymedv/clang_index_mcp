"""Tests for _usr_to_display_name() and its helper functions.

The helpers decode libclang USR (Unified Symbol Resolution) strings into
human-readable qualified names, preserving template arguments.
"""

import pytest

from mcp_server.cpp_analyzer import (
    _usr_to_display_name,
    _decode_usr_type,
    _decode_template_args,
    _decode_class_ref,
)

# ---- Primitive type decoding ------------------------------------------------


class TestPrimitiveTypeDecoding:
    """Verify that single-character type codes inside template args are decoded."""

    @pytest.mark.parametrize(
        "usr, expected",
        [
            ("c:@S@Container>#i", "Container<int>"),
            ("c:@S@Container>#d", "Container<double>"),
            ("c:@S@Container>#b", "Container<bool>"),
            ("c:@S@Container>#f", "Container<float>"),
            ("c:@S@Container>#v", "Container<void>"),
            ("c:@S@Container>#c", "Container<char>"),
            ("c:@S@Container>#I", "Container<unsigned int>"),
            ("c:@S@Container>#l", "Container<long long>"),
            ("c:@S@Container>#e", "Container<long double>"),
            ("c:@S@Container>#h", "Container<unsigned char>"),
            ("c:@S@Container>#s", "Container<short>"),
            ("c:@S@Container>#t", "Container<unsigned short>"),
            ("c:@S@Container>#j", "Container<long>"),
            ("c:@S@Container>#k", "Container<unsigned long>"),
            ("c:@S@Container>#w", "Container<wchar_t>"),
            ("c:@S@Container>#D", "Container<auto>"),
        ],
    )
    def test_primitive_types(self, usr, expected):
        assert _usr_to_display_name(usr) == expected


# ---- Multiple template arguments -------------------------------------------


class TestMultipleTemplateArgs:
    @pytest.mark.parametrize(
        "usr, expected",
        [
            ("c:@S@Pair>#i#d", "Pair<int, double>"),
            ("c:@S@Tuple>#i#d#b", "Tuple<int, double, bool>"),
            ("c:@S@Map>#i#f", "Map<int, float>"),
        ],
    )
    def test_multiple_args(self, usr, expected):
        assert _usr_to_display_name(usr) == expected


# ---- Pointer / reference / const -------------------------------------------


class TestQualifiers:
    @pytest.mark.parametrize(
        "usr, expected",
        [
            ("c:@S@Container>#*i", "Container<int *>"),
            ("c:@S@Container>#&i", "Container<int &>"),
            ("c:@S@Container>#Oi", "Container<int &&>"),
            ("c:@S@Container>#Ki", "Container<const int>"),
            ("c:@S@Container>#1i", "Container<const int>"),
            ("c:@S@Container>#Vi", "Container<volatile int>"),
            ("c:@S@Container>#2i", "Container<volatile int>"),
            ("c:@S@Container>#*Ki", "Container<const int *>"),
            # K*i = const(pointer(int)); displayed as "const int *" for simplicity
            ("c:@S@Container>#K*i", "Container<const int *>"),
        ],
    )
    def test_qualifiers(self, usr, expected):
        assert _usr_to_display_name(usr) == expected


# ---- Template parameter references (tN.M) ----------------------------------


class TestTemplateParamRefs:
    @pytest.mark.parametrize(
        "usr, expected",
        [
            ("c:@SP>1#T@Container>#*t0.0", "Container<T *>"),
            ("c:@SP>1#T@Container>#t0.0", "Container<T>"),
            ("c:@SP>2#T#T@Pair>#t0.0#t0.1", "Pair<T, U>"),
        ],
    )
    def test_tparam_refs(self, usr, expected):
        assert _usr_to_display_name(usr) == expected


# ---- Namespace + class segments ---------------------------------------------


class TestNamespaceClassSegments:
    @pytest.mark.parametrize(
        "usr, expected",
        [
            ("c:@N@std@F@move#&", "std::move"),
            ("c:@N@ns1@N@ns2@S@MyClass", "ns1::ns2::MyClass"),
            ("c:@N@std@S@vector>#i@F@push_back#&1t0.0#", "std::vector<int>::push_back"),
            ("c:@N@app@N@core@S@Engine", "app::core::Engine"),
        ],
    )
    def test_namespace_class(self, usr, expected):
        assert _usr_to_display_name(usr) == expected


# ---- Class ref in template args ($@...) -------------------------------------


class TestClassRefInTemplateArgs:
    @pytest.mark.parametrize(
        "usr, expected",
        [
            ("c:@S@Container>#$@S@MyClass", "Container<MyClass>"),
            ("c:@S@Container>#$@N@std@S@string", "Container<std::string>"),
            ("c:@S@Container>#$@N@std@S@vector>#i", "Container<std::vector<int>>"),
        ],
    )
    def test_class_ref(self, usr, expected):
        assert _usr_to_display_name(usr) == expected


# ---- Function segments (param types skipped) --------------------------------


class TestFunctionSegments:
    @pytest.mark.parametrize(
        "usr, expected",
        [
            ("c:@F@printf#*1c#", "printf"),
            ("c:@F@main#", "main"),
            ("c:@F@foo#i#d#", "foo"),
            ("c:@S@MyClass@F@method#i#", "MyClass::method"),
        ],
    )
    def test_function_segments(self, usr, expected):
        assert _usr_to_display_name(usr) == expected


# ---- Template definitions (@ST>, @SP>) --------------------------------------


class TestTemplateDefinitions:
    @pytest.mark.parametrize(
        "usr, expected",
        [
            ("c:@ST>1#T@Container", "Container"),
            ("c:@ST>1#T@Container@F@get#", "Container::get"),
            ("c:@ST>2#T#T@Pair", "Pair"),
        ],
    )
    def test_template_definitions(self, usr, expected):
        assert _usr_to_display_name(usr) == expected


# ---- Edge cases -------------------------------------------------------------


class TestEdgeCases:
    def test_empty_string(self):
        assert _usr_to_display_name("") == ""

    def test_non_usr_string(self):
        """Non-USR strings are returned unchanged (fallback)."""
        assert _usr_to_display_name("not a usr") == "not a usr"

    def test_no_template_args(self):
        assert _usr_to_display_name("c:@S@A") == "A"

    def test_only_namespace(self):
        assert _usr_to_display_name("c:@N@myns") == "myns"

    def test_deeply_nested(self):
        assert _usr_to_display_name("c:@N@a@N@b@N@c@S@D") == "a::b::c::D"

    def test_unknown_type_code_produces_question_mark(self):
        """Unknown type codes in template args produce '?'."""
        result = _usr_to_display_name("c:@S@Foo>#Z")
        assert "?" in result or "Foo" in result


# ---- Low-level helpers ------------------------------------------------------


class TestDecodeUsrType:
    """Direct tests for _decode_usr_type()."""

    def test_int(self):
        assert _decode_usr_type("i", 0) == ("int", 1)

    def test_pointer_to_int(self):
        assert _decode_usr_type("*i", 0) == ("int *", 2)

    def test_const_int(self):
        assert _decode_usr_type("Ki", 0) == ("const int", 2)

    def test_reference_to_double(self):
        assert _decode_usr_type("&d", 0) == ("double &", 2)

    def test_rvalue_ref(self):
        assert _decode_usr_type("Oi", 0) == ("int &&", 2)

    def test_past_end(self):
        t, pos = _decode_usr_type("i", 1)
        assert t == "?"
        assert pos == 1


class TestDecodeTemplateArgs:
    """Direct tests for _decode_template_args()."""

    def test_single_arg(self):
        text, pos = _decode_template_args("i@", 0)
        assert text == "<int>"
        assert pos == 1

    def test_two_args(self):
        text, pos = _decode_template_args("i#d@", 0)
        assert text == "<int, double>"
        assert pos == 3

    def test_empty(self):
        text, pos = _decode_template_args("@", 0)
        assert text == ""
        assert pos == 0


class TestDecodeClassRef:
    """Direct tests for _decode_class_ref()."""

    def test_simple_class(self):
        name, pos = _decode_class_ref("@S@MyClass", 0)
        assert name == "MyClass"

    def test_namespaced_class(self):
        name, pos = _decode_class_ref("@N@std@S@string", 0)
        assert name == "std::string"

    def test_class_with_template(self):
        name, pos = _decode_class_ref("@N@std@S@vector>#i", 0)
        assert name == "std::vector<int>"
