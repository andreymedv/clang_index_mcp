"""
C++ Code Analysis MCP Server

Provides tools for analyzing C++ codebases using libclang.
Focused on specific queries rather than bulk data dumps.
"""

import asyncio
import json
import os
import sys
from typing import Any, Dict, List, cast

# Import diagnostics early
try:
    from .._core import diagnostics
except ImportError:
    from .._core import diagnostics

try:
    from clang.cindex import Config  # noqa: F401
except ImportError:
    diagnostics.fatal("clang package not found. Install with: pip install libclang")
    sys.exit(1)

from mcp.server import Server
from mcp.types import TextContent, Tool

from .tool_registry import ToolRegistry
from . import consolidated_tools  # noqa: F401

try:
    from .._core.libclang_setup import configure_libclang, get_libclang_runtime_info
except ImportError:
    from libclang_setup import configure_libclang, get_libclang_runtime_info  # type: ignore[no-redef]


def find_and_configure_libclang():
    """Backwards-compatible wrapper around shared libclang setup."""
    return configure_libclang()


# Try to find and configure libclang
if not find_and_configure_libclang():
    diagnostics.fatal("Could not find libclang library.")
    diagnostics.fatal("Please install LLVM/Clang:")
    diagnostics.fatal("  Windows: Download from https://releases.llvm.org/")
    diagnostics.fatal("  macOS: brew install llvm")
    diagnostics.fatal("  Linux: sudo apt install libclang-dev")
    sys.exit(1)

diagnostics.info(f"libclang runtime config: {get_libclang_runtime_info()}")

# Import the Python analyzer and state manager
try:
    # Try package import first (when run as module)
    from ..cpp_analyzer import CppAnalyzer
    from .state_manager import (
        AnalyzerState,
        BackgroundIndexer,
    )
    from .tool_call_logger import ToolCallLogger  # noqa: F401  # type: ignore[no-redef]
except ImportError:
    # Fall back to direct import (when run as script)
    from cpp_analyzer import CppAnalyzer  # type: ignore[no-redef]
    from state_manager import (  # type: ignore[no-redef]
        AnalyzerState,
        BackgroundIndexer,
    )
    from tool_call_logger import ToolCallLogger  # type: ignore[no-redef]  # noqa: F401

from .context import ctx  # noqa: E402

# Initialize analyzer
PROJECT_ROOT = os.environ.get("CPP_PROJECT_ROOT", None)


# MCP Server
server = Server("cpp-analyzer")


@server.list_tools()
async def list_tools() -> List[Tool]:
    return cast(List[Tool], ToolRegistry.call_tool("list_tools_b"))


def _count_results_from_text(result_text: str) -> int:
    """Extract result count from JSON text for telemetry."""
    try:
        parsed = json.loads(result_text)
        if isinstance(parsed, list):
            return len(parsed)
        if isinstance(parsed, dict):
            results_list = parsed.get("results")
            if isinstance(results_list, list):
                return len(results_list)
            for key in ("callers", "callees"):
                sub = parsed.get(key)
                if isinstance(sub, list):
                    return len(sub)
    except (json.JSONDecodeError, TypeError):
        pass
    return 0


def _try_log_tool_call(name: str, arguments: Dict[str, Any], result: List[TextContent]) -> None:
    """Log a tool call for telemetry. Never raises."""
    try:
        if ctx.tool_call_logger is None or not ctx.tool_call_logger.enabled:
            return
        result_text = result[0].text if result else ""
        result_count = _count_results_from_text(result_text)
        ctx.tool_call_logger.log_tool_call(
            name, arguments, result_count, result_text, analyzer=ctx.analyzer
        )
    except Exception:
        pass  # Telemetry must never break tool calls


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    result = cast(
        List[TextContent], await ToolRegistry.call_tool("handle_tool_call_b", name, arguments)
    )
    _try_log_tool_call(name, arguments, result)
    return result


# Import domain rules from focused modules.
from .query_policy import _check_tool_readiness  # noqa: E402

# Import tool handlers from focused submodules.
from .tool_handlers.search_tools import (  # noqa: E402
    _handle_find_in_file,
    _handle_get_class_info,
    _handle_get_type_alias_info,
    _handle_search_classes,
    _handle_search_functions,
    _handle_search_symbols,
)
from .tool_handlers.hierarchy_tools import _handle_get_class_hierarchy  # noqa: E402
from .tool_handlers.call_graph_tools import (  # noqa: E402
    _handle_find_incoming_calls,
    _handle_get_call_path,
    _handle_get_call_sites,
    _handle_get_outgoing_calls,
)
from .tool_handlers.project_tools import (  # noqa: E402
    _handle_check_system_status,
    _handle_refresh_project,
    _handle_set_project_directory,
    _handle_wait_for_indexing,
)
from .tool_handlers.transport_tools import (  # noqa: E402
    _install_signal_handlers,
    _run_http_transport,
    _run_stdio_transport,
)


