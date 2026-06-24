"""Runtime and concurrency context."""

from dataclasses import dataclass

from .cancellation_coordinator import CancellationCoordinator
from .concurrency_context import ConcurrencyContext
from .._indexing.execution_config import ExecutionConfig
from .._indexing.indexing_progress_reporter import IndexingProgressReporter


@dataclass
class RuntimeContext:
    """Concurrency primitives, execution pool, cancellation, and progress reporting."""

    concurrency: ConcurrencyContext
    cancellation: CancellationCoordinator
    execution: ExecutionConfig
    progress_reporter: IndexingProgressReporter
