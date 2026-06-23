"""
Task submission helpers for indexing and refresh operations.

Extracted from CppAnalyzer to isolate the logic that submits file-indexing work
items to the process pool executor.
"""

import os
from typing import TYPE_CHECKING, Dict, List

from .._indexing.indexing_task_spec import IndexingTaskSpec
from .._indexing.worker_pool import _process_file_worker

if TYPE_CHECKING:
    from concurrent.futures import Executor, Future

    from ..project_context import ProjectContext


class IndexingTaskSubmitter:
    """Submits indexing/refresh tasks to the process pool executor."""

    def __init__(self, context: "ProjectContext"):
        """
        Initialize the task submitter.

        Args:
            context: Shared project context with project root, identity, execution,
                     and compilation environment.
        """
        self.context = context
        self.project_root = context.project_root
        self.project_identity = context.project_identity
        assert context.execution is not None
        self.execution = context.execution
        assert context.compilation_env is not None
        self.compilation_env = context.compilation_env

    def submit_indexing_tasks(
        self, executor: "Executor", files: List[str], force: bool, include_dependencies: bool
    ) -> Dict["Future", str]:
        """Submit indexing tasks to the process pool executor."""
        config_file_str = (
            str(self.project_identity.config_file_path)
            if self.project_identity.config_file_path
            else None
        )
        file_compile_args = self.compilation_env._prepare_worker_compile_args(files)

        return {
            executor.submit(
                _process_file_worker,
                IndexingTaskSpec(
                    project_root=str(self.project_root),
                    config_file=config_file_str,
                    file_path=os.path.abspath(f),
                    force=force,
                    include_dependencies=include_dependencies,
                    compile_args=file_compile_args[f],
                ),
            ): os.path.abspath(f)
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
        project_root = str(self.project_root)
        config_file_str = (
            str(self.project_identity.config_file_path)
            if self.project_identity.config_file_path
            else None
        )

        all_files_to_process = list(modified_files) + list(new_files)
        file_compile_args = self.compilation_env._prepare_refresh_compile_args(all_files_to_process)

        for f in modified_files:
            future = executor.submit(
                _process_file_worker,
                IndexingTaskSpec(
                    project_root=project_root,
                    config_file=config_file_str,
                    file_path=os.path.abspath(f),
                    force=True,
                    include_dependencies=include_dependencies,
                    compile_args=file_compile_args[f],
                ),
            )
            future_to_file[future] = f
        for f in new_files:
            future = executor.submit(
                _process_file_worker,
                IndexingTaskSpec(
                    project_root=project_root,
                    config_file=config_file_str,
                    file_path=os.path.abspath(f),
                    force=False,
                    include_dependencies=include_dependencies,
                    compile_args=file_compile_args[f],
                ),
            )
            future_to_file[future] = f
        return future_to_file
