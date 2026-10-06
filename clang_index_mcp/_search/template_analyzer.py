"""Template inheritance analysis helpers for the query engine.

Provides parsing and matching utilities for template parameters, specializations,
and indirect inheritance through template parameters (e.g. ``class Foo<T> : public T``).
"""

import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .._symbols.model import SymbolInfo, build_location_objects, omit_empty
from .._search.pattern_matcher import matches_qualified_pattern, normalize_template_whitespace
from .._search.symbol_name_utils import (
    extract_simple_name,
    is_dependent_type_name,
    is_specialization_key,
    split_specialization_key,
)


def check_template_param_inheritance(
    base_class: str,
    target_class: str,
    symbol_store,
    index_lock,
) -> bool:
    """
    Check if a class indirectly inherits from target_class through template
    parameter inheritance.

    Issue: cplusplus_mcp-hnj

    Example:
        If Template<T> inherits from T, and a class has base_class="Template<BaseClass>",
        then it indirectly inherits from BaseClass.

    Args:
        base_class: The base class string (e.g., "ns::Template<ns::BaseClass>")
        target_class: The class we're looking for (e.g., "ns::BaseClass" or "BaseClass")
        symbol_store: Source of indexed class symbols.
        index_lock: Lock guarding the symbol index.

    Returns:
        True if there's indirect inheritance through template parameters
    """
    # Quick check: if no template instantiation, no indirect inheritance possible
    if "<" not in base_class:
        return False

    # Parse the template instantiation
    # Format: "ns::Template<arg1, arg2, ...>" or "Template<arg>"
    bracket_pos = base_class.find("<")
    if bracket_pos == -1:
        return False

    template_name = base_class[:bracket_pos]
    args_str = base_class[bracket_pos + 1 : -1]  # Remove < and >

    # Find which parameter indices the template inherits from
    # Look up the template in class_index and check its base_classes for type-parameter-X-Y
    param_indices = get_template_param_inheritance_indices(template_name, symbol_store, index_lock)

    if not param_indices:
        return False

    # Parse template arguments (handle nested templates)
    template_args = parse_template_args(args_str)

    # Check if any of the inherited-from parameter positions match target_class
    for param_idx in param_indices:
        if param_idx < len(template_args):
            arg = template_args[param_idx]
            # Check if the argument matches target_class
            # Handle both qualified and simple names
            if arg == target_class:
                return True
            # Check if target_class is the simple name of arg
            if "::" in arg and arg.endswith("::" + target_class):
                return True
            # Check if arg is the simple name of target_class
            if "::" in target_class and target_class.endswith("::" + arg):
                return True
            # Check simple name match
            arg_simple = arg.split("::")[-1] if "::" in arg else arg
            target_simple = target_class.split("::")[-1] if "::" in target_class else target_class
            if arg_simple == target_simple:
                return True

    return False


def get_template_param_inheritance_indices(
    template_name: str, symbol_store, index_lock
) -> List[int]:
    """
    Get the template parameter indices that a template inherits from.

    Looks up the template in class_index and analyzes its base_classes
    to find which template parameters are used as base classes.

    Supports two formats:
    1. Parameter names (new format): base_classes = ['T', 'BaseType']
    2. Legacy format: base_classes = ['type-parameter-0-0'] (for backward compatibility)

    Args:
        template_name: The template name (e.g., "ns::TemplateInheritsParam")
        symbol_store: Source of indexed class symbols.
        index_lock: Lock guarding the symbol index.

    Returns:
        List of parameter indices that are used as base classes.
        E.g., [0] means the template inherits from its first parameter.
    """
    simple_name = template_name.split("::")[-1] if "::" in template_name else template_name

    param_indices = []
    with index_lock:
        infos = symbol_store.get_classes_by_name(simple_name)
        for info in infos:
            if info.kind != "class_template":
                continue
            if not template_info_matches_name(info, template_name):
                continue

            param_name_to_index = build_param_name_to_index(info.template_parameters)
            for base in info.base_classes:
                param_index = resolve_param_index(base, param_name_to_index)
                if param_index is not None and param_index not in param_indices:
                    param_indices.append(param_index)

    return param_indices


def template_info_matches_name(info: SymbolInfo, template_name: str) -> bool:
    """Check if a class info matches the requested template name."""
    if "::" not in template_name:
        return True
    info_qualified = info.qualified_name if info.qualified_name else info.name
    return matches_qualified_pattern(info_qualified, template_name)


