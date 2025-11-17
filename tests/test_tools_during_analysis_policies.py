#!/usr/bin/env python3
"""
Tests for query behavior policy configuration (REQ-10.7.x)

Tests that query behavior policies (allow_partial, block, reject) work correctly
and can be configured via config file and environment variables.
"""

import os
import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from mcp_server.cpp_analyzer_config import CppAnalyzerConfig
from mcp_server.state_manager import (
    AnalyzerStateManager, AnalyzerState, QueryBehaviorPolicy
)


@pytest.fixture
def temp_project_with_config(tmp_path):
    """Create a temporary project with config support"""
    project = tmp_path / "project"
    project.mkdir()

    # Create a simple C++ file
    (project / "main.cpp").write_text("int main() { return 0; }")

    return project


def test_query_behavior_policy_enum():
    """Test QueryBehaviorPolicy enum values"""
    assert QueryBehaviorPolicy.ALLOW_PARTIAL.value == "allow_partial"
    assert QueryBehaviorPolicy.BLOCK.value == "block"
    assert QueryBehaviorPolicy.REJECT.value == "reject"


def test_config_default_query_behavior(temp_project_with_config):
    """Test that default query behavior is allow_partial"""
    config = CppAnalyzerConfig(temp_project_with_config)

    policy = config.get_query_behavior_policy()
    assert policy == "allow_partial", "Default policy should be allow_partial"


def test_config_file_query_behavior(temp_project_with_config):
    """Test reading query_behavior from config file"""
    # Create config file with block policy
    config_file = temp_project_with_config / ".cpp-analyzer-config.json"
    config_data = {
        "query_behavior": "block"
    }
    config_file.write_text(json.dumps(config_data))

    # Load config
    config = CppAnalyzerConfig(temp_project_with_config)

    policy = config.get_query_behavior_policy()
    assert policy == "block", "Should read policy from config file"


def test_config_file_reject_policy(temp_project_with_config):
    """Test reject policy from config file"""
    config_file = temp_project_with_config / ".cpp-analyzer-config.json"
    config_data = {
        "query_behavior": "reject"
    }
    config_file.write_text(json.dumps(config_data))

    config = CppAnalyzerConfig(temp_project_with_config)
    policy = config.get_query_behavior_policy()
    assert policy == "reject", "Should read reject policy from config file"


def test_env_var_overrides_config_file(temp_project_with_config):
    """Test that CPP_ANALYZER_QUERY_BEHAVIOR env var overrides config file"""
    # Create config file with allow_partial
    config_file = temp_project_with_config / ".cpp-analyzer-config.json"
    config_data = {
        "query_behavior": "allow_partial"
    }
    config_file.write_text(json.dumps(config_data))

    # Set environment variable to block
    with patch.dict(os.environ, {'CPP_ANALYZER_QUERY_BEHAVIOR': 'block'}):
        config = CppAnalyzerConfig(temp_project_with_config)
        policy = config.get_query_behavior_policy()
        assert policy == "block", "Env var should override config file"


def test_env_var_case_insensitive(temp_project_with_config):
    """Test that env var is case-insensitive"""
    with patch.dict(os.environ, {'CPP_ANALYZER_QUERY_BEHAVIOR': 'BLOCK'}):
        config = CppAnalyzerConfig(temp_project_with_config)
        policy = config.get_query_behavior_policy()
        assert policy == "block", "Env var should be case-insensitive"


def test_invalid_config_value_defaults_to_allow_partial(temp_project_with_config):
    """Test that invalid config value defaults to allow_partial"""
    config_file = temp_project_with_config / ".cpp-analyzer-config.json"
    config_data = {
        "query_behavior": "invalid_value"
    }
    config_file.write_text(json.dumps(config_data))

    config = CppAnalyzerConfig(temp_project_with_config)
    policy = config.get_query_behavior_policy()
    assert policy == "allow_partial", "Invalid value should default to allow_partial"


