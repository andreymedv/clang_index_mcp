"""Symbol information data structure for C++ analysis."""

import json
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(slots=True)
class SymbolInfo:
    """Information about a C++ symbol (class, function, etc.)"""

    name: str
    kind: str  # "class", "function", "method", etc.
    file: str
    line: int
    column: int
    qualified_name: str = ""  # Fully qualified name (e.g., "ns1::ns2::Class")
    signature: str = ""
    is_project: bool = True
    namespace: str = ""  # Namespace portion (e.g., "ns1::ns2" from "ns1::ns2::Class")
    access: str = "public"  # public, private, protected
    parent_class: str = ""  # For methods, the containing class
    base_classes: List[str] = field(default_factory=list)  # For classes
    usr: str = ""  # Unified Symbol Resolution - unique identifier
    # Note: calls/called_by fields removed in v9.0 (Task 1.2 memory optimization)
    # Call graph data is now stored in call_sites table and queried on-demand

    # Overload metadata (Phase 3: Qualified Names Support)
    is_template_specialization: bool = (
        False  # True for template specializations (e.g., template<> void foo<int>())
    )

    # Template tracking (Template Search Support)
    is_template: bool = False  # True for any template-related symbol
    template_kind: Optional[str] = None  # 'class_template', 'function_template', etc.
    template_parameters: Optional[str] = None  # JSON array for generic templates
    primary_template_usr: Optional[str] = None  # USR of primary template for specializations

    # Line ranges (Phase 1: LLM Integration)
    start_line: Optional[int] = None  # First line of symbol definition
    end_line: Optional[int] = None  # Last line of symbol definition

    # Header file location (for declarations separate from definitions)
    header_file: Optional[str] = None  # Path to header file (if declaration separate)
    header_line: Optional[int] = None  # Declaration line in header
    header_start_line: Optional[int] = None  # Declaration start line
    header_end_line: Optional[int] = None  # Declaration end line

    # Documentation (Phase 2: LLM Integration)
    brief: Optional[str] = None  # Brief description (first line of documentation)
    doc_comment: Optional[str] = None  # Full documentation comment

    # Virtual/abstract method indicators (Phase 5: LLM Integration)
    is_virtual: bool = False  # True if method is virtual
    is_pure_virtual: bool = False  # True if method is pure virtual (= 0)
    is_const: bool = False  # True if method is const-qualified
    is_static: bool = False  # True if method/function is static

    # Definition tracking (exposed for LLM tools)
    is_definition: bool = False  # True if this cursor is a definition (has body)

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "kind": self.kind,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "signature": self.signature,
            "is_project": self.is_project,
            "namespace": self.namespace,
            "access": self.access,
            "parent_class": self.parent_class,
            "base_classes": self.base_classes,
            "usr": self.usr,
            # Overload metadata (Phase 3)
            "is_template_specialization": self.is_template_specialization,
            # Template tracking (Template Search Support)
            "is_template": self.is_template,
            "template_kind": self.template_kind,
            "template_parameters": self.template_parameters,
            # Note: specialization_of should be resolved to qualified name at query time
            # Here we output the USR as fallback if to_dict() is used directly
            "specialization_of": self.primary_template_usr,
            # Note: calls/called_by removed in v9.0 - use call graph API
            # Line ranges (Phase 1)
            "start_line": self.start_line,
            "end_line": self.end_line,
            "header_file": self.header_file,
            "header_line": self.header_line,
            "header_start_line": self.header_start_line,
            "header_end_line": self.header_end_line,
            # Documentation (Phase 2)
            "brief": self.brief,
            "doc_comment": self.doc_comment,
            # Virtual/abstract indicators (Phase 5)
            "is_virtual": self.is_virtual,
            "is_pure_virtual": self.is_pure_virtual,
            "is_const": self.is_const,
            "is_static": self.is_static,
            "is_definition": self.is_definition,
        }


# Constants for class-like symbol kinds
CLASS_KINDS = ("class", "struct", "class_template", "partial_specialization")


def is_richer_definition(new_symbol: "SymbolInfo", existing_symbol: "SymbolInfo") -> bool:
    """Determine if new_symbol is a richer definition than existing_symbol.

    When both symbols have is_definition=True (e.g., a macro-generated empty struct
    and the real struct with base classes), prefer the one with more semantic content.

    Returns True if new_symbol should replace existing_symbol.
    """
    # Heuristic 1: prefer non-empty base_classes
    new_has_bases = bool(new_symbol.base_classes)
    existing_has_bases = bool(existing_symbol.base_classes)
    if new_has_bases and not existing_has_bases:
        return True
    if existing_has_bases and not new_has_bases:
        return False

    # Heuristic 2: prefer larger line span (more content)
    new_span = (
        (new_symbol.end_line - new_symbol.start_line)
        if new_symbol.start_line is not None and new_symbol.end_line is not None
        else 0
    )
    existing_span = (
        (existing_symbol.end_line - existing_symbol.start_line)
        if existing_symbol.start_line is not None and existing_symbol.end_line is not None
        else 0
    )
    if new_span > existing_span:
        return True

    # Tie: keep existing (stable)
    return False


def get_template_param_base_indices(info: "SymbolInfo") -> List[int]:
    """Return indices of base_classes entries that are template parameters.

    Cross-references base_classes with template_parameters JSON to identify
    which base classes are actually template parameter names rather than
    concrete class names.

    Example:
        template<typename T, typename U> class Foo : public T, public Bar
        base_classes = ['T', 'Bar']
        template_parameters = [{"name": "T", ...}, {"name": "U", ...}]
        → returns [0]  (index 0 in base_classes is template param 'T')
    """
    if not info.template_parameters or not info.base_classes:
        return []

    # Parse template parameter names
    try:
        params = json.loads(info.template_parameters)
    except (json.JSONDecodeError, TypeError):
        return []

    param_names = {p.get("name", "") for p in params if p.get("name")}
    if not param_names:
        return []

    # Find which base_classes entries match template parameter names
    indices = []
    for i, base in enumerate(info.base_classes):
        if base in param_names:
            indices.append(i)
    return indices
