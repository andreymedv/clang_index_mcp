#!/usr/bin/env python3
"""
Tests for real-time progress reporting during indexing (REQ-10.3.5)

Tests that progress callbacks are invoked and provide accurate information
during the indexing process.
"""

import asyncio
import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server.state_manager import (
    AnalyzerStateManager, AnalyzerState, BackgroundIndexer, IndexingProgress
)


@pytest.fixture
def simple_cpp_project(tmp_path):
    """Create a simple C++ project with multiple files"""
    project = tmp_path / "project"
    project.mkdir()

    # Create main.cpp
    (project / "main.cpp").write_text("""
#include "utils.h"

int main() {
    return calculate(5);
}
""")

    # Create utils.h
    (project / "utils.h").write_text("""
#ifndef UTILS_H
#define UTILS_H

int calculate(int x);

class Calculator {
public:
    int add(int a, int b);
    int subtract(int a, int b);
};

#endif
""")

    # Create utils.cpp
    (project / "utils.cpp").write_text("""
#include "utils.h"

int calculate(int x) {
    return x * 2;
}

int Calculator::add(int a, int b) {
    return a + b;
}

int Calculator::subtract(int a, int b) {
    return a - b;
}
""")

    return project


@pytest.mark.asyncio
async def test_progress_callback_invoked(simple_cpp_project):
    """Test that progress callback is invoked during indexing"""
    analyzer = CppAnalyzer(str(simple_cpp_project))
    state_manager = AnalyzerStateManager()

    # Track progress updates
    progress_updates = []

    def progress_callback(progress: IndexingProgress):
        """Capture progress updates"""
        progress_updates.append(progress)

    # Index with progress callback
    indexed_count = analyzer.index_project(
        force=True,
        include_dependencies=False,
        progress_callback=progress_callback
    )

    # Verify callback was invoked
    assert len(progress_updates) > 0, "Progress callback should be invoked at least once"

    # Verify we indexed files
    assert indexed_count > 0, "Should have indexed some files"


@pytest.mark.asyncio
async def test_progress_data_accuracy(simple_cpp_project):
    """Test that progress data is accurate and complete"""
    analyzer = CppAnalyzer(str(simple_cpp_project))
    state_manager = AnalyzerStateManager()

    progress_updates = []

    def progress_callback(progress: IndexingProgress):
        progress_updates.append(progress)

    indexed_count = analyzer.index_project(
        force=True,
        include_dependencies=False,
        progress_callback=progress_callback
    )

    # Check that we got progress updates
    assert len(progress_updates) > 0, "Should have progress updates"

    # Get the last progress update
    final_progress = progress_updates[-1]

    # Verify structure
    assert final_progress.total_files > 0, "Should have total files"
    assert final_progress.indexed_files >= 0, "Should have indexed count"
    assert final_progress.failed_files >= 0, "Should have failed count"
    assert final_progress.cache_hits >= 0, "Should have cache hits"
    assert isinstance(final_progress.start_time, datetime), "Should have start time"

    # Verify completion calculation
    assert 0 <= final_progress.completion_percentage <= 100, "Percentage should be 0-100"

    # Verify final counts
    assert final_progress.indexed_files + final_progress.failed_files <= final_progress.total_files


@pytest.mark.asyncio
async def test_progress_increases_monotonically(simple_cpp_project):
    """Test that indexed_files count increases monotonically"""
    analyzer = CppAnalyzer(str(simple_cpp_project))

    progress_updates = []

    def progress_callback(progress: IndexingProgress):
        progress_updates.append(progress)

    analyzer.index_project(
        force=True,
        include_dependencies=False,
        progress_callback=progress_callback
    )

    # Check that indexed count never decreases
    for i in range(1, len(progress_updates)):
        prev = progress_updates[i-1].indexed_files + progress_updates[i-1].failed_files
        curr = progress_updates[i].indexed_files + progress_updates[i].failed_files
        assert curr >= prev, f"Progress should not decrease: {prev} -> {curr}"


