"""
Compile-commands diff and argument-hash helpers.

These utilities detect changes between two snapshots of compile commands and
manage per-file argument hashes stored in an optional cache backend.
"""

from typing import Any, Dict, List, Optional, Set, Tuple

# Handle both package and script imports
try:
    from .._core import diagnostics
    from .._core.file_utils import hash_compile_args
except ImportError:
    import diagnostics  # type: ignore[no-redef]
    from file_utils import hash_compile_args  # type: ignore[no-redef]


def compute_commands_diff(
    old_commands: Dict[str, List[str]], new_commands: Dict[str, List[str]]
) -> Tuple[Set[str], Set[str], Set[str]]:
    """
    Compute difference between two compile-command maps.

    Returns:
        Tuple of (added_files, removed_files, changed_files).
    """
    old_files = set(old_commands.keys())
    new_files = set(new_commands.keys())

    added = new_files - old_files
    removed = old_files - new_files
    changed = {
        file_path
        for file_path in old_files & new_files
        if old_commands[file_path] != new_commands[file_path]
    }

    diagnostics.debug(f"Compile commands diff: +{len(added)} -{len(removed)} ~{len(changed)}")
    return added, removed, changed


def hash_args(args: List[str]) -> str:
    """Return a stable hash of a compilation argument list."""
    return hash_compile_args(args, normalize_order=False)


def store_command_hashes(commands: Dict[str, List[str]], cache_backend: Optional[Any]) -> int:
    """Store argument hashes for the given compile commands in SQLite."""
    if cache_backend is None:
        return 0

    stored = 0
    for file_path, args in commands.items():
        args_hash = hash_args(args)
        if cache_backend.set_compile_args_hash(file_path, args_hash):
            stored += 1

    if stored > 0:
        diagnostics.debug(f"Stored {stored} compile command hashes")
    return stored


def get_stored_args_hash(file_path: str, cache_backend: Optional[Any]) -> str:
    """Return the stored argument hash for a file, or empty string."""
    if cache_backend is None:
        return ""
    result = cache_backend.get_compile_args_hash(file_path)
    return result or ""


def has_args_changed(file_path: str, current_args: List[str], cache_backend: Optional[Any]) -> bool:
    """Return True if the stored argument hash differs from the current args."""
    stored_hash = get_stored_args_hash(file_path, cache_backend)
    if not stored_hash:
        return True
    return stored_hash != hash_args(current_args)


def clear_stored_command_hashes(cache_backend: Optional[Any]) -> int:
    """Clear all stored compilation argument hashes."""
    if cache_backend is None:
        return 0
    cleared = int(cache_backend.clear_compile_args_hashes() or 0)
    if cleared > 0:
        diagnostics.info(f"Cleared {cleared} stored command hashes")
    return cleared
