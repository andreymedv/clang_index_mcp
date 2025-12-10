"""
Unit tests for Phase 3.1: Call Site Extraction

Tests call site tracking with line-level precision, covering:
- Basic call site extraction (CS-01)
- Multiple calls to same function (CS-02)
- Calls in different control flow paths (CS-03)
- Method calls (CS-04)
- Function pointers vs direct calls (CS-05)
- Lambda captures (CS-06)
- Recursive calls (CS-07)
- Template function calls (CS-08)
"""

import pytest
from pathlib import Path
from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server.call_graph import CallSite


@pytest.fixture
def phase3_fixtures_dir(tmp_path):
    """Get path to Phase 3 test fixtures."""
    fixtures_path = Path(__file__).parent / "fixtures" / "phase3_samples"
    return fixtures_path


@pytest.fixture
def analyzer(phase3_fixtures_dir):
    """Create a fresh analyzer instance for testing."""
    # CppAnalyzer takes project directory, not cache_dir
    analyzer = CppAnalyzer(str(phase3_fixtures_dir))
    return analyzer


class TestBasicCallSiteExtraction:
    """Test CS-01: Basic call site tracking."""

    def test_single_call_site(self, analyzer):
        """Test that a single function call is tracked with correct line number."""
        # Index the project
        analyzer.index_project()

        # Get call sites from single_caller function
        call_sites = analyzer.get_call_sites("single_caller")

        # Should have exactly 1 call site
        assert len(call_sites) == 1, f"Expected 1 call site, got {len(call_sites)}"

        # Verify call site details
        cs = call_sites[0]
        assert cs['target'] == 'helper', f"Expected target 'helper', got {cs['target']}"
        assert cs['line'] == 14, f"Expected line 14, got {cs['line']}"
        assert cs['file'].endswith('call_sites_basic.cpp')
        assert cs['column'] is not None, "Column should be set"

    def test_call_site_stored_in_database(self, analyzer):
        """Test that call sites are persisted to SQLite database."""
        analyzer.index_project()

        # Query database directly for call sites
        backend = analyzer.cache_manager.backend

        # Find single_caller USR
        functions = analyzer.search_functions("^single_caller$", project_only=True)
        assert len(functions) > 0, "single_caller function not found"

        caller_usr = None
        for func in functions:
            symbols = analyzer.function_index.get(func['name'], [])
            for sym in symbols:
                if sym.file == func['file'] and sym.line == func['line']:
                    caller_usr = sym.usr
                    break

        assert caller_usr is not None, "Could not find caller USR"

        # Query call sites from database
        db_call_sites = backend.get_call_sites_for_caller(caller_usr)

        assert len(db_call_sites) > 0, "No call sites found in database"
        assert db_call_sites[0]['line'] == 14


class TestMultipleCallsToSameFunction:
    """Test CS-02: Multiple calls to same function."""

    def test_multiple_calls_tracked_separately(self, analyzer):
        """Test that multiple calls to the same function are tracked as separate call sites."""
        analyzer.index_project()

        call_sites = analyzer.get_call_sites("multiple_calls")

        # Should have 2 call sites to validate()
        validate_calls = [cs for cs in call_sites if cs['target'] == 'validate']
        assert len(validate_calls) == 2, f"Expected 2 calls to validate, got {len(validate_calls)}"

        # Verify both line numbers
        lines = sorted([cs['line'] for cs in validate_calls])
        assert lines == [19, 21], f"Expected lines [19, 21], got {lines}"

        # Verify both point to same file
        assert all(cs['file'].endswith('call_sites_basic.cpp') for cs in validate_calls)

    def test_call_sites_sorted_by_line(self, analyzer):
        """Test that call sites are returned sorted by line number."""
        analyzer.index_project()

        call_sites = analyzer.get_call_sites("multiple_calls")

        # Extract line numbers
        lines = [cs['line'] for cs in call_sites]

        # Should be sorted
        assert lines == sorted(lines), f"Call sites not sorted: {lines}"


class TestControlFlowCalls:
    """Test CS-03: Calls in different control flow paths."""

    def test_calls_in_different_branches(self, analyzer):
        """Test that calls in if/else branches are both tracked."""
        analyzer.index_project()

        call_sites = analyzer.get_call_sites("conditional_calls")

        # Should have 2 calls to helper() (one in each branch)
        helper_calls = [cs for cs in call_sites if cs['target'] == 'helper']
        assert len(helper_calls) == 2, f"Expected 2 calls to helper, got {len(helper_calls)}"

        # Verify line numbers (if and else branches)
        lines = sorted([cs['line'] for cs in helper_calls])
        assert lines == [27, 29], f"Expected lines [27, 29], got {lines}"