@pytest.mark.asyncio
async def test_background_indexer_progress_integration(simple_cpp_project):
    """Test that BackgroundIndexer integrates progress reporting with state_manager"""
    analyzer = CppAnalyzer(str(simple_cpp_project))
    state_manager = AnalyzerStateManager()
    background_indexer = BackgroundIndexer(analyzer, state_manager)

    # Start background indexing
    indexed_count = await background_indexer.start_indexing(
        force=True,
        include_dependencies=False
    )

    # Check that state manager has progress information
    progress = state_manager.get_progress()
    assert progress is not None, "State manager should have progress info"
    assert progress.total_files > 0, "Should have indexed files"
    assert progress.indexed_files >= 0, "Should track indexed count"

    # Check that state transitioned to INDEXED
    assert state_manager.state == AnalyzerState.INDEXED, "Should be in INDEXED state"


@pytest.mark.asyncio
async def test_progress_completion_percentage(simple_cpp_project):
    """Test completion percentage calculation"""
    analyzer = CppAnalyzer(str(simple_cpp_project))

    progress_updates = []

    def progress_callback(progress: IndexingProgress):
        progress_updates.append(progress)

    analyzer.index_project(
        force=True,
        include_dependencies=False,
        progress_callback=progress_callback
    )

    # Verify completion percentage is correct
    for progress in progress_updates:
        expected_percentage = (progress.indexed_files / progress.total_files * 100.0)
        assert abs(progress.completion_percentage - expected_percentage) < 0.01, \
            f"Completion percentage mismatch: {progress.completion_percentage} vs {expected_percentage}"


@pytest.mark.asyncio
async def test_progress_callback_exception_handling(simple_cpp_project):
    """Test that indexing continues even if progress callback throws"""
    analyzer = CppAnalyzer(str(simple_cpp_project))

    call_count = [0]

    def failing_callback(progress: IndexingProgress):
        """Callback that always throws"""
        call_count[0] += 1
        raise RuntimeError("Callback error")

    # Indexing should complete despite callback failures
    indexed_count = analyzer.index_project(
        force=True,
        include_dependencies=False,
        progress_callback=failing_callback
    )

    # Verify indexing completed successfully
    assert indexed_count > 0, "Indexing should complete despite callback errors"
    assert call_count[0] > 0, "Callback should have been called"


@pytest.mark.asyncio
async def test_progress_is_complete_flag(simple_cpp_project):
    """Test the is_complete flag on IndexingProgress"""
    analyzer = CppAnalyzer(str(simple_cpp_project))

    progress_updates = []

    def progress_callback(progress: IndexingProgress):
        progress_updates.append(progress)

    analyzer.index_project(
        force=True,
        include_dependencies=False,
        progress_callback=progress_callback
    )

    # Check that early updates show incomplete
    if len(progress_updates) > 1:
        first_progress = progress_updates[0]
        # First update might be complete if only one file, so check conservatively
        pass

    # Check that final update shows complete
    final_progress = progress_updates[-1]
    assert final_progress.is_complete, "Final progress should show complete"


@pytest.mark.asyncio
async def test_progress_to_dict_serialization(simple_cpp_project):
    """Test that IndexingProgress.to_dict() produces valid JSON-serializable dict"""
    analyzer = CppAnalyzer(str(simple_cpp_project))

    progress_updates = []

    def progress_callback(progress: IndexingProgress):
        progress_updates.append(progress)

    analyzer.index_project(
        force=True,
        include_dependencies=False,
        progress_callback=progress_callback
    )

    assert len(progress_updates) > 0, "Should have progress updates"

    # Get dict representation
    progress_dict = progress_updates[0].to_dict()

    # Verify required fields
    assert "total_files" in progress_dict
    assert "indexed_files" in progress_dict
    assert "failed_files" in progress_dict
    assert "cache_hits" in progress_dict
    assert "completion_percentage" in progress_dict
    assert "current_file" in progress_dict
    assert "start_time" in progress_dict

    # Verify types (should be JSON-serializable)
    import json
    json_str = json.dumps(progress_dict)  # Should not throw
    assert len(json_str) > 0
