"""
Security Tests - Regex Security

Tests for ReDoS (Regular Expression Denial of Service) prevention.

Requirements: REQ-10.2 (Regex Security)
Priority: P0 - CRITICAL
"""

import os

# Import test infrastructure
import sys

import pytest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from clang_index_mcp.cpp_analyzer import CppAnalyzer
from clang_index_mcp._core.regex_validator import RegexValidationError, RegexValidator


@pytest.mark.security
@pytest.mark.critical
@pytest.mark.timeout(5)  # Should reject dangerous patterns immediately
class TestRegexDoSPrevention:
    """Test ReDoS attack prevention - REQ-10.2

    Tests verify that regex patterns are validated before execution to prevent
    catastrophic backtracking and DoS attacks.
    """

    def test_regex_dos_prevention(self, temp_project_dir):
        """Test that dangerous ReDoS patterns are rejected - Task 1.3.2"""
        # Create test file
        test_content = "class TestClass {};\nclass AnotherClass {};"
        (temp_project_dir / "src" / "test.cpp").write_text(test_content)

        # Create analyzer
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Test Case 1: Catastrophic backtracking pattern (a+)+
        with pytest.raises(RegexValidationError, match="Dangerous pattern|too complex"):
            analyzer.search_functions("(a+)+b")

        # Test Case 2: Nested quantifiers
        with pytest.raises(RegexValidationError, match="Dangerous pattern|too complex"):
            analyzer.search_functions("(x+x+)+y")

        # Test Case 3: Alternation with overlap
        with pytest.raises(RegexValidationError, match="Dangerous pattern|too complex"):
            analyzer.search_classes("(a|a)*b")

        # Test Case 4: Nested star quantifiers
        with pytest.raises(RegexValidationError, match="Dangerous pattern|too complex"):
            analyzer.search_classes("(a*)*b")

        # Test Case 5: Multiple nested quantifiers
        with pytest.raises(RegexValidationError, match="Dangerous pattern|too complex"):
            analyzer.search_functions("(a*)+c")

    def test_safe_patterns_allowed(self, temp_project_dir):
        """Verify safe regex patterns are accepted and don't trigger ReDoS protection.

        Security requirement: Patterns without nested quantifiers or catastrophic
        backtracking risk must be allowed through the validator. If they were
        incorrectly rejected, it would be a false-positive denial of service.
        """
        # Create test file
        test_content = "class TestClass {};\nclass AnotherClass {};"
        (temp_project_dir / "src" / "test.cpp").write_text(test_content)

        # Create analyzer
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Security assertion: safe patterns must complete without RegexValidationError.
        # They must return a list (not raise). verify results are a list type.
        results = analyzer.search_classes("Test.*")
        assert isinstance(results, (list, tuple)), "Safe pattern must return list, not raise"
        # Class "TestClass" should match "Test.*"
        flat = results[0] if isinstance(results, tuple) else results
        assert len(flat) >= 1, "Safe pattern 'Test.*' should find TestClass"

        results = analyzer.search_classes(".*Class")
        assert isinstance(results, (list, tuple)), "Safe pattern must return list, not raise"
        flat = results[0] if isinstance(results, tuple) else results
        assert len(flat) >= 1, "Safe pattern '.*Class' should find TestClass and AnotherClass"

        results = analyzer.search_functions("[a-zA-Z]+")
        assert isinstance(results, (list, tuple)), "Safe pattern must return list, not raise"

    def test_contains_pattern_allowed(self, temp_project_dir):
        """Verify .*X.* 'contains' patterns are accepted and find matching symbols.

        Security requirement: The .*X.* pattern is the most natural regex for
        'find symbols containing X' and must not be rejected as ReDoS. It uses
        independent quantifiers (no nested backtracking). False rejection would
        block legitimate searches. Additionally, verify that allowed patterns
        actually return the expected results.
        """
        test_content = "class TestClass {};\nclass AnotherClass {};"
        (temp_project_dir / "src" / "test.cpp").write_text(test_content)

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # .*X.* pattern: the most common "contains" search
        results = analyzer.search_classes(".*Test.*")
        assert len(results) >= 1

        results = analyzer.search_classes(".*Class.*")
        assert len(results) >= 1

        # Prefix and suffix wildcards
        results = analyzer.search_classes(".*Class")
        assert len(results) >= 1

        results = analyzer.search_classes("Test.*")
        assert len(results) >= 1

        # Multiple independent quantifiers on functions — must not be rejected as ReDoS
        results = analyzer.search_functions(".*get.*")
        assert isinstance(results, (list, tuple)), "Contains pattern must return list, not raise"

    def test_validator_contains_patterns_safe(self):
        """Test that .*X.* patterns pass validation.

        These are the most common regex patterns for 'contains' search.
        They are safe (no exponential backtracking) and must be allowed.
        """
        # .*X.* patterns: safe, quantifiers on independent atoms
        safe_patterns = [
            ".*Reporter.*",
            ".*Base.*",
            ".*Test.*",
            ".*get.*set.*",
            ".*foo.*bar.*baz.*",
            ".*Class",
            "Test.*",
            "[a-z]+.*[A-Z]+",
            "prefix.*middle.*suffix",
        ]
        for pattern in safe_patterns:
            is_valid, error = RegexValidator.validate(pattern)
            assert is_valid, f"Pattern '{pattern}' should be valid but got: {error}"

    def test_validator_complexity_analysis(self):
        """Test the complexity analysis function"""
        # Simple patterns should have low scores
        assert RegexValidator.analyze_complexity("test") < 5
        assert RegexValidator.analyze_complexity("test.*") < 10

        # Nested quantifiers should have high scores
        assert RegexValidator.analyze_complexity("(a+)+") > 50
        assert RegexValidator.analyze_complexity("(a*)*") > 50

        # Alternation with quantifiers should have high scores
        assert RegexValidator.analyze_complexity("(a|a)*") > 20

    def test_validator_sanitize(self):
        """Test pattern sanitization"""
        # Safe patterns should pass through unchanged
        safe_pattern = "TestClass"
        assert RegexValidator.sanitize(safe_pattern) == safe_pattern

        # Dangerous patterns should be escaped
        dangerous_pattern = "(a+)+"
        sanitized = RegexValidator.sanitize(dangerous_pattern)
        assert sanitized != dangerous_pattern
        assert sanitized == r"\(a\+\)\+"  # All special chars escaped
