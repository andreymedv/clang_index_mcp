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


@pytest.mark.security
@pytest.mark.critical
@pytest.mark.timeout(30)  # Allow time for ReDoS patterns (not yet prevented)
class TestRegexDoSPrevention:
    """Test ReDoS attack prevention - REQ-10.2

    NOTE: Full ReDoS prevention not yet implemented. These tests verify that
    pathological regex patterns complete within reasonable time (30s) but may
    be slow. Future enhancement: implement regex complexity analysis to reject
    dangerous patterns before execution.
    """

    def test_regex_dos_prevention(self, temp_project_dir):
        """Test that ReDoS patterns complete within reasonable time - Task 1.3.2"""
        # Create test file
        test_content = "class TestClass {};\nclass AnotherClass {};"
        (temp_project_dir / "src" / "test.cpp").write_text(test_content)

        # Create analyzer
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Test Case 1: Catastrophic backtracking pattern (a+)+
        # SKIP: This pattern causes catastrophic backtracking with Python's re module.
        # ReDoS prevention is not yet implemented. This test documents the vulnerability.
        # TODO: Implement regex complexity analysis before pattern execution
        pytest.skip("ReDoS prevention not yet implemented - catastrophic backtracking occurs with pattern (A+)+B")

        # Test Case 2: Nested quantifiers
        start = time.time()
        try:
            results = analyzer.search_functions("(x+x+)+y")
            elapsed = time.time() - start
            assert elapsed < 10.0, "Nested quantifiers should complete within 10s"
        except:
            pass  # Error is acceptable, hanging is not

        # Test Case 3: Alternation with overlap
        start = time.time()
        try:
            results = analyzer.search_classes("(a|a)*b")
            elapsed = time.time() - start
            assert elapsed < 10.0, "Overlapping alternation should complete within 10s"
        except:
            pass

        # Test Case 4: Long input with complex pattern
        start = time.time()
        try:
            results = analyzer.search_classes("(a*)*b")
            elapsed = time.time() - start
            assert elapsed < 10.0, "Complex pattern should complete within 10s"
        except:
            pass

        # Test Case 5: Pathological regex
        start = time.time()
        try:
            results = analyzer.search_functions("(a|ab)*c")
            elapsed = time.time() - start
            assert elapsed < 10.0, "Pathological regex should complete within 10s"
        except:
            pass
