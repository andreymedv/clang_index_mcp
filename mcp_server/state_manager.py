#!/usr/bin/env python3
"""
State management for C++ analyzer lifecycle

Provides thread-safe state tracking and progress monitoring for the analyzer.
"""

import asyncio
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from threading import Lock, Event
from typing import Optional, Any, List


class AnalyzerState(Enum):
    """Analyzer lifecycle states"""

    UNINITIALIZED = "uninitialized"  # No project set
    INITIALIZING = "initializing"  # Analyzer created, preparing to index
    INDEXING = "indexing"  # Actively indexing files
    INDEXED = "indexed"  # Indexing complete, ready for queries
    REFRESHING = "refreshing"  # Incremental refresh in progress
    ERROR = "error"  # Indexing failed


@dataclass
class IndexingProgress:
    """Real-time indexing progress information"""

    total_files: int
    indexed_files: int
    failed_files: int
    cache_hits: int
    current_file: Optional[str]
    start_time: datetime
    estimated_completion: Optional[datetime]

    @property
    def completion_percentage(self) -> float:
        """Calculate completion percentage"""
        if self.total_files == 0:
            return 0.0
        return self.indexed_files / self.total_files * 100.0

    @property
    def is_complete(self) -> bool:
        """Check if indexing is complete"""
        return self.indexed_files + self.failed_files >= self.total_files

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "total_files": self.total_files,
            "indexed_files": self.indexed_files,
            "failed_files": self.failed_files,
            "cache_hits": self.cache_hits,
            "completion_percentage": self.completion_percentage,
            "current_file": self.current_file,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "estimated_completion": (
                self.estimated_completion.isoformat() if self.estimated_completion else None
            ),
        }


class AnalyzerStateManager:
    """Thread-safe state management for analyzer lifecycle"""

    def __init__(self):
        self._state = AnalyzerState.UNINITIALIZED
        self._lock = Lock()
        self._indexed_event = Event()  # Signals when indexing completes
        self._progress: Optional[IndexingProgress] = None

    @property
    def state(self) -> AnalyzerState:
        """Get current analyzer state (thread-safe)"""
        with self._lock:
            result: AnalyzerState = self._state
            return result

    def transition_to(self, new_state: AnalyzerState):
        """
        Transition to a new state (thread-safe)

        Args:
            new_state: Target state to transition to
        """
        with self._lock:
            old_state = self._state
            self._state = new_state

            # Set/clear indexed event based on state
            if new_state == AnalyzerState.INDEXED:
                self._indexed_event.set()
            elif new_state == AnalyzerState.INDEXING:
                self._indexed_event.clear()

            # Debug logging (will be picked up by diagnostics module)
            try:
                from . import diagnostics

                diagnostics.debug(f"State transition: {old_state.value} -> {new_state.value}")
            except ImportError:
                pass

    def wait_for_indexed(self, timeout: Optional[float] = None) -> bool:
        """
        Wait until indexing completes (or timeout)

        Args:
            timeout: Maximum time to wait in seconds (None = wait forever)

        Returns:
            True if indexing completed, False if timeout occurred
        """
        result: bool = self._indexed_event.wait(timeout)
        return result

    def update_progress(self, progress: IndexingProgress):
        """
        Update indexing progress information (thread-safe)

        Args:
            progress: Current progress information
        """
        with self._lock:
            self._progress = progress

    def get_progress(self) -> Optional[IndexingProgress]:
        """
        Get current indexing progress (thread-safe)

        Returns:
            Current progress information, or None if not indexing
        """
        with self._lock:
            return self._progress

    def is_ready_for_queries(self) -> bool:
        """
        Check if analyzer can handle queries (even if partial)

        Returns:
            True if queries are allowed (INDEXING, INDEXED, REFRESHING states)
        """
        with self._lock:
            return self._state in (
                AnalyzerState.INDEXING,
                AnalyzerState.INDEXED,
                AnalyzerState.REFRESHING,
            )

    def is_fully_indexed(self) -> bool:
        """
        Check if analyzer has completed indexing

        Returns:
            True only if state is INDEXED
        """
        with self._lock:
            result: bool = self._state == AnalyzerState.INDEXED
            return result

    def get_status_dict(self) -> dict:
        """
        Get complete status as dictionary for JSON serialization

        Returns:
            Dictionary with state, progress, and status flags
        """
        with self._lock:
            status = {
                "state": self._state.value,
                "is_fully_indexed": self._state == AnalyzerState.INDEXED,
                "is_ready_for_queries": self._state
                in (AnalyzerState.INDEXING, AnalyzerState.INDEXED, AnalyzerState.REFRESHING),
                "progress": self._progress.to_dict() if self._progress else None,
            }
            return status


