#!/usr/bin/env python3
"""
Tests for concurrent tool requests during background indexing

These tests verify that the MCP server can handle query requests
while indexing is in progress without timing out or blocking.
"""

import asyncio
import pytest
import json
from pathlib import Path

from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server.state_manager import (
    AnalyzerStateManager, AnalyzerState, BackgroundIndexer
)
from mcp_server import cpp_mcp_server


@pytest.fixture
def large_cpp_project(tmp_path):
    """
    Create a C++ project large enough that indexing takes a few seconds
    This ensures we have time to send concurrent queries during indexing
    """
    project = tmp_path / "large_project"
    project.mkdir()

    # Create 50 files to ensure indexing takes measurable time
    for i in range(50):
        header = project / f"module_{i}.h"
        header.write_text(f"""
#ifndef MODULE_{i}_H
#define MODULE_{i}_H

class Module{i} {{
public:
    int calculate_{i}(int x);
    void process_{i}(double y);
    static Module{i}* getInstance();
private:
    int value_{i};
}};

class Helper{i} {{
public:
    void assist();
}};

#endif
""")

        source = project / f"module_{i}.cpp"
        source.write_text(f"""
#include "module_{i}.h"

int Module{i}::calculate_{i}(int x) {{
    return x * {i};
}}

void Module{i}::process_{i}(double y) {{
    value_{i} = static_cast<int>(y);
}}

Module{i}* Module{i}::getInstance() {{
    static Module{i} instance;
    return &instance;
}}

void Helper{i}::assist() {{
    // Helper implementation
}}
""")

    return project


@pytest.mark.asyncio
async def test_query_during_background_indexing(large_cpp_project):
    """
    Test that queries can be executed while indexing is running
    without timing out or blocking the event loop
    """
    # Set up analyzer and state manager
    analyzer = CppAnalyzer(str(large_cpp_project))
    state_manager = AnalyzerStateManager()
    background_indexer = BackgroundIndexer(analyzer, state_manager)

    # Update global state for MCP server
    cpp_mcp_server.analyzer = analyzer
    cpp_mcp_server.state_manager = state_manager
    cpp_mcp_server.analyzer_initialized = False

    # Start indexing in background (non-blocking)
    state_manager.transition_to(AnalyzerState.INDEXING)
    indexing_task = asyncio.create_task(
        background_indexer.start_indexing(force=True, include_dependencies=False)
    )

    # Wait a moment for indexing to start
    await asyncio.sleep(0.1)

    # Verify indexing is running
    assert state_manager.state == AnalyzerState.INDEXING, "Should be indexing"

    # Send a query while indexing is in progress
    # This should NOT block or timeout - it should return partial results
    result = await cpp_mcp_server.call_tool(
        "search_classes",
        {"pattern": "Module.*", "project_only": True}
    )

    # Verify we got a response (even if partial)
    assert len(result) > 0, "Should get response during indexing"
    response_text = result[0].text
    response_data = json.loads(response_text)

    # Check metadata indicates partial results
    assert "metadata" in response_data, "Response should include metadata"
    metadata = response_data["metadata"]

    # During indexing, status should be "partial"
    if state_manager.state == AnalyzerState.INDEXING:
        assert metadata["status"] == "partial", "Should indicate partial results during indexing"
        assert metadata["warning"] is not None, "Should have warning about incomplete results"

    # Data should be present (even if partial)
    assert "data" in response_data, "Should have data field"

    # Wait for indexing to complete
    await indexing_task

    # Verify indexing completed
    assert state_manager.state == AnalyzerState.INDEXED, "Should be indexed"

    # Now query again - should get complete results
    result2 = await cpp_mcp_server.call_tool(
        "search_classes",
        {"pattern": "Module.*", "project_only": True}
    )

    response_text2 = result2[0].text
    response_data2 = json.loads(response_text2)
    metadata2 = response_data2["metadata"]

    # Should now be complete
    assert metadata2["status"] == "complete", "Should indicate complete results after indexing"
    assert metadata2["warning"] is None, "Should have no warning when complete"

    # Should have found classes
    classes = response_data2["data"]
    assert len(classes) > 0, "Should find Module classes"