def build_param_name_to_index(template_parameters: Optional[str]) -> Dict[str, int]:
    """Build a mapping from template parameter names to their indices."""
    param_name_to_index: Dict[str, int] = {}
    if not template_parameters:
        return param_name_to_index

    try:
        params = json.loads(template_parameters)
        for i, param in enumerate(params):
            param_name = param.get("name", "")
            if param_name:
                param_name_to_index[param_name] = i
    except (json.JSONDecodeError, TypeError):
        pass

    return param_name_to_index


def resolve_param_index(base: str, param_name_to_index: Dict[str, int]) -> Optional[int]:
    """Resolve a base class name to a template parameter index if applicable."""
    if base in param_name_to_index:
        return param_name_to_index[base]

    match = re.match(r"type-parameter-(\d+)-(\d+)", base)
    if match:
        return int(match.group(2))

    return None


def parse_template_args(args_str: str) -> List[str]:
    """
    Parse template arguments from a string like "A, B<C, D>, E".

    Handles nested templates by tracking bracket depth.

    Args:
        args_str: The string inside template brackets (without < and >)

    Returns:
        List of template argument strings
    """
    args = []
    current_arg = ""
    depth = 0

    for char in args_str:
        if char == "<":
            depth += 1
            current_arg += char
        elif char == ">":
            depth -= 1
            current_arg += char
        elif char == "," and depth == 0:
            args.append(current_arg.strip())
            current_arg = ""
        else:
            current_arg += char

    if current_arg.strip():
        args.append(current_arg.strip())

    return args


def get_template_patterns(simple_name: str, symbol_store, index_lock) -> List[str]:
    """Get template patterns for matching derived classes."""
    template_patterns: List[str] = []
    with index_lock:
        # Check if class_name exists in class_index (use simple_name for lookup)
        if symbol_store.has_class_name(simple_name):
            for symbol in symbol_store.get_classes_by_name(simple_name):
                # If any symbol is a template, get all specializations
                if symbol.kind in ("class_template", "partial_specialization"):
                    # Build patterns to match in base_classes
                    # Matches: "Container", "Container<int>", "Container<double>", etc.
                    # Use simple_name since base_classes matching uses suffix matching
                    template_patterns.append(simple_name)  # Exact match
                    template_patterns.append(f"{simple_name}<")  # Prefix match for specializations
                    break  # Only need to detect template once

        # If not a template, just use exact match (use simple_name for matching)
        if not template_patterns:
            template_patterns = [simple_name]
    return template_patterns


def check_pattern_match(base_class: str, template_patterns: List[str]) -> bool:
    """Check if base_class matches any of the template patterns."""
    for pattern in template_patterns:
        # Exact match or template specialization prefix match
        if base_class == pattern or base_class.startswith(pattern):
            return True
        # Handle qualified names: "ns::BaseClass" should match "BaseClass"
        # Check if base_class ends with "::pattern" or "::pattern<"
        if "::" in base_class:
            if base_class.endswith("::" + pattern):
                return True
            if base_class.split("::")[-1].startswith(pattern):
                return True
    return False


def is_derived_from(
    info: SymbolInfo,
    template_patterns: List[str],
    simple_name: str,
    symbol_store,
    index_lock,
) -> bool:
    """Check if a symbol inherits from the target class or any specialization."""
    tparam_names: Set[str] = set()
    if info.template_parameters:
        try:
            tparams = json.loads(info.template_parameters)
            tparam_names = {p.get("name", "") for p in tparams if p.get("name")}
        except (json.JSONDecodeError, TypeError):
            pass

    for base_class in info.base_classes:
        # Skip base classes that are template parameters
        if base_class in tparam_names:
            continue

        match_found = check_pattern_match(base_class, template_patterns)

        # Issue cplusplus_mcp-hnj: Check for indirect inheritance
        # through template parameters
        if not match_found:
            match_found = check_template_param_inheritance(
                base_class, simple_name, symbol_store, index_lock
            )

        if match_found:
            return True
    return False


