"""Pattern matching utilities for symbol search.

Isolates the logic that decides whether a symbol name or qualified name matches
a user-provided pattern.  Supports plain-text exact matching, component-based
qualified-name suffix matching, and full regex matching.
"""

import re


def is_pattern(text: str) -> bool:
    """Check if text contains regex metacharacters that indicate it's a pattern.

    Returns True if text contains regex special chars (*, +, ?, ., [, etc.)
    Returns False for plain text (should use exact matching)
    """
    # Check for common regex metacharacters
    # This list includes characters that users would use for pattern matching
    regex_chars = r".*+?[]{}()|\^$"
    return any(char in text for char in regex_chars)


def matches(pattern: str, name: str) -> bool:
    """Check if name matches pattern using exact or pattern matching.

    - If pattern is empty: match all (returns True)
    - If pattern has no regex metacharacters: exact match (case-insensitive)
    - If pattern has regex metacharacters: regex fullmatch (anchored pattern matching)

    Using fullmatch instead of search provides more intuitive behavior:
    - "View.*" matches "View", "ViewManager" (starts with View)
    - "View.*" does NOT match "ListView" (doesn't start with View)
    - ".*View.*" matches all of the above (contains View anywhere)
    """
    # Empty pattern matches all symbols (useful with file_name filter)
    if not pattern:
        return True

    if is_pattern(pattern):
        # Pattern matching: use regex fullmatch (anchored at both ends)
        regex = re.compile(pattern, re.IGNORECASE)
        return regex.fullmatch(name) is not None
    else:
        # Exact matching: case-insensitive equality
        return name.lower() == pattern.lower()


def normalize_template_whitespace(name: str) -> str:
    """
    Normalize whitespace in template arguments for consistent matching.

    libclang stores template arguments with spaces around pointer/reference operators
    (e.g., 'Container<Widget *>' not 'Container<Widget*>'), but users naturally
    search without spaces. This method normalizes both to enable matching.

    Args:
        name: Type name or pattern that may contain template arguments

    Returns:
        Name with normalized whitespace in template arguments

    Examples:
        'Container<Widget *>' → 'Container<Widget*>'
        'Container<Widget * const &>' → 'Container<Widget*const&>'
        'std::vector<int *>' → 'std::vector<int*>'
        'Container<Widget*>' → 'Container<Widget*>' (unchanged)

    Note:
        Only normalizes spaces around *, &, and && operators.
        Preserves spaces in type names like 'unsigned int', 'const char'.
    """
    # Remove spaces before * and & operators
    name = re.sub(r"\s+\*", "*", name)
    name = re.sub(r"\s+&", "&", name)

    # Remove spaces after * and & operators (but keep meaningful spaces)
    # Use lookahead to avoid removing spaces before keywords/types
    name = re.sub(r"\*\s+", "*", name)
    name = re.sub(r"&\s+", "&", name)

    return name


def detect_pattern_type(pattern: str) -> str:
    """
    Detect pattern type for qualified name search optimization.

    Phase 2 (Qualified Names): Component-based pattern matching.

    Returns:
        "exact": Leading :: means exact match in global namespace (e.g., "::View")
        "unqualified": No :: means match unqualified name only (e.g., "View")
        "suffix": Contains :: means component-based suffix match (e.g., "ui::View")
        "regex": Contains regex metacharacters (e.g., "app::.*::View")

    Examples:
        detect_pattern_type("::View") → "exact"
        detect_pattern_type("View") → "unqualified"
        detect_pattern_type("ui::View") → "suffix"
        detect_pattern_type("app::.*::View") → "regex"

    Task: T2.1.2 (Qualified Names Phase 2)
    """
    # Empty pattern handled by caller
    if not pattern:
        return "unqualified"

    # Leading :: → exact match in global namespace
    if pattern.startswith("::"):
        return "exact"

    # Check for regex metacharacters
    regex_chars = set(".*+?[]{}()|\\^$")
    if any(c in pattern for c in regex_chars):
        return "regex"

    # No :: → match unqualified name
    if "::" not in pattern:
        return "unqualified"

    # Contains :: but not leading, no regex → component-based suffix match
    return "suffix"


def matches_qualified_pattern(qualified_name: str, pattern: str) -> bool:
    """
    Match qualified name against pattern using component-based suffix matching.

    Phase 2 (Qualified Names): Intelligent pattern matching with 4 modes.

    Matching Rules:
        1. Leading "::" → exact match (global namespace)
           "::View" matches only "View" (not "ns::View")

        2. No "::" → match unqualified name only
           "View" matches "View", "ns::View", "ns1::ns2::View"

        3. "::" in pattern → component-based suffix match
           "ui::View" matches "app::ui::View", "legacy::ui::View"
           but NOT "myui::View" (component boundary respected)

        4. Regex metacharacters → regex fullmatch
           "app::.*::View" matches "app::core::View", "app::ui::View"

    Args:
        qualified_name: Fully qualified symbol name (e.g., "app::ui::View")
        pattern: Search pattern (e.g., "ui::View", "::View", "View", ".*::View")

    Returns:
        True if qualified_name matches pattern, False otherwise

    Examples:
        matches_qualified_pattern("app::ui::View", "ui::View") → True (suffix)
        matches_qualified_pattern("app::ui::View", "::View") → False (not global)
        matches_qualified_pattern("app::ui::View", "View") → True (unqualified)
        matches_qualified_pattern("app::ui::View", "app::.*::View") → True (regex)
        matches_qualified_pattern("myui::View", "ui::View") → False (boundary)

    Template whitespace normalization:
        Handles libclang's spacing in template arguments:
        - "Container<Widget *>" matches pattern "Container<Widget*>"
        - "PointerHolder<Widget *>" matches pattern "PointerHolder<Widget*>"

    Task: T2.1.1 (Qualified Names Phase 2)
    """
    # Empty pattern matches everything
    if not pattern:
        return True

    # Normalize whitespace in template arguments for both name and pattern
    # This allows "Container<Widget*>" to match "Container<Widget *>"
    qualified_name = normalize_template_whitespace(qualified_name)
    pattern = normalize_template_whitespace(pattern)

    pattern_type = detect_pattern_type(pattern)

    # 1. Exact match: leading ::
    if pattern_type == "exact":
        # Remove leading :: from pattern and compare with qualified_name
        return qualified_name == pattern[2:]

    # 2. Regex match (case-insensitive for consistency with other modes)
    if pattern_type == "regex":
        try:
            return bool(re.fullmatch(pattern, qualified_name, re.IGNORECASE))
        except re.error:
            # Invalid regex → no match
            return False

    # 3. Unqualified match: no ::
    if pattern_type == "unqualified":
        # Extract unqualified name from qualified_name
        unqualified = qualified_name.split("::")[-1]
        return unqualified.lower() == pattern.lower()

    # 4. Suffix match: component-based
    if pattern_type == "suffix":
        q_parts = qualified_name.split("::")
        p_parts = pattern.split("::")

        # Pattern longer than name → cannot match
        if len(p_parts) > len(q_parts):
            return False

        # Check that last N components match (case-insensitive)
        q_suffix = q_parts[-len(p_parts) :]
        return [p.lower() for p in q_suffix] == [p.lower() for p in p_parts]

    # Fallback (should never reach here)
    return False
