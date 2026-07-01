"""Template inheritance analysis helpers for the query engine.

Provides parsing and matching utilities for template parameters, specializations,
and indirect inheritance through template parameters (e.g. ``class Foo<T> : public T``).
"""

import json
import re
from typing import Any, Dict, List, Optional, Set

from .._symbols.model import SymbolInfo, build_location_objects, omit_empty
from .._search.pattern_matcher import matches_qualified_pattern
from .._search.symbol_name_utils import extract_simple_name


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

    # Issue #99 Phase 3: Check if this is a template and get all specializations
    template_patterns = get_template_patterns(simple_name, symbol_store, index_lock)

    with index_lock:
        for name, infos in symbol_store.iter_class_items():
            for info in infos:
                if not project_only or info.is_project:
                    if is_derived_from(
                        info, template_patterns, simple_name, symbol_store, index_lock
                    ):
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