class BackgroundIndexer:
    """
    Manages background indexing with async support

    Coordinates between synchronous indexing code and async MCP server.
    """

    def __init__(self, analyzer: Any, state_manager: AnalyzerStateManager):
        """
        Initialize background indexer

        Args:
            analyzer: CppAnalyzer instance
            state_manager: State manager for tracking progress
        """
        self.analyzer = analyzer
        self.state_manager = state_manager
        self._indexing_task: Optional[asyncio.Task] = None

    async def start_indexing(self, force: bool = False, include_dependencies: bool = True) -> int:
        """
        Start background indexing (non-blocking)

        Args:
            force: Force re-indexing even if cache exists
            include_dependencies: Include dependency files

        Returns:
            Number of files indexed

        Raises:
            RuntimeError: If indexing is already in progress
        """
        if self._indexing_task and not self._indexing_task.done():
            raise RuntimeError("Indexing already in progress")

        self.state_manager.transition_to(AnalyzerState.INDEXING)

        # Run synchronous index_project in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()

        # Create progress callback that updates state_manager
        def progress_callback(progress: IndexingProgress):
            """Callback to update progress in state manager"""
            self.state_manager.update_progress(progress)

        try:
            indexed_count = await loop.run_in_executor(
                None,  # Use default executor
                lambda: self.analyzer.index_project(
                    force=force,
                    include_dependencies=include_dependencies,
                    progress_callback=progress_callback,
                ),
            )

            self.state_manager.transition_to(AnalyzerState.INDEXED)
            result: int = indexed_count
            return result

        except Exception as e:
            self.state_manager.transition_to(AnalyzerState.ERROR)
            # Log error if diagnostics available
            try:
                from . import diagnostics

                diagnostics.error(f"Indexing failed: {e}")
            except ImportError:
                pass
            raise

    def is_indexing(self) -> bool:
        """
        Check if indexing is currently running

        Returns:
            True if indexing task exists and is not done
        """
        return self._indexing_task is not None and not self._indexing_task.done()

    async def wait_for_completion(self, timeout: Optional[float] = None):
        """
        Wait for indexing to complete

        Args:
            timeout: Maximum time to wait in seconds

        Raises:
            asyncio.TimeoutError: If timeout expires
        """
        if self._indexing_task:
            await asyncio.wait_for(self._indexing_task, timeout=timeout)

    async def cancel(self):
        """
        Cancel background indexing if running

        Attempts to gracefully cancel the indexing task and interrupt
        the analyzer's indexing operation.
        """
        if self._indexing_task and not self._indexing_task.done():
            # Try to interrupt the analyzer's indexing
            # This sets the interrupt flag which the analyzer checks during indexing
            if hasattr(self.analyzer, "_interrupt_indexing"):
                self.analyzer._interrupt_indexing = True

            # Cancel the task
            self._indexing_task.cancel()
            try:
                await self._indexing_task
            except asyncio.CancelledError:
                pass  # Expected when canceling

            self._indexing_task = None


class QueryBehaviorPolicy(Enum):
    """Policy for handling queries during indexing"""

    ALLOW_PARTIAL = "allow_partial"  # Allow queries during indexing (default)
    BLOCK = "block"  # Block queries until indexing completes
    REJECT = "reject"  # Reject queries during indexing with error


class QueryCompletenessStatus(Enum):
    """Status of query result completeness"""

    PARTIAL = "partial"  # Query executed during indexing (incomplete)
    TRUNCATED = "truncated"  # Results truncated due to max_results limit
    LARGE = "large"  # Large result set (>20 results without max_results)


class QueryMetadata:
    """Metadata about query execution context"""

    def __init__(
        self,
        status: QueryCompletenessStatus,
        indexed_files: int,
        total_files: int,
        completion_percentage: float,
        timestamp: str,
        warning: Optional[str] = None,
    ):
        self.status = status
        self.indexed_files = indexed_files
        self.total_files = total_files
        self.completion_percentage = completion_percentage
        self.timestamp = timestamp
        self.warning = warning

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "status": self.status.value,
            "indexed_files": self.indexed_files,
            "total_files": self.total_files,
            "completion_percentage": self.completion_percentage,
            "timestamp": self.timestamp,
            "warning": self.warning,
        }


