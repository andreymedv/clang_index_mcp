
import asyncio
import os
import json
import pytest
from unittest.mock import MagicMock, patch
from clang_index_mcp._mcp import cpp_mcp_server
from clang_index_mcp._mcp.context import ctx
from clang_index_mcp._mcp.state_manager import AnalyzerState

@pytest.mark.asyncio
async def test_sync_project_after_failed_resume():
    # 1. Setup mock session and analyzer
    mock_session = {"config_file": "/tmp/mock_config.json"}

    saved_analyzer = ctx.analyzer
    saved_bg = ctx.background_indexer
    try:
        with patch("clang_index_mcp._core.session_manager.SessionManager.load_session", return_value=mock_session), \
             patch("clang_index_mcp._mcp.cpp_mcp_server._try_resume_session") as mock_resume, \
             patch.object(ctx, "state_manager") as mock_state_manager:

            # Mock resume failure (returns analyzer but state is UNINITIALIZED)
            mock_analyzer = MagicMock()
            mock_background_indexer = MagicMock()
            mock_resume.return_value = (mock_analyzer, mock_background_indexer, False)

            # We need to actually set the context variables
            ctx.analyzer = mock_analyzer
            ctx.background_indexer = mock_background_indexer

            # Mock state_manager.is_ready_for_queries to return False (as it would for UNINITIALIZED)
            mock_state_manager.is_ready_for_queries.return_value = False

            # 2. Call sync_project with refresh_mode="full"
            from clang_index_mcp._mcp.consolidated_tools import handle_tool_call_b

            arguments = {"refresh_mode": "full"}
            result = await handle_tool_call_b("sync_project", arguments)

            print(f"Result: {result}")

            # Check if error message is ABSENT
            assert not any("Error: Project directory not set" in content.text for content in result)

            # Verify if transition_to(AnalyzerState.REFRESHING) was called
            refreshing_calls = [call for call in mock_state_manager.transition_to.call_args_list
                               if call.args[0] == AnalyzerState.REFRESHING]

            if refreshing_calls:
                print("SUCCESS: Refresh WAS started despite initial UNINITIALIZED state.")
            else:
                print("FAILURE: Refresh was NOT started.")
                assert refreshing_calls
    finally:
        ctx.analyzer = saved_analyzer
        ctx.background_indexer = saved_bg

@pytest.mark.asyncio
async def test_sync_project_auto_resumes_when_none():
    # 1. Setup mock session (analyzer starts as None)
    mock_session = {"config_file": "/tmp/mock_config.json"}

    saved_analyzer = ctx.analyzer
    saved_bg = ctx.background_indexer
    try:
        with patch("clang_index_mcp._core.session_manager.SessionManager.load_session", return_value=mock_session), \
             patch("clang_index_mcp._mcp.cpp_mcp_server._try_resume_session") as mock_resume, \
             patch.object(ctx, "state_manager") as mock_state_manager:

            # Mock resume success
            mock_analyzer = MagicMock()
            mock_background_indexer = MagicMock()
            mock_resume.return_value = (mock_analyzer, mock_background_indexer, True)

            # Ensure analyzer starts as None
            ctx.analyzer = None

            # 2. Call sync_project with refresh_mode="full"
            from clang_index_mcp._mcp.consolidated_tools import handle_tool_call_b

            arguments = {"refresh_mode": "full"}
            result = await handle_tool_call_b("sync_project", arguments)

            # Check if _try_resume_session was called
            mock_resume.assert_called_once()

            # Check if error message is ABSENT
            assert not any("Error: Project directory not set" in content.text for content in result)

            print("SUCCESS: sync_project auto-resumed session.")
    finally:
        ctx.analyzer = saved_analyzer
        ctx.background_indexer = saved_bg

@pytest.mark.asyncio
async def test_sync_project_status_works_when_none():
    # Save and restore state_manager to handle test-ordering issues in full suite
    from clang_index_mcp._mcp.state_manager import AnalyzerStateManager
    saved_sm = ctx.state_manager
    try:
        real_sm = AnalyzerStateManager()
        real_sm.transition_to(AnalyzerState.UNINITIALIZED)
        ctx.state_manager = real_sm
        ctx.analyzer = None

        from clang_index_mcp._mcp.consolidated_tools import handle_tool_call_b

        # sync_project with no args returns status
        result = await handle_tool_call_b("sync_project", {})

        # Check if result contains JSON with uninitialized state
        data = json.loads(result[0].text)
        assert data["state"] == "uninitialized"
        assert "analyzer_type" in data

        print("SUCCESS: sync_project status works when analyzer is None.")
    finally:
        ctx.state_manager = saved_sm

if __name__ == "__main__":
    asyncio.run(test_sync_project_after_failed_resume())