async def _handle_tool_call(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    try:
        # 1. Management tools (handle their own state checks)
        if name == "set_project_directory":
            return await _handle_set_project_directory(arguments)
        if name == "check_system_status":
            return await _handle_check_system_status(arguments)

        # 2. Check tool readiness
        error_response = _check_tool_readiness(name)
        if error_response:
            return error_response

        # 3. Route to specific handler
        handlers = {
            "search_classes": _handle_search_classes,
            "search_functions": _handle_search_functions,
            "get_class_info": _handle_get_class_info,
            "get_type_alias_info": _handle_get_type_alias_info,
            "search_symbols": _handle_search_symbols,
            "find_in_file": _handle_find_in_file,
            "refresh_project": _handle_refresh_project,
            "check_system_status": _handle_check_system_status,
            "wait_for_indexing": _handle_wait_for_indexing,
            "get_class_hierarchy": _handle_get_class_hierarchy,
            "find_incoming_calls": _handle_find_incoming_calls,
            "get_outgoing_calls": _handle_get_outgoing_calls,
            "get_call_sites": _handle_get_call_sites,
            "get_call_path": _handle_get_call_path,
        }

        if name in handlers:
            return await handlers[name](arguments)

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [
            TextContent(
                type="text",
                text=f"Internal error: {str(e)}\n\n"
                "This is a server-side issue, not a user error. "
                "Try restarting the MCP server.",
            )
        ]


ToolRegistry.register("_handle_tool_call", _handle_tool_call)


def _try_resume_session(saved_session):
    """Attempt to resume a saved session and return initialized components."""
    config_file = saved_session.get("config_file")

    try:
        with open(config_file, "r") as f:
            config_data = json.load(f)

        config_root = config_data.get("project_root")
        if not config_root:
            raise ValueError(f"Config file {config_file} missing 'project_root'")

        config_dir = os.path.dirname(config_file)
        project_path = os.path.abspath(os.path.join(config_dir, config_root))

        diagnostics.info(f"Auto-resuming session via config: {config_file}")
        diagnostics.info(f"Resolved project root: {project_path}")

        ctx.state_manager.transition_to(AnalyzerState.INITIALIZING)
        new_analyzer = CppAnalyzer(project_path, config_file=config_file)
        new_background_indexer = BackgroundIndexer(new_analyzer, ctx.state_manager)

        cache_loaded = new_analyzer.context.cache_orchestrator.load_cache()
        if cache_loaded:
            diagnostics.info(
                f"Session restored from cache: {new_analyzer.context.symbol_store.class_name_count()} classes, "
                f"{new_analyzer.context.symbol_store.function_name_count()} functions"
            )
            ctx.state_manager.transition_to(AnalyzerState.INDEXED)
            return new_analyzer, new_background_indexer, True

        diagnostics.info("No valid cache for saved session, will need to re-index")
        ctx.state_manager.transition_to(AnalyzerState.UNINITIALIZED)
        return new_analyzer, new_background_indexer, False

    except Exception as e:
        diagnostics.warning(f"Failed to resume session: {e}")
        ctx.state_manager.transition_to(AnalyzerState.UNINITIALIZED)
        return None, None, False


def _shutdown_analyzer():
    """Interrupt and close the analyzer, releasing resources."""
    if ctx.analyzer is None:
        return
    try:
        ctx.analyzer.interrupt()
    except Exception:
        pass
    try:
        ctx.analyzer.close()
    except Exception:
        pass
    ctx.analyzer = None


async def _cleanup_resources():
    """Cleanup resources on shutdown."""
    diagnostics.debug("Starting cleanup...")

    _shutdown_analyzer()

    if ctx.background_indexer and ctx.background_indexer.is_indexing():
        diagnostics.debug("Canceling background indexing...")
        try:
            await ctx.background_indexer.cancel()
        except Exception:
            pass

    loop = asyncio.get_event_loop()
    if hasattr(loop, "_default_executor") and loop._default_executor:
        loop._default_executor.shutdown(wait=False, cancel_futures=True)

    diagnostics.debug("Cleanup complete")


def _create_argument_parser():
    """Create and configure the argument parser for the MCP server."""
    import argparse

    parser = argparse.ArgumentParser(
        description="C++ Code Analysis MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Transport Options:
  stdio  - Standard I/O transport (default, for CLI integration)
  http   - HTTP/Streamable HTTP transport (RESTful API)
  sse    - Server-Sent Events transport (streaming updates)

Examples:
  %(prog)s                                    # Run with stdio transport
  %(prog)s --transport http --port 8000      # Run HTTP server on port 8000
  %(prog)s --transport sse --port 8080       # Run SSE server on port 8080
        """,
    )

    parser.add_argument(
        "--transport",
        type=str,
        choices=["stdio", "http", "sse"],
        default="stdio",
        help="Transport protocol to use (default: stdio)",
    )

    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address for HTTP/SSE server (default: 127.0.0.1)",
    )

    parser.add_argument(
        "--port", type=int, default=8000, help="Port number for HTTP/SSE server (default: 8000)"
    )

    return parser


async def main():
    """Main entry point for the MCP server."""
    _install_signal_handlers()

    disable_auto_resume = os.environ.get("MCP_DISABLE_SESSION_RESUME", "false").lower() == "true"
    saved_session = None if disable_auto_resume else ctx.session_manager.load_session()
    if saved_session:
        ctx.analyzer, ctx.background_indexer, ctx.analyzer_initialized = _try_resume_session(
            saved_session
        )

    parser = _create_argument_parser()
    args = parser.parse_args()

    try:
        if args.transport == "stdio":
            await _run_stdio_transport(server)
        elif args.transport in ("http", "sse"):
            await _run_http_transport(server, args.host, args.port, args.transport)
        else:
            diagnostics.fatal(f"Unknown transport: {args.transport}")
            sys.exit(1)
    except asyncio.CancelledError:
        pass
    finally:
        await _cleanup_resources()


if __name__ == "__main__":
    # Register this module under its package name so that
    # `from clang_index_mcp.cpp_mcp_server import X` reuses it instead of
    # reimporting and re-running module-level code (which would fail
    # because Config.set_library_file() cannot be called twice).
    sys.modules.setdefault("clang_index_mcp.cpp_mcp_server", sys.modules[__name__])
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
