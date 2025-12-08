"""Symbol information data structure for C++ analysis."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SymbolInfo:
    """Information about a C++ symbol (class, function, etc.)"""
    name: str
    kind: str  # "class", "function", "method", etc.
    file: str
    line: int
    column: int
    signature: str = ""
    is_project: bool = True
    namespace: str = ""
    access: str = "public"  # public, private, protected
    parent_class: str = ""  # For methods, the containing class
    base_classes: List[str] = field(default_factory=list)  # For classes
    usr: str = ""  # Unified Symbol Resolution - unique identifier
    calls: List[str] = field(default_factory=list)  # USRs of functions this function calls
    called_by: List[str] = field(default_factory=list)  # USRs of functions that call this

    # Line ranges (Phase 1: LLM Integration)
    start_line: Optional[int] = None  # First line of symbol definition
    end_line: Optional[int] = None    # Last line of symbol definition

    # Header file location (for declarations separate from definitions)
    header_file: Optional[str] = None        # Path to header file (if declaration separate)
    header_line: Optional[int] = None        # Declaration line in header
    header_start_line: Optional[int] = None  # Declaration start line
    header_end_line: Optional[int] = None    # Declaration end line

    # Documentation (Phase 2: LLM Integration)
    brief: Optional[str] = None         # Brief description (first line of documentation)
    doc_comment: Optional[str] = None   # Full documentation comment

    # Internal field for definition-wins logic (not persisted)
    is_definition: bool = False  # True if this cursor is a definition (has body)

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            "name": self.name,
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
            "calls": self.calls,
            "called_by": self.called_by,
            # Line ranges (Phase 1)
            "start_line": self.start_line,
            "end_line": self.end_line,
            "header_file": self.header_file,
            "header_line": self.header_line,
            "header_start_line": self.header_start_line,
            "header_end_line": self.header_end_line,
            # Documentation (Phase 2)
            "brief": self.brief,
            "doc_comment": self.doc_comment
        }