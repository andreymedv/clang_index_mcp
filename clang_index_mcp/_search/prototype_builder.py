"""Prototype and attribute construction from SymbolInfo objects.

This module isolates the presentation-layer logic that turns raw SymbolInfo
data into LLM-friendly prototype strings and attribute lists.  It has no
dependencies on indexes or locks, so it is easy to test in isolation.
"""

import json
from typing import List, Optional

from .._symbols.model import SymbolInfo


def build_function_prototype(info: SymbolInfo) -> Optional[str]:
    """Build a C++ prototype string for a function/method.

    Produces: "[access] [virtual|static] <signature with qualified name> [= 0]"
    Examples:
        "public virtual void app::Handler::processData(int, std::string) const = 0"
        "public static void app::Util::create()"
        "void globalFunc(int x)"

    Access modifier is only included for class members (info.parent_class is set).
    Returns None if info.signature is empty.
    """
    if not info.signature:
        return None

    prefix_parts = []

    # Access modifier only for class members
    if info.parent_class and info.access:
        prefix_parts.append(info.access)

    # Virtual/static qualifiers (mutually exclusive in valid C++)
    if info.is_pure_virtual or info.is_virtual:
        prefix_parts.append("virtual")
    elif info.is_static:
        prefix_parts.append("static")

    # Substitute qualified name into signature (replaces simple name)
    # info.signature uses simple name, e.g. "void processData(int x) const"
    # Result: "void app::Handler::processData(int x) const"
    sig = info.signature
    if info.qualified_name and info.name and info.qualified_name != info.name:
        target = info.name + "("
        idx = sig.find(target)
        if idx >= 0:
            sig = sig[:idx] + info.qualified_name + "(" + sig[idx + len(target) :]

    # Append "= 0" for pure virtual
    if info.is_pure_virtual and "= 0" not in sig:
        sig = sig.rstrip() + " = 0"

    if prefix_parts:
        return " ".join(prefix_parts) + " " + sig
    return sig


def build_class_prototype(info: SymbolInfo) -> Optional[str]:
    """Build a C++ class declaration prototype from SymbolInfo.

    Produces: "[template<...>] class|struct qualified_name[ : Base1, Base2, ...]"
    Examples:
        "class app::Widget : BaseWidget, Serializable"
        "template<typename T> class Container : Allocator<T>"
        "struct Point"

    Returns None if qualified_name is empty.
    """
    qname = info.qualified_name or info.name
    if not qname:
        return None

    # Template prefix for class templates and partial specializations
    template_prefix = ""
    if info.template_kind and info.template_parameters:
        try:
            params = json.loads(info.template_parameters)
            param_strs = []
            for p in params:
                kind = p.get("kind", "type")
                name = p.get("name", "")
                if kind == "type" or not kind:
                    param_strs.append(f"typename {name}" if name else "typename")
                else:
                    # Non-type parameter: use name directly
                    param_strs.append(name if name else "auto")
            if param_strs:
                template_prefix = "template<" + ", ".join(param_strs) + "> "
        except (json.JSONDecodeError, TypeError):
            pass

    # Keyword: "struct" for structs, "class" for everything else
    kind_str = "struct" if info.kind == "struct" else "class"

    # Base classes (no access specifiers since we don't store them per-base)
    bases_str = ""
    if info.base_classes:
        bases_str = " : " + ", ".join(info.base_classes)

    return f"{template_prefix}{kind_str} {qname}{bases_str}"


def build_attributes(info: SymbolInfo) -> Optional[List[str]]:
    """Build attributes list from boolean method/function flags.

    Replaces is_virtual, is_pure_virtual, is_const, is_static, is_definition
    with a compact list of applicable attribute names.
    pure_virtual implies virtual, so only 'pure_virtual' is listed (not both).
    Returns None when no attributes apply (omitted by omit_empty).
    """
    attrs = []
    if info.is_pure_virtual:
        attrs.append("pure_virtual")
    elif info.is_virtual:
        attrs.append("virtual")
    if info.is_const:
        attrs.append("const")
    if info.is_static:
        attrs.append("static")
    if info.is_definition:
        attrs.append("definition")
    return attrs if attrs else None
