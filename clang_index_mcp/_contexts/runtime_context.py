"""Runtime and concurrency context.

Moved from _core/ to break the inward dependency violation where _core/
imported upper-layer types (_indexing.*).
"""

from dataclasses import dataclass

from .._core.cancellation_coordinator import CancellationCoordinator
from .._core.concurrency_context import ConcurrencyContext
from .._indexing.execution_config import ExecutionConfig
from .._indexing.indexing_progress_reporter import IndexingProgressReporter


@dataclass
class RuntimeContext:
    """Concurrency primitives, execution pool, cancellation, and progress reporting."""

    concurrency: ConcurrencyContext
    cancellation: CancellationCoordinator
    execution: ExecutionConfig
    progress_reporter: IndexingProgressReporter
