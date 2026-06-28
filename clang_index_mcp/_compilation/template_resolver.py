"""Pure template argument resolution logic for C++ template instantiation.

This module provides utility functions for parsing and resolving C++ template
arguments. It is used by both the compilation layer (during AST parsing) and
the symbols layer (during deferred symbol resolution).

All functions are stateless and have no libclang dependencies, making them
suitable for use across architectural layers.
"""

import re
from typing import Any, Dict, List


class TemplateResolver:
    """Resolves template parameters to actual arguments in base class names.

    This is pure string manipulation logic used during AST parsing and
    deferred symbol resolution. No libclang dependencies.
    """

    @staticmethod
    def extract_args_from_displayname(displayname: str) -> List[str]:
        """Extract template arguments from a displayname like 'MyTemplate<Arg1, Arg2>'.

        Handles nested templates correctly by tracking angle bracket depth.

        Args:
            displayname: Cursor displayname containing template syntax.

        Returns:
            List of template argument strings. Empty list if no template syntax.
        """
        if "<" not in displayname:
            return []

        args_start = displayname.find("<")
        args_end = displayname.rfind(">")
        if args_start >= args_end:
            return []

        args_str = displayname[args_start + 1 : args_end]

        template_args: List[str] = []
        depth = 0
        current = ""
        for c in args_str:
            if c == "<":
                depth += 1
                current += c
            elif c == ">":
                depth -= 1
                current += c
            elif c == "," and depth == 0:
                template_args.append(current.strip())
                current = ""
            else:
                current += c
        if current.strip():
            template_args.append(current.strip())

        return template_args

    @staticmethod
    def build_param_mapping(
        template_params: List[Dict[str, Any]], template_args: List[str]
    ) -> Dict[str, str]:
        """Build mapping from template parameter names to template arguments.

        Args:
            template_params: List of parameter metadata dicts with 'name' key.
            template_args: List of actual argument strings.

        Returns:
            Dict mapping parameter names to argument strings.
        """
        param_to_arg: Dict[str, str] = {}
        for i, param in enumerate(template_params):
            if i < len(template_args):
                param_name = param.get("name", "")
                if param_name:
                    param_to_arg[param_name] = template_args[i]
        return param_to_arg

    @staticmethod
    def substitute_in_bases(
        base_classes: List[str],
        param_to_arg: Dict[str, str],
        template_args: List[str],
    ) -> List[str]:
        """Resolve base classes by substituting parameter names with actual arguments.

        Handles both named parameters (e.g., 'T' -> 'int') and indexed parameters
        (e.g., 'type-parameter-0-0' -> 'int').

        Args:
            base_classes: List of base class names with unresolved parameters.
            param_to_arg: Mapping from parameter names to argument strings.
            template_args: List of actual argument strings (for indexed lookup).

        Returns:
            List of resolved base class names.
        """
        resolved: List[str] = []
        for base in base_classes:
            if base in param_to_arg:
                resolved.append(param_to_arg[base])
            else:
                match = re.match(r"type-parameter-(\d+)-(\d+)", base)
                if match:
                    param_index = int(match.group(2))
                    if param_index < len(template_args):
                        resolved.append(template_args[param_index])
                    else:
                        resolved.append(base)
                else:
                    resolved.append(base)
        return resolved
