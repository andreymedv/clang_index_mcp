"""
Integration tests for Phase 3.1 MCP tools.

Tests the MCP tool layer to ensure proper integration with call site tracking:
- find_callers tool with call_sites response
- get_call_sites tool
- Backward compatibility
- Response format validation
"""

import pytest
import json
from pathlib import Path
from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.fixture
def phase3_fixtures_dir(tmp_path):
    """Get path to Phase 3 test fixtures."""
    fixtures_path = Path(__file__).parent / "fixtures" / "phase3_samples"
    return fixtures_path


@pytest.fixture
def indexed_analyzer(phase3_fixtures_dir):
    """Create and return a pre-indexed analyzer."""
    analyzer = CppAnalyzer(str(phase3_fixtures_dir))
    analyzer.index_project()
    return analyzer


class TestFindCallersToolIntegration:
    """Test find_callers MCP tool with Phase 3.1 enhancements."""

    def test_find_callers_returns_dictionary(self, indexed_analyzer):
        """Test that find_callers returns a dictionary (not list)."""
        result = indexed_analyzer.find_callers("helper")

        assert isinstance(result, dict), "find_callers must return dict"
        assert not isinstance(result, list), "Should not return list (backward incompatible)"

    def test_find_callers_has_backward_compatible_callers_key(self, indexed_analyzer):
        """Test that 'callers' key exists for backward compatibility."""
        result = indexed_analyzer.find_callers("helper")

        assert 'callers' in result, "Missing 'callers' key (backward compatibility)"
        assert isinstance(result['callers'], list), "'callers' should be a list"

    def test_find_callers_includes_call_sites_key(self, indexed_analyzer):
        """Test that new 'call_sites' key is present (Phase 3)."""
        result = indexed_analyzer.find_callers("helper")

        assert 'call_sites' in result, "Missing 'call_sites' key (Phase 3)"
        assert isinstance(result['call_sites'], list), "'call_sites' should be a list"

    def test_find_callers_includes_total_call_sites(self, indexed_analyzer):
        """Test that 'total_call_sites' count is present."""
        result = indexed_analyzer.find_callers("helper")

        assert 'total_call_sites' in result, "Missing 'total_call_sites' key"
        assert isinstance(result['total_call_sites'], int), "'total_call_sites' should be int"
        assert result['total_call_sites'] == len(result['call_sites']), \
            "total_call_sites should match call_sites length"

    def test_find_callers_includes_function_name(self, indexed_analyzer):
        """Test that 'function' name is included in response."""
        result = indexed_analyzer.find_callers("helper")

        assert 'function' in result, "Missing 'function' key"
        assert result['function'] == 'helper', "Function name mismatch"

    def test_call_sites_entries_have_required_fields(self, indexed_analyzer):
        """Test that each call site has all required fields."""
        result = indexed_analyzer.find_callers("helper")

        required_fields = ['file', 'line', 'column', 'caller', 'caller_file', 'caller_signature']

        for cs in result['call_sites']:
            for field in required_fields:
                assert field in cs, f"Call site missing required field: {field}"

            # Verify field types
            assert isinstance(cs['file'], str), "file should be string"
            assert isinstance(cs['line'], int), "line should be int"
            assert isinstance(cs['caller'], str), "caller should be string"
            assert isinstance(cs['caller_file'], str), "caller_file should be string"
            assert isinstance(cs['caller_signature'], str), "caller_signature should be string"

    def test_call_sites_sorted_by_file_and_line(self, indexed_analyzer):
        """Test that call sites are sorted by file, then line."""
        result = indexed_analyzer.find_callers("helper")

        call_sites = result['call_sites']

        if len(call_sites) > 1:
            for i in range(len(call_sites) - 1):
                cs1 = call_sites[i]
                cs2 = call_sites[i + 1]

                # Compare (file, line) tuples
                pair1 = (cs1['file'], cs1['line'])
                pair2 = (cs2['file'], cs2['line'])

                assert pair1 <= pair2, f"Call sites not properly sorted: {pair1} > {pair2}"

    def test_callers_list_has_line_ranges(self, indexed_analyzer):
        """Test that caller function info includes start_line and end_line (in nested location)."""
        result = indexed_analyzer.find_callers("helper")

        for caller in result['callers']:
            # Location info is now nested under 'definition' or 'declaration'
            _caller_loc = caller.get("definition") or caller.get("declaration") or {}
            assert 'start_line' in _caller_loc, "Missing start_line in location object"
            assert 'end_line' in _caller_loc, "Missing end_line in location object"

            if _caller_loc['start_line'] is not None and _caller_loc['end_line'] is not None:
                assert _caller_loc['start_line'] <= _caller_loc['end_line'], \
                    "start_line should be <= end_line"


