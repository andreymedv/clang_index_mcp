"""
Tests for Search Result Metadata Enhancements

Tests the "silence = success" design principle:
- Normal results (1-20 items, fully indexed): no metadata
- Special conditions trigger metadata:
  - empty: no results found
  - truncated: max_results limit applied
  - large: >20 results without max_results
  - partial: indexing incomplete
"""

import json
import pytest
from unittest.mock import Mock, patch

from mcp_server.state_manager import (
    EnhancedQueryResult,
    QueryCompletenessStatus,
    QueryMetadata,
    AnalyzerStateManager,
    AnalyzerState,
    IndexingProgress,
)


class TestEnhancedQueryResultFactoryMethods:
    """Test factory methods for creating EnhancedQueryResult instances"""

    def test_create_normal_no_metadata(self):
        """Normal results should have no metadata (silence = success)"""
        data = [{"name": "TestClass", "file": "test.h"}]
        result = EnhancedQueryResult.create_normal(data)

        output = result.to_dict()
        assert "data" in output
        assert output["data"] == data
        assert "metadata" not in output, "Normal results should have no metadata"

    def test_create_empty_with_suggestions(self):
        """Empty results should include status and suggestions"""
        data = []
        result = EnhancedQueryResult.create_empty(data)

        output = result.to_dict()
        assert output["data"] == []
        assert "metadata" in output
        assert output["metadata"]["status"] == "empty"
        assert "suggestions" in output["metadata"]
        assert len(output["metadata"]["suggestions"]) > 0

    def test_create_empty_with_custom_suggestions(self):
        """Empty results can have custom suggestions"""
        data = []
        custom_suggestions = ["Try a different pattern", "Check file name"]
        result = EnhancedQueryResult.create_empty(data, suggestions=custom_suggestions)

        output = result.to_dict()
        assert output["metadata"]["suggestions"] == custom_suggestions

    def test_create_truncated_with_counts(self):
        """Truncated results should include returned and total_matches"""
        data = [{"name": f"Class{i}"} for i in range(10)]
        result = EnhancedQueryResult.create_truncated(data, returned=10, total_matches=50)

        output = result.to_dict()
        assert output["data"] == data
        assert "metadata" in output
        assert output["metadata"]["status"] == "truncated"
        assert output["metadata"]["returned"] == 10
        assert output["metadata"]["total_matches"] == 50

    def test_create_large_with_hint(self):
        """Large results should include result_count and hint"""
        data = [{"name": f"Class{i}"} for i in range(30)]
        result = EnhancedQueryResult.create_large(data, result_count=30)

        output = result.to_dict()
        assert output["data"] == data
        assert "metadata" in output
        assert output["metadata"]["status"] == "large"
        assert output["metadata"]["result_count"] == 30
        assert "hint" in output["metadata"]
        assert "max_results" in output["metadata"]["hint"]


class TestEnhancedQueryResultFromState:
    """Test create_from_state for partial indexing scenario"""

    def test_partial_indexing_includes_warning(self):
        """During indexing, should include partial status and warning"""
        state_manager = AnalyzerStateManager()
        state_manager.transition_to(AnalyzerState.INDEXING)

        # Set up progress info
        from datetime import datetime

        progress = IndexingProgress(
            total_files=100,
            indexed_files=30,
            failed_files=0,
            cache_hits=5,
            current_file="test.cpp",
            start_time=datetime.now(),
            estimated_completion=None,
        )
        state_manager.update_progress(progress)

        data = [{"name": "PartialClass"}]
        result = EnhancedQueryResult.create_from_state(data, state_manager, "search_classes")

        output = result.to_dict()
        assert "metadata" in output
        assert output["metadata"]["status"] == "partial"
        assert output["metadata"]["warning"] is not None
        assert "INCOMPLETE" in output["metadata"]["warning"]
        assert output["metadata"]["indexed_files"] == 30
        assert output["metadata"]["total_files"] == 100

    def test_fully_indexed_returns_normal(self):
        """When fully indexed, should return normal result (no metadata)"""
        state_manager = AnalyzerStateManager()
        state_manager.transition_to(AnalyzerState.INDEXED)

        data = [{"name": "CompleteClass"}]
        result = EnhancedQueryResult.create_from_state(data, state_manager, "search_classes")

        output = result.to_dict()
        assert "data" in output
        assert "metadata" not in output, "Fully indexed should return no metadata"


