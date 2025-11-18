"""
Security Tests - Regex Security

Tests for ReDoS (Regular Expression Denial of Service) prevention.

Requirements: REQ-10.2 (Regex Security)
Priority: P0 - CRITICAL
"""

import pytest
import time

# Import test infrastructure
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server.regex_validator import RegexValidator, RegexValidationError


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
        """Test that safe regex patterns are allowed - Task 1.3.2"""
        # Create test file
        test_content = "class TestClass {};\nclass AnotherClass {};"
        (temp_project_dir / "src" / "test.cpp").write_text(test_content)

        # Create analyzer
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Safe patterns should work without exceptions
        results = analyzer.search_classes("Test.*")
        assert len(results) >= 0  # Should complete successfully

        results = analyzer.search_classes(".*Class")
        assert len(results) >= 0

        results = analyzer.search_functions("[a-zA-Z]+")
        assert len(results) >= 0

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