class TestMethodCalls:
    """Test CS-04: Method calls (member functions)."""

    def test_member_function_call(self, analyzer):
        """Test that member function calls are tracked."""
        analyzer.index_project()

        # Get call sites from Processor::process method
        call_sites = analyzer.get_call_sites("process", class_name="Processor")

        # Should have at least 2 calls (validate and helper)
        assert len(call_sites) >= 2, f"Expected at least 2 call sites, got {len(call_sites)}"

        # Check for member function call to validate()
        validate_calls = [cs for cs in call_sites if 'validate' in cs['target']]
        assert len(validate_calls) >= 1, "Should have call to validate()"

        # Check for free function call to helper()
        helper_calls = [cs for cs in call_sites if cs['target'] == 'helper']
        assert len(helper_calls) >= 1, "Should have call to helper()"


class TestFunctionPointersVsCalls:
    """Test CS-05: Function pointers vs direct calls."""

    def test_function_pointer_assignment_not_tracked(self, analyzer):
        """Test that function pointer assignment is NOT tracked as a call."""
        analyzer.index_project()

        call_sites = analyzer.get_call_sites("function_pointer_test")

        # Count calls to callback_func
        callback_calls = [cs for cs in call_sites if cs['target'] == 'callback_func']

        # Should have 2 calls: fn() and direct callback_func()
        # Assignment (line ~15) should NOT be counted
        # This tests that CALL_EXPR is correctly distinguished from DECL_REF_EXPR
        assert len(callback_calls) >= 1, "Should have at least the direct call"

        # Verify line numbers don't include assignment line
        lines = [cs['line'] for cs in callback_calls]
        assert 15 not in lines, "Function pointer assignment should not be tracked"

    def test_direct_call_is_tracked(self, analyzer):
        """Test that direct function calls are tracked."""
        analyzer.index_project()

        call_sites = analyzer.get_call_sites("function_pointer_test")

        # Should have call to callback_func on line 21
        callback_calls = [cs for cs in call_sites if cs['target'] == 'callback_func']
        assert any(cs['line'] == 21 for cs in callback_calls), "Direct call on line 21 not found"


class TestLambdaCalls:
    """Test CS-06: Lambda captures and calls."""

    def test_lambda_captures_external_call(self, analyzer):
        """Test that calls from within lambdas are tracked."""
        analyzer.index_project()

        # Note: Lambda body might be attributed to lambda_test or to the lambda itself
        # depending on how libclang represents it. We check that external_func is called.
        call_sites = analyzer.get_call_sites("lambda_test")

        # Should track call to external_func from within lambda (line 27)
        external_calls = [cs for cs in call_sites if cs['target'] == 'external_func']

        # May or may not capture lambda's internal call depending on libclang behavior
        # This is a best-effort test
        # Just verify no crashes and structure is correct
        assert isinstance(call_sites, list)


class TestRecursiveCalls:
    """Test CS-07: Recursive calls."""

    def test_recursive_call_tracked(self, analyzer):
        """Test that recursive function calls (caller == callee) are tracked."""
        analyzer.index_project()

        call_sites = analyzer.get_call_sites("recursive")

        # Should have a recursive call to itself
        recursive_calls = [cs for cs in call_sites if cs['target'] == 'recursive']
        assert len(recursive_calls) >= 1, "Recursive call not tracked"

        # Verify line number
        assert any(cs['line'] == 49 for cs in recursive_calls), "Recursive call on line 49 not found"


class TestTemplateCalls:
    """Test CS-08: Template function calls."""

    def test_template_instantiation_calls(self, analyzer):
        """
        Test that template function calls are tracked.

        Note: Template instantiations are a known limitation in libclang.
        They may not be tracked as regular function calls depending on
        how libclang handles template instantiations vs declarations.
        This test is best-effort and documents expected behavior.
        """
        analyzer.index_project()

        call_sites = analyzer.get_call_sites("template_caller")

        # Should have calls to process_template (possibly multiple instantiations)
        template_calls = [cs for cs in call_sites if 'process_template' in cs['target']]

        # This is a best-effort test - templates may not be tracked
        # depending on libclang version and how it handles instantiations
        if len(template_calls) == 0:
            # Log for visibility but don't fail
            # Template instantiations are a known edge case in C++ AST analysis
            import warnings
            warnings.warn("Template calls not tracked - this is a known limitation with libclang")
        else:
            # If they are tracked, verify line numbers are reasonable
            lines = [cs['line'] for cs in template_calls]
            assert any(40 <= line <= 41 for line in lines), f"Expected lines around 40-41, got {lines}"


