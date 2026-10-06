"""Shared helpers for parsing C++ symbol names.

These functions are intentionally independent of SearchEngine so that
hierarchy/template analyzers can use them without reaching into a class
that is otherwise unrelated to simple name manipulation.
"""

from typing import Optional, Tuple


def strip_template_args(name: str) -> str:
    """Strip template argument suffix from a name.

    Examples:
        "Container<int>" -> "Container"
        "ns::Container<int>" -> "ns::Container"
        "std::map<int, std::string>" -> "std::map"
        "Widget" -> "Widget" (unchanged)
    """
    idx = name.find("<")
    if idx == -1:
        return name
    return name[:idx]


def is_dependent_type_name(name: str) -> bool:
    """Return True for template-dependent names that cannot be resolved now.

    Examples: "typename T::BaseType", "T<X>::Nested" (qualified through a
    template-id and therefore dependent on unresolved parameters).
    """
    return name.startswith("typename ") or ("<" in name and ">" in name and not name.endswith(">"))


def is_specialization_key(name: str) -> bool:
    """Return True when a name carries template arguments (e.g. "T<A1>").

    Guards against operator names ("operator<") and dependent names that only
    contain angle brackets incidentally.
    """
    if is_dependent_type_name(name):
        return False
    return "<" in name and name.endswith(">") and name.find("<") > 0


def split_specialization_key(name: str) -> Optional[Tuple[str, str]]:
    """Split "ns::T<ns::A1, int>" into ("ns::T", "ns::A1, int").

    Returns None when the name is not a specialization key.
    """
    if not is_specialization_key(name):
        return None
    idx = name.find("<")
    return name[:idx], name[idx + 1 : -1]


def extract_simple_name(qualified_name: str) -> str:
    """Extract simple name from qualified name, ignoring template arguments.

    Examples:
        "myapp::builders::Widget" -> "Widget"
        "std::vector" -> "vector"
        "Container<int>" -> "Container"
        "ns::Container<int>" -> "Container"
        "Widget" -> "Widget" (already simple)
    """
    name = qualified_name
    # Strip template argument suffix: "Container<int>" -> "Container"
    # Guard with endswith(">") to avoid mangling "operator<" or "operator<="
    if "<" in name and name.endswith(">"):
        name = name[: name.index("<")]
    if "::" not in name:
        return name
    return name.split("::")[-1]