class TestCreateSearchResultHelper:
    """Test the _create_search_result helper function from cpp_mcp_server"""

    @pytest.fixture
    def mock_state_manager(self):
        """Create a mock state manager that reports fully indexed"""
        state_manager = AnalyzerStateManager()
        state_manager.transition_to(AnalyzerState.INDEXED)
        return state_manager

    def test_empty_list_returns_empty_status(self, mock_state_manager):
        """Empty list should trigger empty status"""
        from mcp_server.cpp_mcp_server import _create_search_result

        result = _create_search_result([], mock_state_manager, "search_classes")
        output = result.to_dict()

        assert output["data"] == []
        assert output["metadata"]["status"] == "empty"

    def test_empty_dict_returns_empty_status(self, mock_state_manager):
        """Empty dict with empty lists should trigger empty status"""
        from mcp_server.cpp_mcp_server import _create_search_result

        data = {"classes": [], "functions": []}
        result = _create_search_result(data, mock_state_manager, "search_symbols")
        output = result.to_dict()

        assert output["metadata"]["status"] == "empty"

    def test_normal_list_returns_no_metadata(self, mock_state_manager):
        """List with 1-20 items should return no metadata"""
        from mcp_server.cpp_mcp_server import _create_search_result

        data = [{"name": f"Class{i}"} for i in range(15)]
        result = _create_search_result(data, mock_state_manager, "search_classes")
        output = result.to_dict()

        assert output["data"] == data
        assert "metadata" not in output

    def test_large_list_returns_large_status(self, mock_state_manager):
        """List with >20 items should trigger large status"""
        from mcp_server.cpp_mcp_server import _create_search_result

        data = [{"name": f"Class{i}"} for i in range(25)]
        result = _create_search_result(data, mock_state_manager, "search_classes")
        output = result.to_dict()

        assert output["metadata"]["status"] == "large"
        assert output["metadata"]["result_count"] == 25

    def test_truncated_returns_truncated_status(self, mock_state_manager):
        """When max_results causes truncation, should return truncated status"""
        from mcp_server.cpp_mcp_server import _create_search_result

        data = [{"name": f"Class{i}"} for i in range(10)]
        result = _create_search_result(
            data, mock_state_manager, "search_classes", max_results=10, total_count=50
        )
        output = result.to_dict()

        assert output["metadata"]["status"] == "truncated"
        assert output["metadata"]["returned"] == 10
        assert output["metadata"]["total_matches"] == 50

    def test_exactly_threshold_no_large_status(self, mock_state_manager):
        """Exactly 20 items should NOT trigger large status"""
        from mcp_server.cpp_mcp_server import _create_search_result

        data = [{"name": f"Class{i}"} for i in range(20)]
        result = _create_search_result(data, mock_state_manager, "search_classes")
        output = result.to_dict()

        assert "metadata" not in output

    def test_max_results_not_exceeding_total_no_truncated(self, mock_state_manager):
        """When total_count <= max_results, should not show truncated"""
        from mcp_server.cpp_mcp_server import _create_search_result

        data = [{"name": f"Class{i}"} for i in range(5)]
        result = _create_search_result(
            data, mock_state_manager, "search_classes", max_results=10, total_count=5
        )
        output = result.to_dict()

        # 5 items with no truncation should be normal (no metadata)
        assert "metadata" not in output

    def test_partial_indexing_takes_precedence(self):
        """Partial indexing status should take precedence over other conditions"""
        from mcp_server.cpp_mcp_server import _create_search_result

        state_manager = AnalyzerStateManager()
        state_manager.transition_to(AnalyzerState.INDEXING)

        # Even with large result set, partial should be returned
        data = [{"name": f"Class{i}"} for i in range(50)]
        result = _create_search_result(data, state_manager, "search_classes")
        output = result.to_dict()

        assert output["metadata"]["status"] == "partial"


class TestQueryCompletenessStatusEnum:
    """Test the QueryCompletenessStatus enum values"""

    def test_all_status_values_exist(self):
        """Verify all expected status values are defined"""
        assert QueryCompletenessStatus.COMPLETE.value == "complete"
        assert QueryCompletenessStatus.PARTIAL.value == "partial"
        assert QueryCompletenessStatus.STALE.value == "stale"
        assert QueryCompletenessStatus.EMPTY.value == "empty"
        assert QueryCompletenessStatus.TRUNCATED.value == "truncated"
        assert QueryCompletenessStatus.LARGE.value == "large"


class TestLargeResultThreshold:
    """Test the LARGE_RESULT_THRESHOLD constant"""

    def test_threshold_is_20(self):
        """Verify threshold is set to 20"""
        assert EnhancedQueryResult.LARGE_RESULT_THRESHOLD == 20
