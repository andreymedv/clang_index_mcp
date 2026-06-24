"""
Compile-commands cache management.

Handles cache path resolution, file hashing, and pickle-based persistence of
parsed compile_commands.json data.
"""

import hashlib
import pickle
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Handle both package and script imports
try:
    from .._core import diagnostics
    from .._core.file_utils import hash_file
except ImportError:
    import diagnostics  # type: ignore[no-redef]
    from file_utils import hash_file  # type: ignore[no-redef]


def get_compile_commands_cache_path(
    cache_dir: Optional[Path], project_root: Path, compile_commands_path: str
) -> Path:
    """Get the cache file path for parsed compile commands.

    If cache_dir is provided (from CacheManager), stores cache in:
        <cache_dir>/compile_commands/<hash>.cache

    Where <hash> is derived from the absolute path of compile_commands.json
    to support multiple build configurations.

    If cache_dir is not provided, falls back to legacy location:
        <project_root>/.clang_index/compile_commands.cache
    """
    if cache_dir:
        # New location: .mcp_cache/<project>/compile_commands/<hash>.cache
        compile_commands_file = project_root / compile_commands_path

        # Hash the absolute path of compile_commands.json for uniqueness
        cc_path_hash = hashlib.md5(str(compile_commands_file.absolute()).encode()).hexdigest()[:16]

        # Create compile_commands subdirectory
        cc_cache_dir = cache_dir / "compile_commands"
        cc_cache_dir.mkdir(parents=True, exist_ok=True)

        return cc_cache_dir / f"{cc_path_hash}.cache"

    # Legacy location: <project_root>/.clang_index/compile_commands.cache
    legacy_dir = project_root / ".clang_index"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    return legacy_dir / "compile_commands.cache"


def get_file_hash(file_path: Path) -> str:
    """Get MD5 hash of a file for cache validation."""
    return hash_file(file_path)


def load_from_cache(
    compile_commands_file: Path,
    cache_dir: Optional[Path],
    project_root: Path,
    compile_commands_path: str,
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], float]]:
    """Try to load parsed commands from cache.

    Returns:
        Tuple of (compile_commands, file_to_command_map, last_modified) on success,
        or None if the cache is missing or invalid.
    """
    cache_path = get_compile_commands_cache_path(cache_dir, project_root, compile_commands_path)

    if not cache_path.exists():
        return None

    try:
        # Calculate current file hash
        current_hash = get_file_hash(compile_commands_file)
        if not current_hash:
            return None

        # Load cache
        with open(cache_path, "rb") as f:
            cache_data = pickle.load(f)

        # Validate cache
        if cache_data.get("file_hash") != current_hash:
            diagnostics.debug("Compile commands cache invalid: file changed")
            return None

        if cache_data.get("version") != "1.0":
            diagnostics.debug("Compile commands cache invalid: version mismatch")
            return None

        # Load cached data
        compile_commands = cache_data.get("compile_commands", {})
        file_to_command_map = cache_data.get("file_to_command_map", {})
        last_modified = compile_commands_file.stat().st_mtime

        diagnostics.debug(f"Loaded {len(compile_commands)} compile commands from cache (fast path)")
        return compile_commands, file_to_command_map, last_modified

    except Exception as e:
        diagnostics.debug(f"Failed to load from cache: {e}")
        return None


def save_to_cache(
    compile_commands_file: Path,
    cache_dir: Optional[Path],
    project_root: Path,
    compile_commands_path: str,
    compile_commands: Dict[str, Any],
    file_to_command_map: Dict[str, Any],
) -> None:
    """Save parsed commands to cache for faster loading next time."""
    cache_path = get_compile_commands_cache_path(cache_dir, project_root, compile_commands_path)

    try:
        current_hash = get_file_hash(compile_commands_file)

        cache_data = {
            "version": "1.0",
            "file_hash": current_hash,
            "compile_commands": compile_commands,
            "file_to_command_map": file_to_command_map,
        }

        # Atomic write via temp file
        temp_path = cache_path.with_suffix(".tmp")
        with open(temp_path, "wb") as f:
            pickle.dump(cache_data, f, protocol=pickle.HIGHEST_PROTOCOL)

        temp_path.replace(cache_path)
        diagnostics.debug(f"Saved compile commands cache to {cache_path}")

    except Exception as e:
        diagnostics.debug(f"Failed to save cache: {e}")


def get_compile_commands_hash(enabled: bool, project_root: Path, compile_commands_path: str) -> str:
    """Return the MD5 hash of compile_commands.json, or empty if unavailable."""
    if not enabled:
        return ""

    compile_commands_file = project_root / compile_commands_path
    if not compile_commands_file.exists():
        return ""

    try:
        with open(compile_commands_file, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception as e:
        diagnostics.warning(f"Failed to calculate compile_commands.json hash: {e}")
        return ""