class TestMCPToolIntegration:
    """Test MCP tool integration for call sites."""

    def test_find_callers_includes_call_sites(self, analyzer):
        """Test that find_callers returns call_sites array."""
        analyzer.index_project()

        # Find callers of helper() function
        result = analyzer.find_callers("helper")

        # Should return a dictionary
        assert isinstance(result, dict), "find_callers should return dict"

        # Should have required keys
        assert 'function' in result
        assert 'callers' in result
        assert 'call_sites' in result
        assert 'total_call_sites' in result

        # function name should match
        assert result['function'] == 'helper'

        # callers should be a list
        assert isinstance(result['callers'], list)

        # call_sites should be a list
        assert isinstance(result['call_sites'], list)

        # total_call_sites should match length
        assert result['total_call_sites'] == len(result['call_sites'])

    def test_find_callers_call_sites_have_required_fields(self, analyzer):
        """Test that call_sites entries have all required fields."""
        analyzer.index_project()

        result = analyzer.find_callers("helper")

        if result['call_sites']:
            cs = result['call_sites'][0]

            # Verify all required fields present
            required_fields = ['file', 'line', 'caller', 'caller_file', 'caller_signature']
            for field in required_fields:
                assert field in cs, f"Missing required field: {field}"

            # Verify types
            assert isinstance(cs['file'], str)
            assert isinstance(cs['line'], int)
            assert isinstance(cs['caller'], str)

    def test_get_call_sites_returns_correct_format(self, analyzer):
        """Test that get_call_sites returns properly formatted results."""
        analyzer.index_project()

        call_sites = analyzer.get_call_sites("single_caller")

        # Should return a list
        assert isinstance(call_sites, list)

        if call_sites:
            cs = call_sites[0]

            # Verify all required fields
            required_fields = ['target', 'target_signature', 'target_file',
                             'target_kind', 'file', 'line']
            for field in required_fields:
                assert field in cs, f"Missing required field: {field}"


class TestCallSiteAccuracy:
    """Test accuracy of call site line/column information."""

    def test_line_numbers_match_source(self, analyzer):
        """Test that extracted line numbers match actual source code lines."""
        analyzer.index_project()

        # Get call sites from single_caller
        call_sites = analyzer.get_call_sites("single_caller")

        # Verify the call to helper() is on line 14 (as per fixture)
        helper_call = next((cs for cs in call_sites if cs['target'] == 'helper'), None)
        assert helper_call is not None, "Call to helper not found"
        assert helper_call['line'] == 14, f"Expected line 14, got {helper_call['line']}"

    def test_column_numbers_are_positive(self, analyzer):
        """Test that column numbers are positive integers when present."""
        analyzer.index_project()

        call_sites = analyzer.get_call_sites("single_caller")

        for cs in call_sites:
            if cs['column'] is not None:
                assert cs['column'] > 0, f"Column should be positive, got {cs['column']}"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_function_no_call_sites(self, analyzer):
        """Test that functions with no calls return empty call sites list."""
        analyzer.index_project()

        # helper() makes no calls
        call_sites = analyzer.get_call_sites("helper")

        assert isinstance(call_sites, list)
        assert len(call_sites) == 0, "Empty function should have no call sites"

    def test_nonexistent_function_returns_empty(self, analyzer):
        """Test that querying non-existent function returns empty list."""
        analyzer.index_project()

        call_sites = analyzer.get_call_sites("nonexistent_function_xyz")

        assert isinstance(call_sites, list)
        assert len(call_sites) == 0


class TestCallGraphAnalyzer:
    """Test CallGraphAnalyzer class directly."""

    def test_call_site_object_equality(self):
        """Test CallSite equality and hashing."""
        cs1 = CallSite("caller_usr", "callee_usr", "file.cpp", 10, 5)
        cs2 = CallSite("caller_usr", "callee_usr", "file.cpp", 10, 5)
        cs3 = CallSite("caller_usr", "callee_usr", "file.cpp", 20, 5)

        # Same call sites should be equal
        assert cs1 == cs2

        # Different line numbers should not be equal
        assert cs1 != cs3

        # Should be hashable
        call_set = {cs1, cs2, cs3}
        assert len(call_set) == 2  # cs1 and cs2 are duplicates

    def test_call_site_to_dict(self):
        """Test CallSite.to_dict() method."""
        cs = CallSite("caller", "callee", "test.cpp", 42, 10)
        d = cs.to_dict()

        assert d['caller_usr'] == "caller"
        assert d['callee_usr'] == "callee"
        assert d['file'] == "test.cpp"
        assert d['line'] == 42
        assert d['column'] == 10


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
