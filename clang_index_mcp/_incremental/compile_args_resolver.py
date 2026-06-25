"""Compile-argument resolution helper for incremental analysis.

Centralizes precomputing compile arguments for a batch of files so that worker
processes do not each need to load CompileCommandsManager.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:
    from .._contexts.incremental_context import IncrementalContext


def get_file_compile_args(ctx: "IncrementalContext", file_list: List[str]) -> Dict[str, List[str]]:
    """Precompute compile arguments for a list of files."""
    compilation_env = ctx.compilation_env
    file_compile_args = {}
    for file_path in file_list:
        file_path_obj = Path(file_path)
        args = compilation_env.get_compile_args_for_file(file_path_obj)
        file_compile_args[file_path] = args
    return file_compile_args