class EnhancedQueryResult:
    """Wrapper for query results with conditional metadata.

    Design principle: Silence = Success. Metadata only appears for special conditions
    that require LLM guidance (empty, truncated, large, partial).
    Normal results (1-20 items, fully indexed) return just {"data": ...}.
    """

    # Threshold for "large" result sets that trigger metadata
    LARGE_RESULT_THRESHOLD = 20

    def __init__(
        self,
        data: Any,
        metadata: Optional[QueryMetadata] = None,
        status: Optional[QueryCompletenessStatus] = None,
        extra_metadata: Optional[dict] = None,
        next_steps: Optional[List[str]] = None,
    ):
        """
        Initialize EnhancedQueryResult.

        Args:
            data: Query result data
            metadata: Full QueryMetadata object (for partial indexing case)
            status: Simple status without full metadata (for empty/truncated/large)
            extra_metadata: Additional metadata fields (returned, total_matches, etc.)
            next_steps: Conditional workflow hints for LLMs (only populated when useful)
        """
        self.data = data
        self.metadata = metadata
        self.status = status
        self.extra_metadata = extra_metadata or {}
        self.next_steps: List[str] = next_steps or []

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization.

        Returns just {"data": ...} for normal results (silence = success).
        Includes metadata only for special conditions.
        """
        result = {"data": self.data}

        # Partial indexing case - include full metadata
        if self.metadata and self.metadata.status == QueryCompletenessStatus.PARTIAL:
            metadata_dict = self.metadata.to_dict()
            if self.next_steps:
                metadata_dict["next_steps"] = self.next_steps
            result["metadata"] = metadata_dict
            return result

        # Build metadata dict (may remain empty for normal results)
        secondary_dict: dict = {}
        if self.status:
            secondary_dict["status"] = self.status.value
        secondary_dict.update(self.extra_metadata)
        if self.next_steps:
            secondary_dict["next_steps"] = self.next_steps
        if secondary_dict:
            result["metadata"] = secondary_dict

        return result

    @staticmethod
    def create_normal(data: Any, next_steps: Optional[List[str]] = None) -> "EnhancedQueryResult":
        """
        Create result for normal case (1-20 results, fully indexed).

        No metadata included unless next_steps are provided.
        """
        return EnhancedQueryResult(data, next_steps=next_steps)

    @staticmethod
    def create_empty(
        data: Any,
        suggestions: Optional[List[str]] = None,
        fallback: Any = None,
    ) -> "EnhancedQueryResult":
        """
        Create result for empty results case.

        Args:
            data: Empty result data (usually [] or {})
            suggestions: Suggestions for broadening the search
            fallback: Optional FallbackResult from smart_fallback module
        """
        if fallback is not None:
            extra = {"fallback": fallback.to_metadata()}
        elif suggestions is not None:
            # Caller provided explicit suggestions (may be [] to suppress hints entirely)
            extra = {"suggestions": suggestions} if suggestions else {}
        else:
            extra = {
                "suggestions": [
                    "Broaden pattern (e.g., use '.*' prefix/suffix for partial match)",
                    "Check spelling of symbol name",
                    "Verify file is indexed (use get_indexing_status)",
                    "Try search_symbols for unified search across types",
                ]
            }
        return EnhancedQueryResult(
            data,
            extra_metadata=extra,
        )

    @staticmethod
    def create_truncated(
        data: Any,
        returned: int,
        total_matches: int,
    ) -> "EnhancedQueryResult":
        """
        Create result for truncated case (max_results limit applied).

        Args:
            data: Truncated result data
            returned: Number of results returned
            total_matches: Total number of matches before truncation
        """
        return EnhancedQueryResult(
            data,
            status=QueryCompletenessStatus.TRUNCATED,
            extra_metadata={
                "returned": returned,
                "total_matches": total_matches,
            },
        )

    @staticmethod
    def create_large(
        data: Any,
        result_count: int,
    ) -> "EnhancedQueryResult":
        """
        Create result for large result set (>20 results without max_results).

        Args:
            data: Large result data
            result_count: Number of results returned
        """
        return EnhancedQueryResult(
            data,
            status=QueryCompletenessStatus.LARGE,
            extra_metadata={
                "result_count": result_count,
                "hint": "Consider using max_results parameter or narrowing pattern",
            },
        )

    @staticmethod
    def create_from_state(
        data: Any, state_manager: AnalyzerStateManager, tool_name: str = "query"
    ) -> "EnhancedQueryResult":
        """
        Create result with current state metadata.

        Used for partial indexing case only. For other special conditions
        (empty, truncated, large), use the specific factory methods.

        Args:
            data: Query result data
            state_manager: State manager for current indexing state
            tool_name: Name of tool being executed (for custom warnings)

        Returns:
            EnhancedQueryResult with appropriate metadata
        """
        progress = state_manager.get_progress()

        # Determine status and warning
        if state_manager.is_fully_indexed():
            # Fully indexed - return normal result (no metadata)
            return EnhancedQueryResult.create_normal(data)
        else:
            status = QueryCompletenessStatus.PARTIAL

            # Generate detailed warning message
            if progress:
                completion = progress.completion_percentage
                indexed = progress.indexed_files
                total = progress.total_files

                # Customize warning based on tool type
                incomplete_type = "symbols"
                if "class" in tool_name.lower():
                    incomplete_type = "classes"
                elif "function" in tool_name.lower():
                    incomplete_type = "functions"
                elif "symbol" in tool_name.lower():
                    incomplete_type = "symbols"

                warning = (
                    f"[WARNING]  INCOMPLETE RESULTS: Only {completion:.1f}% of files indexed "
                    f"({indexed:,}/{total:,}). Results may be missing {incomplete_type}. "
                    f"Use 'get_indexing_status' to check progress or 'wait_for_indexing' "
                    f"to wait for completion."
                )
            else:
                warning = (
                    "[WARNING]  INCOMPLETE RESULTS: Indexing in progress. "
                    "Results may be incomplete. Use 'wait_for_indexing' to wait for completion."
                )

            # Create metadata
            metadata = QueryMetadata(
                status=status,
                indexed_files=progress.indexed_files if progress else 0,
                total_files=progress.total_files if progress else 0,
                completion_percentage=progress.completion_percentage if progress else 0.0,
                timestamp=datetime.now().isoformat(),
                warning=warning,
            )

            return EnhancedQueryResult(data, metadata=metadata)
