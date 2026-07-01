"""Shared helpers for parsing C++ symbol names.

These functions are intentionally independent of SearchEngine so that
hierarchy/template analyzers can use them without reaching into a class
that is otherwise unrelated to simple name manipulation.
"""


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