def get_derived_classes(
    class_name: str,
    project_only: bool,
    symbol_store,
    index_lock,
) -> List[Dict[str, Any]]:
    """
    Get all classes that derive from the given class.

    Issue #99 Phase 3: Template-aware derived class queries
    If class_name is a template, finds classes derived from ANY specialization:
    - Container → finds classes derived from Container<T>, Container<int>, etc.
    - Enables CRTP pattern discovery

    Args:
        class_name: Name of the base class (can be template name)
        project_only: Only include project classes (exclude dependencies)
        symbol_store: Source of indexed class symbols.
        index_lock: Lock guarding the symbol index.

    Returns:
        List of classes that inherit from the given class or any specialization
    """
    derived_classes = []

    # Normalize class_name: extract simple name from qualified name
    simple_name = extract_simple_name(class_name)
    matcher = _make_derived_matcher(class_name, simple_name, symbol_store, index_lock)

    with index_lock:
        for name, infos in symbol_store.iter_class_items():
            for info in infos:
                if not project_only or info.is_project:
                    if matcher(info):
                        derived_classes.append(
                            omit_empty(
                                {
                                    "qualified_name": info.qualified_name or info.name,
                                    "kind": info.kind,
                                    "is_project": info.is_project,
                                    "base_classes": info.base_classes,
                                    **build_location_objects(info),
                                }
                            )
                        )

    return derived_classes


def _make_derived_matcher(class_name: str, simple_name: str, symbol_store, index_lock):
    """Build a predicate deciding whether a class derives from the target.

    Query names that carry template arguments (e.g. ``T<A1>``) match only the
    exact specialization key, so sibling instantiations (``T<A2>``) never mix
    in. Bare names keep the aggregation behavior and match any specialization.
    """
    if is_specialization_key(class_name):
        exact_key = resolve_class_key(class_name, symbol_store, index_lock)

        def match_exact(info: SymbolInfo) -> bool:
            return _inherits_exact_key(info, exact_key, symbol_store, index_lock)

        return match_exact

    template_patterns = get_template_patterns(simple_name, symbol_store, index_lock)

    def match_pattern(info: SymbolInfo) -> bool:
        return is_derived_from(info, template_patterns, simple_name, symbol_store, index_lock)

    return match_pattern


def _inherits_exact_key(info: SymbolInfo, exact_key: str, symbol_store, index_lock) -> bool:
    """Return True if any base of ``info`` resolves to the exact node key."""
    for base_class in info.base_classes:
        if resolve_class_key(base_class, symbol_store, index_lock) == exact_key:
            return True
    return False


# =============================================================================
# Specialization node keys (issue cplusplus_mcp-jqqq)
# =============================================================================


def parse_specialization_key(key: str) -> Optional[Tuple[str, List[str]]]:
    """Parse "ns::T<ns::A1, int>" into ("ns::T", ["ns::A1", "int"]).

    Returns None when the key is not a specialization key (handles nested
    template arguments via :func:`parse_template_args`).
    """
    parts = split_specialization_key(key)
    if parts is None:
        return None
    name_part, args_str = parts
    return name_part, parse_template_args(args_str)


def format_specialization_key(template_name: str, args: List[str]) -> str:
    """Build a canonical specialization key like "ns::T<ns::A1>"."""
    inner = ", ".join(a.strip() for a in args)
    return normalize_template_whitespace(f"{template_name}<{inner}>")


def resolve_class_key(raw: str, symbol_store, index_lock) -> str:
    """Resolve a raw class/base name to a canonical node key.

    Specialization names keep their template arguments (``T<A1>``); the
    template-name portion and each argument are resolved to qualified names so
    ``T<A1>`` and ``ns::T<ns::A1>`` converge on the same key. Dependent names
    (``typename T::Base``) pass through unchanged.
    """
    if is_dependent_type_name(raw):
        return raw
    parts = split_specialization_key(raw)
    if parts is None:
        return _resolve_plain_key(raw, symbol_store, index_lock)
    name_part, args_str = parts
    resolved_name = _resolve_plain_key(name_part, symbol_store, index_lock)
    args = [resolve_class_key(a, symbol_store, index_lock) for a in parse_template_args(args_str)]
    return format_specialization_key(resolved_name, args)


def _resolve_plain_key(lookup: str, symbol_store, index_lock) -> str:
    """Resolve a non-specialization name to its indexed qualified name."""
    is_qual = "::" in lookup
    simple = extract_simple_name(lookup)
    with index_lock:
        infos = symbol_store.get_classes_by_name(simple)
        for info in infos:
            if is_qual:
                info_qn = info.qualified_name if info.qualified_name else info.name
                if not matches_qualified_pattern(info_qn, lookup):
                    continue
            qn = info.qualified_name if info.qualified_name else info.name
            return str(qn)  # type: ignore[no-any-return]
    return lookup