def test_invalid_env_var_falls_back_to_config(temp_project_with_config):
    """Test that invalid env var falls back to config file"""
    config_file = temp_project_with_config / ".cpp-analyzer-config.json"
    config_data = {
        "query_behavior": "reject"
    }
    config_file.write_text(json.dumps(config_data))

    with patch.dict(os.environ, {'CPP_ANALYZER_QUERY_BEHAVIOR': 'invalid'}):
        config = CppAnalyzerConfig(temp_project_with_config)
        policy = config.get_query_behavior_policy()
        assert policy == "reject", "Invalid env var should fall back to config"


def test_priority_order_env_config_default(temp_project_with_config):
    """Test complete priority order: env > config > default"""
    # Test 1: Only default (no config, no env)
    config = CppAnalyzerConfig(temp_project_with_config)
    assert config.get_query_behavior_policy() == "allow_partial"

    # Test 2: Config overrides default
    config_file = temp_project_with_config / ".cpp-analyzer-config.json"
    config_data = {"query_behavior": "block"}
    config_file.write_text(json.dumps(config_data))

    config = CppAnalyzerConfig(temp_project_with_config)
    assert config.get_query_behavior_policy() == "block"

    # Test 3: Env overrides config
    with patch.dict(os.environ, {'CPP_ANALYZER_QUERY_BEHAVIOR': 'reject'}):
        config = CppAnalyzerConfig(temp_project_with_config)
        assert config.get_query_behavior_policy() == "reject"


def test_state_manager_ready_for_queries():
    """Test state manager ready_for_queries check"""
    state_manager = AnalyzerStateManager()

    # UNINITIALIZED - not ready
    state_manager.transition_to(AnalyzerState.UNINITIALIZED)
    assert not state_manager.is_ready_for_queries()

    # INITIALIZING - not ready
    state_manager.transition_to(AnalyzerState.INITIALIZING)
    assert not state_manager.is_ready_for_queries()

    # INDEXING - ready (partial results)
    state_manager.transition_to(AnalyzerState.INDEXING)
    assert state_manager.is_ready_for_queries()

    # INDEXED - ready (complete results)
    state_manager.transition_to(AnalyzerState.INDEXED)
    assert state_manager.is_ready_for_queries()

    # REFRESHING - ready
    state_manager.transition_to(AnalyzerState.REFRESHING)
    assert state_manager.is_ready_for_queries()

    # ERROR - not ready
    state_manager.transition_to(AnalyzerState.ERROR)
    assert not state_manager.is_ready_for_queries()


def test_state_manager_fully_indexed_check():
    """Test state manager is_fully_indexed check"""
    state_manager = AnalyzerStateManager()

    # Only INDEXED state is fully indexed
    state_manager.transition_to(AnalyzerState.UNINITIALIZED)
    assert not state_manager.is_fully_indexed()

    state_manager.transition_to(AnalyzerState.INITIALIZING)
    assert not state_manager.is_fully_indexed()

    state_manager.transition_to(AnalyzerState.INDEXING)
    assert not state_manager.is_fully_indexed()

    state_manager.transition_to(AnalyzerState.INDEXED)
    assert state_manager.is_fully_indexed()

    state_manager.transition_to(AnalyzerState.REFRESHING)
    assert not state_manager.is_fully_indexed()


def test_example_config_includes_query_behavior(temp_project_with_config):
    """Test that example config includes query_behavior field"""
    config = CppAnalyzerConfig(temp_project_with_config)

    # Create example config
    example_path = config.create_example_config(location='project')

    # Read it back
    with open(example_path) as f:
        example_data = json.load(f)

    assert "query_behavior" in example_data, "Example config should include query_behavior"
    assert example_data["query_behavior"] == "allow_partial"
    assert "_query_behavior_options" in example_data, "Should include options documentation"


def test_all_three_policy_values_valid():
    """Test that all three policy enum values can be created"""
    try:
        policy1 = QueryBehaviorPolicy("allow_partial")
        policy2 = QueryBehaviorPolicy("block")
        policy3 = QueryBehaviorPolicy("reject")

        assert policy1 == QueryBehaviorPolicy.ALLOW_PARTIAL
        assert policy2 == QueryBehaviorPolicy.BLOCK
        assert policy3 == QueryBehaviorPolicy.REJECT
    except ValueError:
        pytest.fail("All three policy values should be valid")