@pytest.mark.asyncio
async def test_multiple_concurrent_queries_during_indexing(large_cpp_project):
    """
    Test that multiple concurrent queries can execute during indexing
    without blocking each other
    """
    analyzer = CppAnalyzer(str(large_cpp_project))
    state_manager = AnalyzerStateManager()
    background_indexer = BackgroundIndexer(analyzer, state_manager)

    # Update global state
    cpp_mcp_server.analyzer = analyzer
    cpp_mcp_server.state_manager = state_manager
    cpp_mcp_server.analyzer_initialized = False

    # Start indexing
    state_manager.transition_to(AnalyzerState.INDEXING)
    indexing_task = asyncio.create_task(
        background_indexer.start_indexing(force=True, include_dependencies=False)
    )

    await asyncio.sleep(0.1)

    # Launch multiple queries concurrently
    query_tasks = [
        cpp_mcp_server.call_tool("search_classes", {"pattern": "Module.*"}),
        cpp_mcp_server.call_tool("search_functions", {"pattern": "calculate.*"}),
        cpp_mcp_server.call_tool("search_classes", {"pattern": "Helper.*"}),
        cpp_mcp_server.call_tool("search_functions", {"pattern": "process.*"}),
    ]

    # All queries should complete without blocking each other
    # Use a reasonable timeout (5 seconds)
    results = await asyncio.wait_for(
        asyncio.gather(*query_tasks),
        timeout=5.0
    )

    # All queries should return results
    assert len(results) == 4, "All concurrent queries should complete"

    for result in results:
        assert len(result) > 0, "Each query should return a response"
        response_data = json.loads(result[0].text)
        assert "metadata" in response_data, "Each response should have metadata"
        assert "data" in response_data, "Each response should have data"

    # Wait for indexing to complete
    await indexing_task


@pytest.mark.asyncio
async def test_query_does_not_timeout_during_long_indexing(large_cpp_project):
    """
    Test that queries complete quickly even when indexing is taking a long time

    This verifies the fix for the LM Studio timeout issue
    """
    analyzer = CppAnalyzer(str(large_cpp_project))
    state_manager = AnalyzerStateManager()
    background_indexer = BackgroundIndexer(analyzer, state_manager)

    cpp_mcp_server.analyzer = analyzer
    cpp_mcp_server.state_manager = state_manager

    # Start indexing
    state_manager.transition_to(AnalyzerState.INDEXING)
    indexing_task = asyncio.create_task(
        background_indexer.start_indexing(force=True, include_dependencies=False)
    )

    await asyncio.sleep(0.1)

    # Time how long a query takes
    import time
    start = time.time()

    result = await cpp_mcp_server.call_tool(
        "get_indexing_status",
        {}
    )

    elapsed = time.time() - start

    # Query should complete very quickly (< 1 second)
    # even though indexing is still running
    assert elapsed < 1.0, f"Query should not block, took {elapsed:.2f}s"

    # Verify we got status
    response_data = json.loads(result[0].text)
    assert "state" in response_data, "Should return status"
    assert response_data["state"] == "indexing", "Should show indexing state"

    await indexing_task


@pytest.mark.asyncio
async def test_wait_for_indexing_blocks_appropriately(large_cpp_project):
    """
    Test that wait_for_indexing tool blocks until indexing completes
    but does so without blocking the event loop
    """
    analyzer = CppAnalyzer(str(large_cpp_project))
    state_manager = AnalyzerStateManager()
    background_indexer = BackgroundIndexer(analyzer, state_manager)

    cpp_mcp_server.analyzer = analyzer
    cpp_mcp_server.state_manager = state_manager

    # Start indexing
    state_manager.transition_to(AnalyzerState.INDEXING)
    indexing_task = asyncio.create_task(
        background_indexer.start_indexing(force=True, include_dependencies=False)
    )

    await asyncio.sleep(0.1)

    # Call wait_for_indexing with a long timeout
    wait_task = asyncio.create_task(
        cpp_mcp_server.call_tool("wait_for_indexing", {"timeout": 30.0})
    )

    # While waiting, we should still be able to check status
    # This proves wait_for_indexing doesn't block the event loop
    status_result = await cpp_mcp_server.call_tool("get_indexing_status", {})
    status_data = json.loads(status_result[0].text)

    # Should still be indexing
    assert status_data["state"] == "indexing", "Should still be indexing while waiting"

    # Now wait for both to complete
    await indexing_task
    wait_result = await wait_task

    # wait_for_indexing should report success
    response_text = wait_result[0].text
    assert "complete" in response_text.lower(), "Should report indexing complete"


@pytest.mark.asyncio
async def test_state_manager_ready_for_queries_during_indexing(large_cpp_project):
    """
    Test that state_manager.is_ready_for_queries() returns True during indexing
    """
    state_manager = AnalyzerStateManager()

    # Should not be ready initially
    assert not state_manager.is_ready_for_queries(), "Not ready when uninitialized"

    # Should be ready during indexing
    state_manager.transition_to(AnalyzerState.INDEXING)
    assert state_manager.is_ready_for_queries(), "Should be ready during indexing"

    # Should be ready when indexed
    state_manager.transition_to(AnalyzerState.INDEXED)
    assert state_manager.is_ready_for_queries(), "Should be ready when indexed"

    # Should be ready during refresh
    state_manager.transition_to(AnalyzerState.REFRESHING)
    assert state_manager.is_ready_for_queries(), "Should be ready during refresh"
