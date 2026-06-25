"""Change-category handlers for incremental analysis.

Each function handles one kind of change detected by the ChangeScanner:
compile_commands.json changes, header changes, source changes, and removed files.
"""

from typing import TYPE_CHECKING, Set

if TYPE_CHECKING:
    from .._contexts.incremental_context import IncrementalContext


def handle_compile_commands_change(ctx: "IncrementalContext") -> Set[str]:
    """
    Handle compile_commands.json change.

    Strategy:
        1. Load new compile_commands.json
        2. Compute diff with cached version
        3. Return files with changed/added/removed entries
        4. Invalidate all headers (compilation args affect preprocessing)

    Returns:
        Set of files to re-analyze
    """
    from .._core import diagnostics

    diagnostics.info("Handling compile_commands.json change...")

    cc_manager = ctx.compilation_env.compile_commands_manager
    assert cc_manager is not None
    cache_orchestrator = ctx.cache_orchestrator

    old_commands = cc_manager.file_to_command_map.copy()

    cc_manager._load_compile_commands()
    new_commands = cc_manager.file_to_command_map

    files_to_analyze: Set[str]
    if cc_manager.cache_backend is not None and hasattr(
        cc_manager.cache_backend, "set_compile_args_hash"
    ):

        def _extract_args(commands):
            result = {}
            for fp, cmd in commands.items():
                if cmd and isinstance(cmd[0], dict):
                    result[fp] = cmd[0].get("arguments", [])
                else:
                    result[fp] = cmd
            return result

        try:
            old_args = _extract_args(old_commands)
            new_args = _extract_args(new_commands)
        except (AttributeError, TypeError, IndexError):
            old_args = old_commands
            new_args = new_commands

        added, removed, changed = cc_manager.compute_commands_diff(old_args, new_args)

        diagnostics.info(f"Compile commands diff: +{len(added)} -{len(removed)} ~{len(changed)}")

        files_to_analyze = added | changed
        cc_manager.store_command_hashes(new_args)
    else:
        files_to_analyze = set(new_commands.keys())
        diagnostics.warning("No SQLite backend, re-analyzing all compile_commands files")

    cache_orchestrator.compile_commands_hash = cc_manager.get_compile_commands_hash()
    cache_orchestrator.clear_header_tracker()
    diagnostics.info("Invalidated all header tracking due to compile commands change")

    return files_to_analyze


def handle_header_change(ctx: "IncrementalContext", header_path: str) -> Set[str]:
    """
    Handle header file change.

    Finds transitive dependents via the dependency graph, invalidates the header,
    and returns the set of files to re-analyze.
    """
    from .._core import diagnostics

    diagnostics.info(f"Handling header change: {header_path}")

    dependency_graph = ctx.dependency_graph
    cache_orchestrator = ctx.cache_orchestrator

    if dependency_graph:
        dependents = dependency_graph.find_transitive_dependents(header_path)
        diagnostics.info(f"Header {header_path} affects {len(dependents)} files")
    else:
        diagnostics.warning("No dependency graph, cannot determine affected files")
        dependents = set()

    cache_orchestrator.invalidate_header(header_path)
    return dependents


def handle_source_change(ctx: "IncrementalContext", source_path: str) -> None:
    """
    Handle source file change.

    Source files are isolated; no additional prep work is required beyond adding
    the file to the re-analysis set.
    """
    from .._core import diagnostics

    diagnostics.debug(f"Handling source change: {source_path}")


def remove_file(ctx: "IncrementalContext", file_path: str) -> None:
    """Remove a deleted file from cache, indexes, and dependency graph."""
    from .._core import diagnostics

    diagnostics.info(f"Removing deleted file: {file_path}")
    cache_orchestrator = ctx.cache_orchestrator
    try:
        cache_orchestrator.remove_deleted_file(file_path)
    except Exception as e:
        diagnostics.warning(f"Failed to remove deleted file {file_path}: {e}")
