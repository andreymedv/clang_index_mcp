"""Project and lifecycle MCP tool handlers."""

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, List

from mcp.types import TextContent

from ..context import ctx
from ..cpp_mcp_server import _validate_config_file
from ..state_manager import AnalyzerState, IndexingProgress, BackgroundIndexer
from ..tool_call_logger import ToolCallLogger
from ..._core import diagnostics
from ...cpp_analyzer import CppAnalyzer
from ..._symbols.indexing_callbacks import IndexingCallbacks


async def _handle_set_project_directory(arguments: Dict[str, Any]) -> List[TextContent]:
    config_file_raw = arguments.get("config_file")
    auto_refresh = arguments.get("auto_refresh", True)

    config_file, error_response = _validate_config_file(config_file_raw)
    if error_response:
        return error_response
    assert config_file is not None

    try:
        with open(config_file, "r") as f:
            config_data = json.load(f)

        config_root = config_data.get("project_root")
        if not config_root:
            return [
                TextContent(
                    type="text",
                    text=f"Error: Config file '{config_file}' is missing 'project_root' field",
                )
            ]

        # Resolve project_root relative to config file directory
        config_dir = os.path.dirname(config_file)  # type: ignore[arg-type]
        project_path = os.path.abspath(os.path.join(config_dir, config_root))

        if not os.path.isdir(project_path):
            return [
                TextContent(
                    type="text",
                    text=f"Error: 'project_root' in config '{project_path}' is not a directory or does not exist",
                )
            ]

        diagnostics.info(f"Using config {config_file} for root {project_path}")

    except Exception as e:
        return [TextContent(type="text", text=f"Error reading config file: {str(e)}")]

    # Re-initialize analyzer with new path and config
    # Transition to INDEXING state (allows immediate queries with partial results)
    # This prevents race condition where get_indexing_status fails if called immediately
    ctx.state_manager.transition_to(AnalyzerState.INDEXING)
    ctx.analyzer = CppAnalyzer(project_path, config_file=config_file)
    analyzer = ctx.analyzer
    assert analyzer is not None
    ctx.background_indexer = BackgroundIndexer(analyzer, ctx.state_manager)

    # Initialize tool call telemetry logger
    import uuid as _uuid

    ctx.tool_call_logger = ToolCallLogger(analyzer.cache_dir, str(_uuid.uuid4()))

    # Start indexing in background (truly asynchronous, non-blocking)
    # The task will run independently while the MCP server continues to handle requests
    async def run_background_indexing():
        try:
            # FAST PATH: Check if cache exists and is valid
            # If so, load directly without calling index_project
            loop = asyncio.get_event_loop()
            cache_valid = await loop.run_in_executor(
                None, analyzer.context.cache_orchestrator.load_cache
            )

            if cache_valid:
                # Cache loaded successfully - skip indexing
                diagnostics.info(
                    f"Cache loaded successfully: "
                    f"{analyzer.context.symbol_store.class_name_count()} classes, "
                    f"{analyzer.context.symbol_store.function_name_count()} functions indexed"
                )

                # CRITICAL FIX FOR ISSUE #15: Initialize progress with cache data
                # Without this, get_indexing_status returns 0 files even though cache is loaded
                # Create progress object from cached data
                total_files = analyzer.context.symbol_store.file_index_count()
                progress = IndexingProgress(
                    total_files=total_files,
                    indexed_files=total_files,  # All files loaded from cache
                    failed_files=0,  # No failures when loading from cache
                    cache_hits=total_files,  # Everything came from cache
                    current_file=None,  # No active file
                    start_time=datetime.now(),
                    estimated_completion=None,  # Already complete
                )
                ctx.state_manager.update_progress(progress)

                ctx.state_manager.transition_to(AnalyzerState.INDEXED)

                # Mark as initialized immediately
                ctx.analyzer_initialized = True

                diagnostics.info(
                    "Server ready (loaded from cache) - use sync_project with refresh_mode to detect file changes"
                )
                return

            # SLOW PATH: Cache not valid, need to index from scratch
            diagnostics.info("No valid cache found, starting full indexing...")
            await ctx.background_indexer.start_indexing(force=False, include_dependencies=True)

            # Indexing complete - mark as initialized
            ctx.analyzer_initialized = True

        except Exception as e:
            diagnostics.error(f"Background indexing failed: {e}")
            ctx.state_manager.transition_to(AnalyzerState.ERROR)
            pass

    # Create background task (non-blocking)
    asyncio.create_task(run_background_indexing())

    # Save session for auto-resume on restart
    ctx.session_manager.save_session(config_file=config_file)

    # Build response message
    auto_refresh_msg = " Auto-refresh enabled." if auto_refresh else " Auto-refresh disabled."

    # Return immediately - indexing continues in background
    return [
        TextContent(
            type="text",
            text=f"Set project via config: {config_file}\n"
            f"Resolved project root: {project_path}\n"
            f"Indexing started in background.{auto_refresh_msg}\n"
            f"Use 'sync_project' to check progress.\n"
            f"Tools are available but will return partial results until indexing completes.",
        )
    ]


