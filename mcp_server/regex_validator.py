"""
Regex Validator - ReDoS Prevention

Validates regex patterns to prevent Regular Expression Denial of Service (ReDoS) attacks.
Detects catastrophic backtracking patterns that could cause exponential time complexity.
"""

import re
from typing import Tuple, Optional


class RegexValidationError(Exception):
    """Raised when a regex pattern is deemed unsafe."""

    pass


class RegexValidator:
    """Validates regex patterns for ReDoS vulnerabilities."""

    # Dangerous patterns that can cause catastrophic backtracking
    DANGEROUS_PATTERNS = [
        # Nested quantifiers: (a+)+, (a*)+, (a+)*, (a*)*
        (r"\([^()]*[\+\*]\)[\+\*]", "Nested quantifiers can cause exponential backtracking"),
        # Overlapping alternation: (a|a)*, (ab|a)*
        (r"\([^()]*\|[^()]*\)[\+\*]", "Alternation with quantifiers can cause backtracking"),
        # Repetition on groups containing repetition
        (r"\([^()]*[\+\*\{][^()]*\)[\+\*\{]", "Quantified group containing quantifiers"),
    ]

    # Maximum complexity score allowed
    MAX_COMPLEXITY_SCORE = 10

    @staticmethod
    def analyze_complexity(pattern: str) -> int:
        """
        Analyze regex complexity and return a score.
        Higher scores indicate more dangerous patterns.

        Args:
            pattern: The regex pattern to analyze

        Returns:
            Complexity score (0-100)
        """
        score = 0

        # Count nested groups
        max_nesting = 0
        current_nesting = 0
        for char in pattern:
            if char == "(":
                current_nesting += 1
                max_nesting = max(max_nesting, current_nesting)
            elif char == ")":
                current_nesting -= 1

        score += max_nesting * 2

        # Count quantifiers
        quantifiers = pattern.count("+") + pattern.count("*") + pattern.count("{")
        score += quantifiers

        # Count alternations
        alternations = pattern.count("|")
        score += alternations

        # Penalize nested quantifiers heavily
        if re.search(r"\([^()]*[\+\*]\)[\+\*]", pattern):
            score += 50  # Critical vulnerability

        # Penalize alternation in quantified groups
        if re.search(r"\([^()]*\|[^()]*\)[\+\*]", pattern):
            score += 30  # High vulnerability

        return score

    @classmethod
    def validate(cls, pattern: str, max_length: int = 1000) -> Tuple[bool, Optional[str]]:
        """
        Validate a regex pattern for safety.

        Args:
            pattern: The regex pattern to validate
            max_length: Maximum allowed pattern length

        Returns:
            Tuple of (is_valid, error_message)

        Raises:
            RegexValidationError: If the pattern is unsafe
        """
        # Check pattern length
        if len(pattern) > max_length:
            return False, f"Pattern too long ({len(pattern)} > {max_length})"

        # Check for dangerous patterns
        for dangerous_pattern, reason in cls.DANGEROUS_PATTERNS:
            if re.search(dangerous_pattern, pattern):
                return False, f"Dangerous pattern detected: {reason}"

        # Check complexity score
        complexity = cls.analyze_complexity(pattern)
        if complexity > cls.MAX_COMPLEXITY_SCORE:
            return False, f"Pattern too complex (score: {complexity} > {cls.MAX_COMPLEXITY_SCORE})"

        # Try to compile the pattern
        try:
            re.compile(pattern)
        except re.error as e:
            return False, f"Invalid regex pattern: {str(e)}"

        return True, None

    @classmethod
    def validate_or_raise(cls, pattern: str) -> None:
        """
        Validate a regex pattern and raise an exception if unsafe.

        Args:
            pattern: The regex pattern to validate

        Raises:
            RegexValidationError: If the pattern is unsafe
        """
        is_valid, error_msg = cls.validate(pattern)
        if not is_valid:
            raise RegexValidationError(f"Unsafe regex pattern: {error_msg}")

    @classmethod
    def sanitize(cls, pattern: str) -> str:
        """
        Attempt to sanitize a pattern by escaping special characters if it's unsafe.

        Args:
            pattern: The regex pattern to sanitize

        Returns:
            Sanitized pattern (or original if already safe)
        """
        is_valid, _ = cls.validate(pattern)
        if is_valid:
            return pattern

        # If invalid, escape all special regex characters to make it a literal search
        return re.escape(pattern)
