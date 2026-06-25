"""Template specialization lookup helpers for SymbolIndexStore."""

import re
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .._symbols.model import SymbolInfo
    from .symbol_index_store import SymbolIndexStore


def extract_template_base_name_from_usr(usr: str) -> Optional[str]:
    """
    Extract the base template name from a USR.

    USR Format Examples:
    - Generic Template:        c:@ST>1#T@Container
    - Explicit Specialization: c:@S@Container>#I
    - Partial Specialization:  c:@SP>1#T@Container>#*t0.0

    Returns:
        Base template name (e.g., "Container") or None if not a template-related USR
    """
    if not usr:
        return None

    match = re.search(r"c:@ST>[^@]*@(\w+)", usr)
    if match:
        return match.group(1)

    match = re.search(r"c:@S@(\w+)", usr)
    if match:
        return match.group(1)

    match = re.search(r"c:@SP>[^@]*@(\w+)", usr)
    if match:
        return match.group(1)

    return None


def add_class_template_symbols(class_index, base_name: str, results: List["SymbolInfo"]) -> None:
    """Add class template and specialization symbols to results."""
    if base_name not in class_index:
        return
    for symbol in class_index[base_name]:
        if symbol.kind in ("class_template", "partial_specialization"):
            results.append(symbol)
        elif symbol.kind in ("class", "struct"):
            if symbol.usr and ">#" in symbol.usr:
                results.append(symbol)


def add_function_template_symbols(
    function_index, base_name: str, results: List["SymbolInfo"]
) -> None:
    """Add function template and specialization symbols to results."""
    if base_name not in function_index:
        return
    for symbol in function_index[base_name]:
        if symbol.kind == "function_template":
            results.append(symbol)
        elif symbol.kind in ("function", "method"):
            if symbol.is_template_specialization or (
                symbol.usr and ("<#" in symbol.usr or ">#" in symbol.usr)
            ):
                results.append(symbol)


def find_template_specializations(store: "SymbolIndexStore", base_name: str) -> List["SymbolInfo"]:
    """
    Find all specializations of a template by base name.

    Searches for:
    1. Generic template definition (kind=class_template, function_template)
    2. Explicit full specializations (kind=class, function with template args in USR)
    3. Partial specializations (kind=partial_specialization)
    """
    results: List["SymbolInfo"] = []

    with store.index_lock:
        add_class_template_symbols(store.class_index, base_name, results)
        add_function_template_symbols(store.function_index, base_name, results)

    return results