async def _ensure_analyzer_resumed() -> bool:
    """Ensure analyzer is initialized, attempting auto-resume if needed."""
    if ctx.analyzer is not None:
        return True

    diagnostics.info("Attempting auto-resume of last used session...")
    disable_auto_resume = os.environ.get("MCP_DISABLE_SESSION_RESUME", "false").lower() == "true"
    saved_session = None if disable_auto_resume else ctx.session_manager.load_session()
    if saved_session:
        from ..cpp_mcp_server import _try_resume_session

        ctx.analyzer, ctx.background_indexer, ctx.analyzer_initialized = _try_resume_session(
            saved_session
        )

    return ctx.analyzer is not None


async def _run_background_refresh(refresh_mode: str):
    """Background task to perform project refresh (incremental or full)."""
    analyzer = ctx.analyzer
    assert analyzer is not None
    try:
        loop = asyncio.get_event_loop()

        # Create progress callback that updates state_manager (same as BackgroundIndexer)
        def progress_callback(progress: IndexingProgress):
            """Callback to update progress in state manager during refresh"""
            ctx.state_manager.update_progress(progress)

        def wait_for_tools():
            """Wrapper to match Callable[[], None] expected by analyzers"""
            ctx.state_manager.wait_for_tools_to_finish()

        if refresh_mode == "incremental":
            diagnostics.info("Starting incremental refresh...")
        else:
            diagnostics.info("Starting full refresh...")

        callbacks = IndexingCallbacks(progress=progress_callback, wait_for_tools=wait_for_tools)
        modified_count = await loop.run_in_executor(
            None, lambda: analyzer.refresh_if_needed(callbacks)
        )
        diagnostics.info(f"Refresh complete: re-analyzed {modified_count} files")
        ctx.state_manager.transition_to(AnalyzerState.INDEXED)
        return

    except Exception as e:
        diagnostics.error(f"Background refresh failed: {e}")
        ctx.state_manager.transition_to(AnalyzerState.ERROR)
        pass


async def _handle_refresh_project(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle refresh_project: trigger incremental or full re-indexing."""
    # 1. If analyzer is None, try to resume session from last used config
    if not await _ensure_analyzer_resumed():
        return [
            TextContent(
                type="text",
                text="Error: Project directory not set. Please use 'set_project_directory' first with the path to your C++ project.",
            )
        ]

    refresh_mode = arguments.get("refresh_mode", "incremental")

    # Issue #7: Warn if full mode is used (should be rare)
    if refresh_mode == "full":
        diagnostics.warning(
            "refresh_mode='full' was requested - this will re-analyze ALL files and may "
            "take 5-10 minutes on large projects. Incremental mode is 30-300x faster "
            "and sufficient for 99% of cases."
        )

    # Transition to REFRESHING state synchronously
    ctx.state_manager.transition_to(AnalyzerState.REFRESHING)

    # Create background task (non-blocking)
    asyncio.create_task(_run_background_refresh(refresh_mode))

    # Return immediately - refresh continues in background
    return [
        TextContent(
            type="text",
            text=f"Refresh started in background (mode: {refresh_mode}).\n"
            f"Use 'sync_project' to check progress.\n"
            f"Tools will continue to work and return results based on current cache state.",
        )
    ]


async def _handle_check_system_status(arguments: Dict[str, Any]) -> List[TextContent]:
    # Combined server diagnostics and indexing status
    status_dict = ctx.state_manager.get_status_dict()
    status_dict["analyzer_type"] = "python_enhanced"

    analyzer = ctx.analyzer
    if analyzer is None:
        return [TextContent(type="text", text=json.dumps(status_dict, indent=2))]

    ccm = analyzer.context.compile_commands_manager
    symbol_store = analyzer.context.symbol_store
    assert symbol_store is not None
    total_classes = symbol_store.total_class_symbols()
    total_functions = symbol_store.total_function_symbols()

    status_dict.update(
        {
            "call_graph_enabled": True,
            "compile_commands_enabled": ccm.enabled if ccm else False,
            "compile_commands_path": ccm.compile_commands_path if ccm else None,
            "parsed_files": symbol_store.file_index_count(),
            "indexed_classes": total_classes,
            "indexed_functions": total_functions,
        }
    )
    return [TextContent(type="text", text=json.dumps(status_dict, indent=2))]


async def _handle_wait_for_indexing(arguments: Dict[str, Any]) -> List[TextContent]:
    loop = asyncio.get_event_loop()
    # Internal handler - used by sync_project and tests
    timeout = arguments.get("timeout", 60.0)

    if ctx.state_manager.is_fully_indexed():
        return [TextContent(type="text", text="Indexing already complete.")]

    completed = await loop.run_in_executor(
        None, lambda: ctx.state_manager.wait_for_indexed(timeout)
    )

    if completed:
        progress = ctx.state_manager.get_progress()
        indexed_count = progress.indexed_files if progress else 0
        failed_count = progress.failed_files if progress else 0
        return [
            TextContent(
                type="text",
                text=f"Indexing complete! Indexed {indexed_count} files successfully ({failed_count} failed).",
            )
        ]
    else:
        return [
            TextContent(
                type="text",
                text=f"Timeout waiting for indexing (waited {timeout}s). Use 'sync_project' to check progress.",
            )
        ]
