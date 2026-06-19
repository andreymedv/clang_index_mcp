"""
Task submission helpers for indexing and refresh operations.

Extracted from CppAnalyzer to isolate the logic that submits file-indexing work
items to the execution pool (process or thread based).
"""

import os
from typing import TYPE_CHECKING, Any, Callable, Dict, List

from .worker_pool import _process_file_worker

if TYPE_CHECKING:
    from concurrent.futures import Executor, Future


class IndexingTaskSubmitter:
    """Submits indexing/refresh tasks to the configured executor."""

    def __init__(
        self,
        project_root: Any,
        project_identity: Any,
        execution: Any,
        compilation_env: Any,
        index_file: Callable[[str, bool], Any],
    ):
        """
        Initialize the task submitter.

        Args:
            project_root: Resolved project root path.
            project_identity: ProjectIdentity instance.
            execution: ExecutionConfig instance.
            compilation_env: CompilationEnvironment instance.
            index_file: Callable used in thread mode to index a single file.
        """
        self.project_root = project_root
        self.project_identity = project_identity
        self.execution = execution
        self.compilation_env = compilation_env
        self.index_file = index_file

    def submit_indexing_tasks(
        self, executor: "Executor", files: List[str], force: bool, include_dependencies: bool
    ) -> Dict["Future", str]:
        """Submit indexing tasks to executor."""
        if self.execution.use_processes:
            config_file_str = (
                str(self.project_identity.config_file_path)
                if self.project_identity.config_file_path
                else None
            )
            file_compile_args = self.compilation_env._prepare_worker_compile_args(files)

            return {
                executor.submit(
                    _process_file_worker,
                    (
                        str(self.project_root),
                        config_file_str,
                        os.path.abspath(f),
                        force,
                        include_dependencies,
                        file_compile_args[f],
                    ),
                ): os.path.abspath(f)
                for f in files
            }
        else:
            return {
                executor.submit(self.index_file, os.path.abspath(f), force): os.path.abspath(f)
                for f in files
            }

    def submit_refresh_tasks(
        self,
        executor: "Executor",
        modified_files: List[str],
        new_files: List[str],
        include_dependencies: bool,
    ) -> Dict["Future", str]:
        """Submit indexing tasks for modified and new files."""
        future_to_file: Dict["Future", str] = {}
        if self.execution.use_processes:
            project_root = str(self.project_root)
            config_file_str = (
                str(self.project_identity.config_file_path)
                if self.project_identity.config_file_path
                else None
            )

            all_files_to_process = list(modified_files) + list(new_files)
            file_compile_args = self.compilation_env._prepare_refresh_compile_args(
                all_files_to_process
            )

            for f in modified_files:
                future = executor.submit(
                    _process_file_worker,
                    (
                        project_root,
                        config_file_str,
                        os.path.abspath(f),
                        True,
                        include_dependencies,
                        file_compile_args[f],
                    ),
                )
                future_to_file[future] = f
            for f in new_files:
                future = executor.submit(
                    _process_file_worker,
                    (
                        project_root,
                        config_file_str,
                        os.path.abspath(f),
                        False,
                        include_dependencies,
                        file_compile_args[f],
                    ),
                )
                future_to_file[future] = f
        else:
            for f in modified_files:
                future_to_file[executor.submit(self.index_file, f, True)] = f
            for f in new_files:
                future_to_file[executor.submit(self.index_file, f, False)] = f
        return future_to_file