def test_invalid_policy_value_raises():
    """Test that invalid policy value raises ValueError"""
    with pytest.raises(ValueError):
        QueryBehaviorPolicy("invalid_policy")


def test_config_with_all_three_policies(temp_project_with_config):
    """Test loading config with each of the three policy values"""
    for policy_value in ["allow_partial", "block", "reject"]:
        config_file = temp_project_with_config / ".cpp-analyzer-config.json"
        config_data = {"query_behavior": policy_value}
        config_file.write_text(json.dumps(config_data))

        config = CppAnalyzerConfig(temp_project_with_config)
        assert config.get_query_behavior_policy() == policy_value


def test_wait_for_indexed_timeout():
    """Test state manager wait_for_indexed with timeout"""
    state_manager = AnalyzerStateManager()

    # Start in INDEXING state
    state_manager.transition_to(AnalyzerState.INDEXING)

    # Wait with short timeout - should timeout
    result = state_manager.wait_for_indexed(timeout=0.1)
    assert not result, "Should timeout when indexing not complete"

    # Transition to INDEXED
    state_manager.transition_to(AnalyzerState.INDEXED)

    # Wait should succeed immediately
    result = state_manager.wait_for_indexed(timeout=0.1)
    assert result, "Should succeed when already indexed"


def test_wait_for_indexed_no_timeout():
    """Test wait_for_indexed without timeout (should work immediately if indexed)"""
    state_manager = AnalyzerStateManager()

    # Already indexed
    state_manager.transition_to(AnalyzerState.INDEXED)

    # Should return True immediately
    result = state_manager.wait_for_indexed(timeout=None)
    assert result, "Should succeed immediately when already indexed"


def test_policy_enforcement_logic_simulation():
    """Test policy enforcement logic without MCP server dependency"""
    # This test simulates the policy enforcement logic
    # without requiring the full MCP server

    from mcp_server.cpp_analyzer import CppAnalyzer

    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir) / "project"
        project.mkdir()
        (project / "main.cpp").write_text("int main() {}")

        # Create analyzer and state manager
        analyzer = CppAnalyzer(str(project))
        state_manager = AnalyzerStateManager()

        # Helper function to simulate policy check
        def simulate_policy_check(state: AnalyzerState, policy_str: str):
            """Simulate the check_query_policy logic"""
            # If fully indexed, always allow
            if state == AnalyzerState.INDEXED:
                return True

            # If not ready for queries, allow (will be caught by other checks)
            if state not in (AnalyzerState.INDEXING, AnalyzerState.INDEXED, AnalyzerState.REFRESHING):
                return True

            # Check policy
            try:
                policy = QueryBehaviorPolicy(policy_str)
            except ValueError:
                policy = QueryBehaviorPolicy.ALLOW_PARTIAL

            if policy == QueryBehaviorPolicy.ALLOW_PARTIAL:
                return True
            elif policy == QueryBehaviorPolicy.BLOCK:
                # In real code, this would wait - for test, just return False
                return False
            elif policy == QueryBehaviorPolicy.REJECT:
                return False

            return True

        # Test 1: Fully indexed - always allow
        result = simulate_policy_check(AnalyzerState.INDEXED, "allow_partial")
        assert result, "Should allow when fully indexed"

        result = simulate_policy_check(AnalyzerState.INDEXED, "reject")
        assert result, "Should allow when fully indexed even with reject policy"

        # Test 2: Indexing with allow_partial - allow
        result = simulate_policy_check(AnalyzerState.INDEXING, "allow_partial")
        assert result, "Should allow with allow_partial policy"

        # Test 3: Indexing with block - block (returns False in test)
        result = simulate_policy_check(AnalyzerState.INDEXING, "block")
        assert not result, "Should block with block policy"

        # Test 4: Indexing with reject - reject
        result = simulate_policy_check(AnalyzerState.INDEXING, "reject")
        assert not result, "Should reject with reject policy"

        # Test 5: Uninitialized state - allow (will be caught elsewhere)
        result = simulate_policy_check(AnalyzerState.UNINITIALIZED, "reject")
        assert result, "Should allow for uninitialized (other checks will catch it)"
