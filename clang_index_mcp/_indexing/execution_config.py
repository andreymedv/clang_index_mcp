"""
Execution configuration for C++ Analyzer parallel processing.

Encapsulates the worker pool strategy (processes vs threads),
worker count, and pool lifecycle management.
"""

import os
from typing import Optional

from .._core import diagnostics
from .._indexing.worker_pool import WorkerPoolManager


class ExecutionConfig:
    """Manages parallel execution configuration and worker pool lifecycle."""

    def __init__(self, config_max_workers: Optional[int] = None):
        cpu_count = os.cpu_count() or 1

        if config_max_workers is not None:
            self.max_workers = min(config_max_workers, cpu_count)
            diagnostics.info(
                f"Using max_workers={self.max_workers} from config (cpu_count={cpu_count})"
            )
        else:
            self.max_workers = cpu_count

        self.use_processes: bool = os.environ.get("CPP_ANALYZER_USE_THREADS", "").lower() != "true"

        self.worker_pool = WorkerPoolManager(self.max_workers, self.use_processes)