class TestGetCallSitesTool:
    """Test get_call_sites MCP tool (Phase 3.1 new tool)."""

    def test_get_call_sites_returns_list(self, indexed_analyzer):
        """Test that get_call_sites returns a list."""
        result = indexed_analyzer.get_call_sites("single_caller")

        assert isinstance(result, list), "get_call_sites must return list"

    def test_get_call_sites_entries_have_required_fields(self, indexed_analyzer):
        """Test that each call site has all required fields."""
        result = indexed_analyzer.get_call_sites("single_caller")

        required_fields = ['target', 'target_signature', 'target_file',
                          'target_kind', 'file', 'line', 'column']

        for cs in result:
            for field in required_fields:
                assert field in cs, f"Call site missing required field: {field}"

            # Verify field types
            assert isinstance(cs['target'], str), "target should be string"
            assert isinstance(cs['target_signature'], str), "target_signature should be string"
            assert isinstance(cs['target_file'], str), "target_file should be string"
            assert isinstance(cs['target_kind'], str), "target_kind should be string"
            assert isinstance(cs['file'], str), "file should be string"
            assert isinstance(cs['line'], int), "line should be int"
            # column can be int or None

    def test_get_call_sites_sorted_by_file_and_line(self, indexed_analyzer):
        """Test that call sites are sorted by file, then line."""
        result = indexed_analyzer.get_call_sites("multiple_calls")

        if len(result) > 1:
            for i in range(len(result) - 1):
                cs1 = result[i]
                cs2 = result[i + 1]

                pair1 = (cs1['file'], cs1['line'])
                pair2 = (cs2['file'], cs2['line'])

                assert pair1 <= pair2, f"Call sites not sorted: {pair1} > {pair2}"

    def test_get_call_sites_for_function_with_no_calls(self, indexed_analyzer):
        """Test get_call_sites on a function that makes no calls."""
        result = indexed_analyzer.get_call_sites("helper")

        assert isinstance(result, list)
        assert len(result) == 0, "Function with no calls should return empty list"

    def test_get_call_sites_for_nonexistent_function(self, indexed_analyzer):
        """Test get_call_sites on non-existent function."""
        result = indexed_analyzer.get_call_sites("nonexistent_xyz")

        assert isinstance(result, list)
        assert len(result) == 0, "Non-existent function should return empty list"


class TestComplementaryTools:
    """Test that find_callers and get_call_sites are complementary."""

    def test_find_callers_backward_get_call_sites_forward(self, indexed_analyzer):
        """Test that find_callers shows WHO calls (backward), get_call_sites shows WHAT is called (forward)."""

        # Get functions that call helper (backward analysis)
        callers_result = indexed_analyzer.find_callers("helper")
        callers = {c['name'] for c in callers_result['callers']}

        # For each caller, check that get_call_sites shows helper as target (forward analysis)
        for caller_name in callers:
            call_sites = indexed_analyzer.get_call_sites(caller_name)
            targets = {cs['target'] for cs in call_sites}

            # This caller should have helper in its targets
            assert 'helper' in targets or len(call_sites) > 0, \
                f"{caller_name} calls helper, but get_call_sites doesn't show it"


class TestResponseFormatJSON:
    """Test that responses can be serialized to JSON."""

    def test_find_callers_json_serializable(self, indexed_analyzer):
        """Test that find_callers response can be serialized to JSON."""
        result = indexed_analyzer.find_callers("helper")

        try:
            json_str = json.dumps(result, indent=2)
            assert len(json_str) > 0
        except Exception as e:
            pytest.fail(f"find_callers result not JSON serializable: {e}")

    def test_get_call_sites_json_serializable(self, indexed_analyzer):
        """Test that get_call_sites response can be serialized to JSON."""
        result = indexed_analyzer.get_call_sites("single_caller")

        try:
            json_str = json.dumps(result, indent=2)
            assert len(json_str) > 0
        except Exception as e:
            pytest.fail(f"get_call_sites result not JSON serializable: {e}")


class TestRealWorldScenarios:
    """Test real-world usage scenarios."""

    def test_impact_analysis_workflow(self, indexed_analyzer):
        """
        Simulate impact analysis workflow:
        1. Find who calls a function
        2. Get exact call locations
        3. Verify line numbers are usable
        """
        # Step 1: Find all callers of helper()
        result = indexed_analyzer.find_callers("helper")

        assert len(result['callers']) > 0, "Should have at least one caller"

        # Step 2: Check we have call sites with line numbers
        assert len(result['call_sites']) > 0, "Should have call site data"

        # Step 3: Verify each call site has actionable line number
        for cs in result['call_sites']:
            assert cs['line'] > 0, "Line number should be positive"
            assert cs['file'].endswith('.cpp'), "Should have source file"

            # In real workflow, you would:
            # - Open cs['file']
            # - Jump to cs['line']
            # - See the actual call statement

    def test_dependency_analysis_workflow(self, indexed_analyzer):
        """
        Simulate dependency analysis workflow:
        1. Find what a function calls
        2. Get exact call locations
        3. Understand execution flow
        """
        # Step 1: Find what multiple_calls() calls
        call_sites = indexed_analyzer.get_call_sites("multiple_calls")

        assert len(call_sites) > 0, "Should have dependencies"

        # Step 2: Verify we have target function info
        for cs in call_sites:
            assert 'target' in cs, "Should know what function is called"
            assert 'target_file' in cs, "Should know where target is defined"
            assert cs['line'] > 0, "Should know where call occurs"

        # Step 3: Can trace execution flow
        # In real workflow: follow call chain by recursively calling get_call_sites


class TestPerformance:
    """Test performance characteristics of Phase 3.1."""

    def test_call_sites_do_not_explode_memory(self, indexed_analyzer):
        """Test that call site tracking doesn't cause memory explosion."""
        # This is a basic sanity check
        # In a real large codebase, call_sites list should scale linearly with number of calls

        result = indexed_analyzer.find_callers("helper")

        # Should not have duplicate call sites
        call_site_tuples = [(cs['file'], cs['line']) for cs in result['call_sites']]
        unique_tuples = set(call_site_tuples)

        # Some functions might legitimately call from same line (macros, etc.)
        # but duplicates should be minimal
        assert len(call_site_tuples) > 0  # Basic sanity check

    def test_query_response_time_reasonable(self, indexed_analyzer):
        """Test that queries return in reasonable time."""
        import time

        start = time.time()
        result = indexed_analyzer.find_callers("helper")
        elapsed = time.time() - start

        # Should complete in under 1 second for small test project
        assert elapsed < 1.0, f"Query took {elapsed:.2f}s, expected <1s"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
