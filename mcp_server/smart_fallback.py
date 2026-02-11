"""
Smart fallback suggestions for empty search results.

When MCP search tools return no results, this module analyzes the original pattern
to detect common LLM mistakes and generate actionable suggestions:
- Signature/prototype used as pattern instead of name
- Regex anchoring issues (fullmatch semantics)
- Qualified name with wrong namespace
- File name case mismatch

Design: Fallback cascade runs in priority order, first match wins.
Performance: Only called when results are empty. Uses O(1) index lookups, not full scans.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class FallbackResult:
    """Structured result from smart fallback analysis."""

    reason: str  # e.g. "signature_detected", "regex_hint", "qualified_fallback"
    searched_for: str  # Original pattern
    hint: str  # Human-readable explanation
    alternatives: List[Dict[str, Any]] = field(default_factory=list)  # Max 10
    suggested_pattern: Optional[str] = None  # Corrected pattern to try

    def to_metadata(self) -> Dict[str, Any]:
        """Convert to metadata dict for EnhancedQueryResult."""
        result: Dict[str, Any] = {
            "reason": self.reason,
            "searched_for": self.searched_for,
            "hint": self.hint,
        }
        if self.suggested_pattern:
            result["suggested_pattern"] = self.suggested_pattern
        if self.alternatives:
            result["alternatives"] = self.alternatives[:10]
        return result


# Regex patterns that indicate a C++ signature/prototype, not a symbol name
_SIGNATURE_INDICATORS = [
    re.compile(r"\("),  # parentheses
    re.compile(r"\bvoid\b"),
    re.compile(r"\bbool\b"),
    re.compile(r"\bint\b"),
    re.compile(r"\bfloat\b"),
    re.compile(r"\bdouble\b"),
    re.compile(r"\bchar\b"),
    re.compile(r"\bconst\b"),
    re.compile(r"\bstruct\b\s"),  # "struct " as type prefix, not as search filter
    re.compile(r"\bclass\b\s"),  # "class " as type prefix
    re.compile(r"\bauto\b"),
    re.compile(r"\btypename\b"),
    re.compile(r"\bunsigned\b"),
    re.compile(r"\blong\b"),
    re.compile(r"\bshort\b"),
]

# Additional indicators: pattern has spaces + identifiers (looks like type + name)
_PROTOTYPE_PATTERN = re.compile(r"^[a-zA-Z_][\w:]*\s+[a-zA-Z_][\w:]*\s*\(", re.ASCII)

# C++ identifier pattern
_IDENTIFIER_RE = re.compile(r"[a-zA-Z_]\w*(?:::[a-zA-Z_]\w*)*")


def _looks_like_signature(pattern: str) -> bool:
    """Check if pattern looks like a C++ function signature rather than a name."""
    # Must have at least one space (type + name) or parentheses
    if "(" in pattern:
        return True
    # Check for type keyword indicators
    for indicator in _SIGNATURE_INDICATORS:
        if indicator.search(pattern):
            # Additional check: must have space-separated tokens (type + name)
            tokens = pattern.split()
            if len(tokens) >= 2:
                return True
    return False


def _extract_identifier_from_signature(pattern: str) -> Optional[str]:
    """Extract the most likely function/class name from a signature-like pattern.

    Heuristic: the last identifier before '(' is usually the function name.
    For type-only patterns (e.g., "IConfig &"), extract identifiers.
    """
    if "(" in pattern:
        before_paren = pattern[: pattern.index("(")]
        # Find identifiers in the part before parentheses
        identifiers: List[str] = _IDENTIFIER_RE.findall(before_paren)
        if identifiers:
            # Last identifier before ( is usually the function name
            return str(identifiers[-1])
    # No parens — extract all identifiers, return the longest/most specific
    identifiers = _IDENTIFIER_RE.findall(pattern)
    if identifiers:
        # Filter out type keywords
        type_keywords = {
            "void",
            "bool",
            "int",
            "float",
            "double",
            "char",
            "const",
            "struct",
            "class",
            "auto",
            "typename",
            "unsigned",
            "long",
            "short",
            "static",
            "virtual",
            "inline",
            "extern",
            "volatile",
            "mutable",
            "explicit",
            "template",
        }
        non_keywords: List[str] = [i for i in identifiers if i.lower() not in type_keywords]
        if non_keywords:
            # Return the longest one (most specific)
            return str(max(non_keywords, key=len))
        # All keywords — return longest anyway
        return str(max(identifiers, key=len))
    return None


def _has_double_escapes(pattern: str) -> bool:
    """Check if pattern has double-escaped regex metacharacters."""
    return "\\\\" in pattern or "\\." in pattern and "\\.*" not in pattern


def _has_unnecessary_anchors(pattern: str) -> bool:
    """Check if pattern has ^ or $ anchors (redundant with fullmatch)."""
    # Ignore ^ inside character classes [^...]
    has_caret = "^" in pattern and not re.search(r"\[\^", pattern)
    has_dollar = pattern.endswith("$")
    return has_caret or has_dollar


def _strip_anchors(pattern: str) -> str:
    """Remove unnecessary ^ and $ anchors."""
    result = pattern
    if result.startswith("^"):
        result = result[1:]
    if result.endswith("$"):
        result = result[:-1]
    return result


def _looks_like_short_regex(pattern: str) -> bool:
    """Check if pattern is a short regex that probably needs .* suffix.

    E.g., "I[A-Z]" only matches 2-char names. User probably wants "I[A-Z].*".
    """
    # Check if pattern has regex metacharacters but is very short when expanded
    try:
        # Estimate minimum match length by removing regex syntax
        stripped = re.sub(r"\[.*?\]", "X", pattern)  # Replace char classes
        stripped = re.sub(r"[.*+?{}()|\\^$]", "", stripped)  # Remove metacharacters
        return len(stripped) <= 3 and len(pattern) <= 10
    except Exception:
        return False


def _index_lookup_simple(
    index: Dict[str, List[Any]], name: str, max_results: int = 10
) -> List[Dict[str, Any]]:
    """Look up a simple name in an index, return formatted alternatives."""
    name_lower = name.lower()
    candidates = index.get(name, [])
    # Also try case-insensitive
    if not candidates:
        for key, infos in index.items():
            if key.lower() == name_lower:
                candidates = infos
                break
    results = []
    for info in candidates[:max_results]:
        results.append(
            {
                "name": info.name,
                "qualified_name": getattr(info, "qualified_name", info.name),
                "file": info.file,
                "line": info.line,
            }
        )
    return results


def _sample_regex_matches(
    index: Dict[str, List[Any]],
    pattern: str,
    max_sample: int = 200,
    max_results: int = 10,
) -> List[Dict[str, Any]]:
    """Test a regex pattern against a sample of index entries.

    Returns matching alternatives. Bounded to max_sample entries for performance.
    """
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return []

    results = []
    checked = 0
    for name, infos in index.items():
        if checked >= max_sample:
            break
        for info in infos:
            checked += 1
            if checked >= max_sample:
                break
            qualified = getattr(info, "qualified_name", info.name)
            if compiled.fullmatch(qualified) or compiled.fullmatch(info.name):
                results.append(
                    {
                        "name": info.name,
                        "qualified_name": qualified,
                        "file": info.file,
                        "line": info.line,
                    }
                )
                if len(results) >= max_results:
                    return results
    return results


class SmartFallback:
    """Analyzes failed search patterns and generates smart suggestions.

    Called only when search results are empty. Runs a priority-ordered
    fallback cascade to detect common LLM mistakes and suggest corrections.
    """

    def analyze_empty_result(
        self,
        pattern: str,
        tool_name: str,
        class_index: Dict[str, List[Any]],
        function_index: Dict[str, List[Any]],
        file_index: Optional[Dict[str, List[Any]]] = None,
        file_name: Optional[str] = None,
        namespace: Optional[str] = None,
        class_name: Optional[str] = None,
    ) -> Optional[FallbackResult]:
        """Run fallback cascade and return first useful suggestion.

        Args:
            pattern: The original search pattern that returned no results
            tool_name: Which MCP tool was called
            class_index: Dict[simple_name, List[SymbolInfo]]
            function_index: Dict[simple_name, List[SymbolInfo]]
            file_index: Dict[file_path, List[SymbolInfo]] (for file suggestions)
            file_name: Original file_name filter (if any)
            namespace: Original namespace filter (if any)
            class_name: Original class_name filter (search_functions only)

        Returns:
            FallbackResult if a useful suggestion was generated, None otherwise.
        """
        if not pattern:
            return None

        # Select the appropriate index for the tool
        if tool_name == "search_classes":
            primary_index = class_index
        elif tool_name == "search_functions":
            primary_index = function_index
        else:
            # search_symbols uses both — merge for lookup purposes
            primary_index = {**class_index, **function_index}

        # Cascade: try each detector in priority order
        result = self._detect_signature(pattern, primary_index, function_index)
        if result:
            return result

        result = self._detect_regex_issues(pattern, primary_index)
        if result:
            return result

        result = self._detect_qualified_fallback(pattern, primary_index)
        if result:
            return result

        if file_name and file_index:
            result = self._detect_file_case_mismatch(pattern, file_name, file_index, primary_index)
            if result:
                return result

        return None

    def _detect_signature(
        self,
        pattern: str,
        primary_index: Dict[str, List[Any]],
        function_index: Dict[str, List[Any]],
    ) -> Optional[FallbackResult]:
        """Detect signature/prototype used as pattern instead of symbol name."""
        if not _looks_like_signature(pattern):
            return None

        extracted = _extract_identifier_from_signature(pattern)
        if not extracted:
            return FallbackResult(
                reason="signature_detected",
                searched_for=pattern,
                hint=(
                    "Pattern looks like a C++ function signature or type expression, "
                    "not a symbol name. "
                    "Use just the function/class name as the pattern."
                ),
            )

        # Try to find the extracted name in the index
        alternatives = _index_lookup_simple(function_index, extracted)
        if not alternatives:
            alternatives = _index_lookup_simple(primary_index, extracted)

        return FallbackResult(
            reason="signature_detected",
            searched_for=pattern,
            hint=(
                f"Pattern looks like a C++ function signature, not a symbol name. "
                f"Use just the name '{extracted}' as the pattern."
            ),
            suggested_pattern=extracted,
            alternatives=alternatives,
        )

    def _detect_regex_issues(
        self, pattern: str, primary_index: Dict[str, List[Any]]
    ) -> Optional[FallbackResult]:
        """Detect regex anchoring issues, double escapes, etc."""
        # Only applies to patterns classified as regex
        regex_chars = set(".*+?[]{}()|\\^$")
        if not any(c in pattern for c in regex_chars):
            return None

        # Check for double escapes first (e.g., \\. when user means \.)
        if _has_double_escapes(pattern):
            # Try with single escapes
            fixed = pattern.replace("\\\\", "\\")
            alternatives = _sample_regex_matches(primary_index, fixed)
            if alternatives:
                return FallbackResult(
                    reason="regex_hint",
                    searched_for=pattern,
                    hint=(
                        "Pattern appears to have double-escaped characters. "
                        "Regex patterns are passed directly — no extra escaping needed."
                    ),
                    suggested_pattern=fixed,
                    alternatives=alternatives,
                )

        # Check for unnecessary anchors (^ and $)
        if _has_unnecessary_anchors(pattern):
            stripped = _strip_anchors(pattern)
            # When user writes "Reporter$" they want suffix match → ".*Reporter"
            # When user writes "^Console" they want prefix match → "Console.*"
            suggested = stripped
            if pattern.endswith("$") and not stripped.startswith(".*"):
                suggested = ".*" + stripped
            if pattern.startswith("^") and not stripped.endswith(".*"):
                suggested = suggested + ".*"
            alternatives = _sample_regex_matches(primary_index, suggested)
            if not alternatives:
                # Also try exact stripped version
                alternatives = _sample_regex_matches(primary_index, stripped)
                if alternatives:
                    suggested = stripped
            if alternatives:
                return FallbackResult(
                    reason="regex_hint",
                    searched_for=pattern,
                    hint=(
                        "Patterns use fullmatch (anchored at both ends), "
                        "so ^ and $ anchors are redundant. "
                        f"Try '{suggested}' instead."
                    ),
                    suggested_pattern=suggested,
                    alternatives=alternatives,
                )

        # Check for short regex that needs .* suffix
        if _looks_like_short_regex(pattern):
            broadened = pattern + ".*"
            alternatives = _sample_regex_matches(primary_index, broadened)
            if alternatives:
                return FallbackResult(
                    reason="regex_hint",
                    searched_for=pattern,
                    hint=(
                        f"Patterns use fullmatch (anchored at both ends). "
                        f"'{pattern}' only matches very short names. "
                        f"Try '{broadened}' to match names starting with this pattern."
                    ),
                    suggested_pattern=broadened,
                    alternatives=alternatives,
                )

        # Generic: try broadening with .* prefix/suffix
        if not pattern.startswith(".*"):
            broadened = ".*" + pattern
            if not broadened.endswith(".*"):
                broadened = broadened + ".*"
            alternatives = _sample_regex_matches(primary_index, broadened)
            if alternatives:
                return FallbackResult(
                    reason="regex_hint",
                    searched_for=pattern,
                    hint=(
                        "Patterns use fullmatch (anchored at both ends). "
                        f"'{pattern}' requires an exact full match. "
                        f"Try '{broadened}' for partial matching."
                    ),
                    suggested_pattern=broadened,
                    alternatives=alternatives,
                )

        return None

    def _detect_qualified_fallback(
        self, pattern: str, primary_index: Dict[str, List[Any]]
    ) -> Optional[FallbackResult]:
        """Detect wrong namespace in qualified name and suggest alternatives."""
        if "::" not in pattern:
            return None

        # Don't apply to regex patterns
        regex_chars = set(".*+?[]{}()|\\^$")
        if any(c in pattern for c in regex_chars):
            return None

        simple_name = pattern.split("::")[-1]
        if not simple_name:
            return None

        alternatives = _index_lookup_simple(primary_index, simple_name)
        if not alternatives:
            return None

        return FallbackResult(
            reason="qualified_fallback",
            searched_for=pattern,
            hint=(
                f"No match for '{pattern}'. "
                f"Found '{simple_name}' in {len(alternatives)} location(s). "
                f"Use the qualified_name from alternatives for exact match."
            ),
            suggested_pattern=simple_name,
            alternatives=alternatives,
        )

    def _detect_file_case_mismatch(
        self,
        pattern: str,
        file_name: str,
        file_index: Dict[str, List[Any]],
        primary_index: Dict[str, List[Any]],
    ) -> Optional[FallbackResult]:
        """Detect file_name filter with wrong case."""
        file_name_lower = file_name.lower()
        matching_files = []
        for indexed_file in file_index.keys():
            indexed_basename = Path(indexed_file).name
            if indexed_basename.lower() == file_name_lower and indexed_basename != file_name:
                matching_files.append(indexed_basename)

        if not matching_files:
            return None

        correct_name = matching_files[0]
        return FallbackResult(
            reason="file_case_mismatch",
            searched_for=pattern,
            hint=(
                f"No file matching '{file_name}' (case-sensitive). "
                f"Did you mean '{correct_name}'? "
                f"Use file_name='{correct_name}' for exact match."
            ),
            suggested_pattern=pattern,
            alternatives=[{"suggested_file_name": f} for f in matching_files[:5]],
        )
