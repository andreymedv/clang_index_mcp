"""Header Processing Tracker for first-win header extraction strategy.

This module provides thread-safe tracking of which headers have been processed
to avoid redundant symbol extraction when the same header is included by multiple
source files.

Key Assumption (ASSUMPTION-HE-01):
    For a given compile_commands.json version, a header produces identical symbols
    regardless of which source file includes it. This allows using header path as
    the sole identifier for deduplication.

Design Pattern:
    Thread-safe coordination using Lock-based atomic operations to prevent race
    conditions when multiple threads analyze different source files simultaneously.
"""

from threading import Lock
from typing import Dict, Set


class HeaderProcessingTracker:
    """
    Thread-safe tracker for header processing using first-win strategy.

    This class coordinates which headers have been processed to prevent redundant
    symbol extraction when the same header is included by multiple source files.

    Key Design Decisions:
        - Header identity: File path only (not compile args)
        - Change detection: File hash (MD5) comparison
        - Thread safety: Lock-based atomic operations
        - First-win: First source to include header extracts symbols

    Attributes:
        _lock: Threading lock for atomic operations
        _processed: Maps header path to file hash when processed
        _in_progress: Set of headers currently being processed
    """

    def __init__(self):
        """Initialize the header processing tracker."""
        self._lock = Lock()

        # Track: header_path -> file_hash when it was processed
        # File hash enables change detection
        self._processed: Dict[str, str] = {}

        # Track headers currently being processed (prevents race conditions)
        self._in_progress: Set[str] = set()

    def try_claim_header(self, header_path: str, current_file_hash: str) -> bool:
        """
        Try to claim a header for processing (first-win strategy).

        This operation is atomic: checking state and claiming the header occur
        within a single lock acquisition to prevent race conditions.

        Args:
            header_path: Absolute path to the header file
            current_file_hash: MD5 hash of the current file contents

        Returns:
            True if caller should process this header (won the claim)
            False if header already processed or being processed

        Processing Logic:
            1. If already processed with same hash -> return False (skip)
            2. If file hash changed -> remove old entry, return True (re-process)
            3. If currently in progress -> return False (another thread processing)
            4. Otherwise -> claim for processing, return True

        Thread Safety:
            All checks and state modifications protected by self._lock
        """
        with self._lock:
            # Check if already processed
            if header_path in self._processed:
                stored_hash = self._processed[header_path]

                # Hash matches - already processed with current version
                if stored_hash == current_file_hash:
                    return False  # Skip processing

                # Hash mismatch - file changed, need to re-process
                # Remove old entry and continue to claim
                del self._processed[header_path]

            # Check if currently being processed by another thread
            if header_path in self._in_progress:
                return False  # Another thread is processing it

            # Claim header for processing
            self._in_progress.add(header_path)
            return True  # Caller should process

    def mark_completed(self, header_path: str, file_hash: str):
        """
        Mark header as fully processed.

        Moves header from in-progress to processed state and stores the file hash
        for future change detection.

        Args:
            header_path: Absolute path to the header file
            file_hash: MD5 hash of the file contents when processed

        Thread Safety:
            Protected by self._lock
        """
        with self._lock:
            # Remove from in-progress
            self._in_progress.discard(header_path)

            # Mark as processed with current hash
            self._processed[header_path] = file_hash

    def invalidate_header(self, header_path: str):
        """
        Invalidate a header, forcing re-processing on next access.

        Removes header from both processed and in-progress sets. Next claim
        attempt will succeed.

        Args:
            header_path: Absolute path to the header file

        Use Cases:
            - External file change detection
            - Manual cache invalidation
            - Testing/debugging

        Thread Safety:
            Protected by self._lock
        """
        with self._lock:
            self._processed.pop(header_path, None)
            self._in_progress.discard(header_path)

    def clear_all(self):
        """
        Clear all tracking state (reset to empty).

        Use Cases:
            - compile_commands.json version changed
            - Full cache invalidation
            - Analyzer restart with fresh state

        Thread Safety:
            Protected by self._lock
        """
        with self._lock:
            self._processed.clear()
            self._in_progress.clear()

    def is_processed(self, header_path: str, file_hash: str) -> bool:
        """
        Check if header has been processed with the given hash.

        Args:
            header_path: Absolute path to the header file
            file_hash: MD5 hash to check against

        Returns:
            True if header processed with matching hash, False otherwise

        Thread Safety:
            Protected by self._lock
        """
        with self._lock:
            if header_path not in self._processed:
                return False
            return self._processed[header_path] == file_hash

    def get_processed_count(self) -> int:
        """
        Get the number of headers currently tracked as processed.

        Returns:
            Count of processed headers

        Use Cases:
            - Diagnostics and monitoring
            - Performance analysis
            - Testing verification

        Thread Safety:
            Protected by self._lock
        """
        with self._lock:
            return len(self._processed)

    def get_processed_headers(self) -> Dict[str, str]:
        """
        Get a copy of all processed headers and their hashes.

        Returns:
            Dictionary mapping header paths to file hashes

        Use Cases:
            - Cache persistence (save to disk)
            - Diagnostics and debugging
            - Testing verification

        Thread Safety:
            Returns a copy to avoid external modification
            Protected by self._lock
        """
        with self._lock:
            return dict(self._processed)

    def restore_processed_headers(self, processed_headers: Dict[str, str]):
        """
        Restore processed headers from cache.

        Replaces current processed state with provided state. Used when restoring
        from disk cache on analyzer startup.

        Args:
            processed_headers: Dictionary mapping header paths to file hashes

        Use Cases:
            - Restore from header_tracker.json on startup
            - Testing with predefined state

        Thread Safety:
            Protected by self._lock

        Note:
            Does not modify in_progress (should be empty on restore)
        """
        with self._lock:
            self._processed = dict(processed_headers)