def build_param_name_to_arg(
    template_parameters: Optional[str], template_args: List[str]
) -> Dict[str, str]:
    """Build a mapping from template parameter names to substitution arguments."""
    mapping: Dict[str, str] = {}
    for name, index in build_param_name_to_index(template_parameters).items():
        if index < len(template_args):
            mapping[name] = template_args[index]
    return mapping


def substitute_template_params(
    base_classes: List[str],
    template_parameters: Optional[str],
    template_args: List[str],
) -> List[str]:
    """Substitute template parameters inside base class names.

    Handles whole-base parameters (``P`` -> ``A1``), legacy indexed parameters
    (``type-parameter-0-0``) and parameters embedded in composite names
    (``T1<P>`` -> ``T1<A1>``).
    """
    param_to_arg = build_param_name_to_arg(template_parameters, template_args)
    return [_substitute_base(b, param_to_arg, template_args) for b in base_classes]


def _substitute_base(base: str, param_to_arg: Dict[str, str], template_args: List[str]) -> str:
    if base in param_to_arg:
        return param_to_arg[base]
    legacy = re.match(r"type-parameter-(\d+)-(\d+)$", base)
    if legacy:
        index = int(legacy.group(2))
        return template_args[index] if index < len(template_args) else base
    return re.sub(r"\b([A-Za-z_]\w*)\b", lambda m: param_to_arg.get(m.group(1), m.group(1)), base)


def _base_uses_template_params(base_classes: List[str], template_parameters: Optional[str]) -> bool:
    """Return True when any base class is (or embeds) a template parameter."""
    name_to_index = build_param_name_to_index(template_parameters)
    for base in base_classes:
        if resolve_param_index(base, name_to_index) is not None:
            return True
        for name in name_to_index:
            if re.search(rf"\b{re.escape(name)}\b", base):
                return True
    return False


# USR encoding of template arguments (observed libclang shapes):
#   c:@S@T>#$@S@A1        -> T<A1>       ($ + type USR without "c:" prefix)
#   c:@S@T>#I             -> T<int>      (builtin type code)
#   c:@S@T2>#$@S@A1#$@N@ns@S@NA -> T2<A1, ns::NA>
#   c:@S@TN>#$@S@TN>#I    -> T<TN<int>> (nested template-id)
_USR_BUILTIN_TYPE_CODES = {
    "I": "int",
    "d": "double",
    "b": "bool",
    "C": "char",
    "S": "short",
    "L": "long",
    "v": "void",
    "f": "float",
    "K": "long long",
    "i": "unsigned int",
    "l": "unsigned long",
    "W": "wchar_t",
    "q": "char16_t",
    "r": "signed char",
    "c": "unsigned char",
    "s": "unsigned short",
    "D": "long double",
}


def decode_usr_template_args(usr: Optional[str]) -> Optional[List[str]]:
    """Recover template argument strings from a specialization USR.

    Returns None when the USR shape is unrecognized (non-type arguments with
    complex encodings, function pointers, arrays, ...), so callers can fall
    back to base-class substitution matching.
    """
    if not usr or ">#" not in usr:
        return None
    args_part = usr.split(">", 1)[1]
    try:
        args, rest = _decode_usr_arg_list(args_part)
    except (ValueError, IndexError):
        return None
    if rest or not args:
        return None
    return args


def _decode_usr_arg_list(text: str) -> Tuple[List[str], str]:
    args: List[str] = []
    while text.startswith("#"):
        arg, text = _decode_usr_arg(text[1:])
        args.append(arg)
    return args, text


def _decode_usr_arg(text: str) -> Tuple[str, str]:
    if text.startswith("V"):
        _, text = _decode_usr_type(text[1:])
        return _decode_usr_literal(text)
    return _decode_usr_type(text)


def _decode_usr_literal(text: str) -> Tuple[str, str]:
    end = 1 if text.startswith("-") else 0
    while end < len(text) and text[end].isdigit():
        end += 1
    if end == (1 if text.startswith("-") else 0):
        raise ValueError("missing non-type argument literal")
    return text[:end], text[end:]


def _decode_usr_type(text: str) -> Tuple[str, str]:
    if text.startswith("$"):
        return _decode_usr_type_name(text[1:])
    if text.startswith(("*", "&", "1")):
        inner, rest = _decode_usr_type(text[1:])
        suffix = "" if text[0] == "1" else text[0]
        prefix = "const " if text[0] == "1" else ""
        return f"{prefix}{inner}{suffix}", rest
    if text[:1] in _USR_BUILTIN_TYPE_CODES:
        return _USR_BUILTIN_TYPE_CODES[text[0]], text[1:]
    raise ValueError(f"unrecognized USR type encoding: {text!r}")


