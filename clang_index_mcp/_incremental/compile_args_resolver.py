"""Compile-argument resolution helper for incremental analysis.

Centralizes precomputing compile arguments for a batch of files so that worker
processes do not each need to load CompileCommandsManager.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:
    from ..cpp_analyzer import CppAnalyzer


def get_file_compile_args(analyzer: "CppAnalyzer", file_list: List[str]) -> Dict[str, List[str]]:
    """Precompute compile arguments for a list of files."""
    compilation_env = analyzer.context.compilation_env
    assert compilation_env is not None
    file_compile_args = {}
    for file_path in file_list:
        file_path_obj = Path(file_path)
        args = compilation_env.get_compile_args_for_file(file_path_obj)
        file_compile_args[file_path] = args
    return file_compile_args
