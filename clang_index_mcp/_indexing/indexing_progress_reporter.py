"""
Progress reporting utilities for indexing and refresh operations.

Extracted from CppAnalyzer to isolate the purely presentational / callback logic
of reporting indexing progress.
"""

import os
import sys
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from .._core import diagnostics
from .._mcp.state_manager import IndexingProgress


class IndexingProgressReporter:
    """Reports indexing and refresh progress to stderr and optional callbacks."""

    @staticmethod
    def is_terminal() -> bool:
        """Check if stderr is a terminal for progress reporting."""
        return (
            hasattr(sys.stderr, "isatty")
            and sys.stderr.isatty()
            and not os.environ.get("MCP_SESSION_ID")
            and not os.environ.get("CLAUDE_CODE_SESSION")
        )

    @staticmethod
    def should_report_progress(
        processed: int,
        total: int,
        current_time: float,
        last_report_time: float,
        is_terminal: bool,
    ) -> bool:
        """Determine if progress should be reported based on interval and environment."""
        if is_terminal:
            return (
                (processed <= 5)
                or (processed % 5 == 0)
                or ((current_time - last_report_time) > 2.0)
                or (processed == total)
            )
        return (
            (processed % 50 == 0)
            or ((current_time - last_report_time) > 5.0)
            or (processed == total)
        )

    @staticmethod
    def report_indexing_progress(
        processed: int,
        total: int,
        indexed_count: int,
        failed_count: int,
        cache_hits: int,
        start_time: float,
        is_terminal: bool,
        progress_callback: Optional[Callable],
        file_path: str,
    ):
        """Log progress and invoke callback."""
        current_time = time.time()
        elapsed = current_time - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        eta = (total - processed) / rate if rate > 0 else 0
        cache_rate = (cache_hits * 100 // processed) if processed > 0 else 0

        progress_str = (
            f"Progress: {processed}/{total} files ({100 * processed // total}%) - "
            f"Success: {indexed_count} - Failed: {failed_count} - "
            f"Cache: {cache_hits} ({cache_rate}%) - {rate:.1f} files/sec - ETA: {eta:.0f}s"
        )

        if is_terminal:
            print(f"\033[2K\r{progress_str}", end="", file=sys.stderr, flush=True)
        else:
            print(progress_str, file=sys.stderr, flush=True)

        if progress_callback:
            try:
                estimated_completion = datetime.now() + timedelta(seconds=eta) if eta > 0 else None
                progress = IndexingProgress(
                    total_files=total,
                    indexed_files=indexed_count,
                    failed_files=failed_count,
                    cache_hits=cache_hits,
                    current_file=file_path if processed < total else None,
                    start_time=datetime.fromtimestamp(start_time),
                    estimated_completion=estimated_completion,
                )
                progress_callback(progress)
            except Exception as e:
                diagnostics.debug(f"Progress callback failed: {e}")

    @staticmethod
    def maybe_report_indexing_progress(
        processed: int,
        total: int,
        indexed_count: int,
        failed_count: int,
        cache_hits: int,
        start_time: float,
        last_report_time: float,
        is_terminal: bool,
        progress_callback: Optional[Callable],
        file_path: str,
    ) -> float:
        """Report progress if enough time has passed; return updated last_report_time."""
        if IndexingProgressReporter.should_report_progress(
            processed, total, time.time(), last_report_time, is_terminal
        ):
            IndexingProgressReporter.report_indexing_progress(
                processed,
                total,
                indexed_count,
                failed_count,
                cache_hits,
                start_time,
                is_terminal,
                progress_callback,
                file_path,
            )
            return time.time()
        return last_report_time

    @staticmethod
    def report_refresh_progress(
        progress_callback: Callable,
        total_files: int,
        refreshed: int,
        failed: int,
        current_file: str,
        start_time: float,
    ):
        """Report refresh progress via callback."""
        try:
            processed = refreshed + failed
            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (total_files - processed) / rate if rate > 0 else 0

            estimated_completion = datetime.now() + timedelta(seconds=eta) if eta > 0 else None

            progress = IndexingProgress(
                total_files=total_files,
                indexed_files=refreshed,
                failed_files=failed,
                cache_hits=0,  # Not tracked during refresh
                current_file=current_file if processed < total_files else None,
                start_time=datetime.fromtimestamp(start_time),
                estimated_completion=estimated_completion,
            )

            progress_callback(progress)
        except Exception as e:
            # Don't fail refresh if progress callback fails
            diagnostics.debug(f"Progress callback failed: {e}")