def _decode_usr_type_name(text: str) -> Tuple[str, str]:
    parts: List[str] = []
    while text.startswith("@"):
        if len(text) < 3 or text[2] != "@":
            raise ValueError(f"malformed USR name element: {text!r}")
        end = 3
        while end < len(text) and text[end] not in "@>":
            end += 1
        if end == 3:
            raise ValueError(f"empty USR name element: {text!r}")
        parts.append(text[3:end])
        text = text[end:]
    if not parts:
        raise ValueError("missing USR name path")
    name = "::".join(parts)
    if text.startswith(">"):
        args, text = _decode_usr_arg_list(text[1:])
        if not args:
            raise ValueError("empty nested template argument list")
        name = format_specialization_key(name, args)
    return name, text


def find_full_specializations(primary: SymbolInfo, symbol_store, index_lock) -> List[SymbolInfo]:
    """Return full specialization symbols of the given primary class template."""
    simple = extract_simple_name(primary.qualified_name or primary.name)
    with index_lock:
        candidates = list(symbol_store.get_classes_by_name(simple))
    result = []
    for info in candidates:
        if not info.is_template_specialization:
            continue
        if primary.usr and info.primary_template_usr and info.primary_template_usr != primary.usr:
            continue
        result.append(info)
    return result


def recover_specialization_args(
    spec: SymbolInfo, primary: Optional[SymbolInfo], symbol_store, index_lock
) -> Optional[List[str]]:
    """Recover the template arguments of an indexed specialization symbol.

    Specialization symbols are stored with template arguments stripped from
    their names, so arguments are recovered from the USR first, then by
    matching the specialization's base classes against the primary template's
    substituted base classes.
    """
    decoded = decode_usr_template_args(spec.usr)
    if decoded is not None:
        return [resolve_class_key(a, symbol_store, index_lock) for a in decoded]
    if primary is None:
        return None
    return _args_from_base_substitution(spec, primary)


def _args_from_base_substitution(spec: SymbolInfo, primary: SymbolInfo) -> Optional[List[str]]:
    name_to_index = build_param_name_to_index(primary.template_parameters)
    arg_count = len(name_to_index)
    if not arg_count or not spec.base_classes:
        return None
    args: List[Optional[str]] = [None] * arg_count
    for position, base in enumerate(primary.base_classes):
        index = resolve_param_index(base, name_to_index)
        if index is not None and position < len(spec.base_classes):
            args[index] = spec.base_classes[position]
    if all(a is not None for a in args):
        return [str(a) for a in args]  # type: ignore[arg-type]
    return None


def find_matching_specialization(
    primary: SymbolInfo,
    template_args: List[str],
    symbol_store,
    index_lock,
) -> Optional[SymbolInfo]:
    """Find the indexed full specialization of ``primary`` for ``template_args``.

    Matching compares recovered arguments first (USR decoding), then falls
    back to substituted base classes — specialization symbols all share the
    template's stripped name, so name comparison cannot distinguish them.
    """
    specs = find_full_specializations(primary, symbol_store, index_lock)
    canon = [resolve_class_key(a, symbol_store, index_lock) for a in template_args]
    for spec in specs:
        recovered = recover_specialization_args(spec, primary, symbol_store, index_lock)
        if recovered is None:
            continue
        if [resolve_class_key(a, symbol_store, index_lock) for a in recovered] == canon:
            return spec
    return _match_specialization_by_bases(primary, template_args, specs, symbol_store, index_lock)


def _match_specialization_by_bases(
    primary: SymbolInfo,
    template_args: List[str],
    specs: List[SymbolInfo],
    symbol_store,
    index_lock,
) -> Optional[SymbolInfo]:
    if not _base_uses_template_params(primary.base_classes, primary.template_parameters):
        return None
    expected = [
        resolve_class_key(b, symbol_store, index_lock)
        for b in substitute_template_params(
            primary.base_classes, primary.template_parameters, template_args
        )
    ]
    for spec in specs:
        got = [
            resolve_class_key(b, symbol_store, index_lock)
            for b in substitute_template_params(
                spec.base_classes, primary.template_parameters, template_args
            )
        ]
        if got == expected:
            return spec
    return None
