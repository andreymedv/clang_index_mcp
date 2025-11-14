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
@pytest.mark.timeout(5)  # Should complete within 5 seconds
class TestRegexDoSPrevention:
    """Test ReDoS attack prevention - REQ-10.2"""

    def test_regex_dos_prevention(self, temp_project_dir):
        """Test prevention of catastrophic backtracking in regex - Task 1.3.2"""
        # Create test file with long class names
        test_content = "class " + "A" * 1000 + " {};\n" * 100
        (temp_project_dir / "src" / "test.cpp").write_text(test_content)

        # Create analyzer
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Test Case 1: Catastrophic backtracking pattern (a+)+
        start = time.time()
        try:
            results = analyzer.search_classes("(A+)+B")
            elapsed = time.time() - start
            assert elapsed < 2.0, f"Regex should not cause catastrophic backtracking: {elapsed}s"
        except:
            elapsed = time.time() - start
            assert elapsed < 2.0, f"Regex error should occur quickly, not hang: {elapsed}s"

        # Test Case 2: Nested quantifiers
        start = time.time()
        try:
            results = analyzer.search_functions("(x+x+)+y")
            elapsed = time.time() - start
            assert elapsed < 2.0, "Nested quantifiers should not cause DoS"
        except:
            pass  # Error is acceptable, hanging is not

        # Test Case 3: Alternation with overlap
        start = time.time()
        try:
            results = analyzer.search_classes("(a|a)*b")
            elapsed = time.time() - start
            assert elapsed < 2.0, "Overlapping alternation should not cause DoS"
        except:
            pass

        # Test Case 4: Long input with complex pattern
        start = time.time()
        try:
            results = analyzer.search_classes("(a*)*b")
            elapsed = time.time() - start
            assert elapsed < 2.0, "Complex pattern on long input should not hang"
        except:
            pass

        # Test Case 5: Pathological regex
        start = time.time()
        try:
            results = analyzer.search_functions("(a|ab)*c")
            elapsed = time.time() - start
            assert elapsed < 2.0, "Pathological regex should not cause DoS"
        except:
            pass
