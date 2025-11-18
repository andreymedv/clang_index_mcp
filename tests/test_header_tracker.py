"""Tests for HeaderProcessingTracker class.

Tests the header extraction first-win strategy and thread safety
as documented in REQUIREMENTS.md Section 11.
"""

import pytest
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from mcp_server.header_tracker import HeaderProcessingTracker


class TestHeaderProcessingTrackerBasic:
    """Basic functionality tests for HeaderProcessingTracker."""

    def test_initial_state_empty(self):
        """Tracker should start with no processed headers."""
        tracker = HeaderProcessingTracker()
        assert tracker.get_processed_count() == 0
        assert tracker.get_processed_headers() == {}

    def test_try_claim_header_first_time_succeeds(self):
        """First claim for a header should succeed (REQ-11.2.1)."""
        tracker = HeaderProcessingTracker()
        result = tracker.try_claim_header("/path/to/header.h", "abc123")
        assert result is True

    def test_try_claim_header_after_completed_same_hash_fails(self):
        """Claiming completed header with same hash should fail (REQ-11.2.2)."""
        tracker = HeaderProcessingTracker()

        # First claim and mark completed
        tracker.try_claim_header("/path/to/header.h", "abc123")
        tracker.mark_completed("/path/to/header.h", "abc123")

        # Second claim with same hash should fail
        result = tracker.try_claim_header("/path/to/header.h", "abc123")
        assert result is False

    def test_try_claim_header_after_completed_different_hash_succeeds(self):
        """Claiming completed header with different hash should succeed (REQ-11.3.4)."""
        tracker = HeaderProcessingTracker()

        # First claim and mark completed
        tracker.try_claim_header("/path/to/header.h", "abc123")
        tracker.mark_completed("/path/to/header.h", "abc123")

        # Second claim with different hash should succeed (file changed)
        result = tracker.try_claim_header("/path/to/header.h", "xyz789")
        assert result is True

    def test_try_claim_header_while_in_progress_fails(self):
        """Claiming header already in progress should fail (REQ-11.6.2)."""
        tracker = HeaderProcessingTracker()

        # First claim (now in progress)
        tracker.try_claim_header("/path/to/header.h", "abc123")

        # Second claim while in progress should fail
        result = tracker.try_claim_header("/path/to/header.h", "abc123")
        assert result is False

    def test_mark_completed_moves_from_in_progress(self):
        """mark_completed should move header from in_progress to processed."""
        tracker = HeaderProcessingTracker()

        tracker.try_claim_header("/path/to/header.h", "abc123")
        tracker.mark_completed("/path/to/header.h", "abc123")

        assert tracker.get_processed_count() == 1
        assert tracker.is_processed("/path/to/header.h", "abc123")

    def test_invalidate_header_removes_from_processed(self):
        """invalidate_header should allow re-processing."""
        tracker = HeaderProcessingTracker()

        tracker.try_claim_header("/path/to/header.h", "abc123")
        tracker.mark_completed("/path/to/header.h", "abc123")

        # Invalidate
        tracker.invalidate_header("/path/to/header.h")

        # Should be able to claim again
        result = tracker.try_claim_header("/path/to/header.h", "abc123")
        assert result is True

    def test_clear_all_resets_state(self):
        """clear_all should reset all tracking state (REQ-11.4.3)."""
        tracker = HeaderProcessingTracker()

        # Add some headers
        tracker.try_claim_header("/path/to/header1.h", "abc123")
        tracker.mark_completed("/path/to/header1.h", "abc123")
        tracker.try_claim_header("/path/to/header2.h", "def456")

        # Clear all
        tracker.clear_all()

        assert tracker.get_processed_count() == 0
        assert tracker.get_processed_headers() == {}

    def test_is_processed_with_matching_hash(self):
        """is_processed should return True for matching hash."""
        tracker = HeaderProcessingTracker()

        tracker.try_claim_header("/path/to/header.h", "abc123")
        tracker.mark_completed("/path/to/header.h", "abc123")

        assert tracker.is_processed("/path/to/header.h", "abc123") is True
        assert tracker.is_processed("/path/to/header.h", "different") is False

    def test_is_processed_with_non_existent_header(self):
        """is_processed should return False for non-existent header."""
        tracker = HeaderProcessingTracker()
        assert tracker.is_processed("/path/to/nonexistent.h", "abc123") is False

    def test_get_processed_headers_returns_copy(self):
        """get_processed_headers should return a copy."""
        tracker = HeaderProcessingTracker()

        tracker.try_claim_header("/path/to/header.h", "abc123")
        tracker.mark_completed("/path/to/header.h", "abc123")

        headers = tracker.get_processed_headers()
        headers["/new/header.h"] = "new_hash"  # Modify the copy

        # Original should be unchanged
        assert "/new/header.h" not in tracker.get_processed_headers()

    def test_restore_processed_headers(self):
        """restore_processed_headers should restore from cache (REQ-11.5.3)."""
        tracker = HeaderProcessingTracker()

        # Restore from saved state
        saved_state = {
            "/path/to/header1.h": "hash1",
            "/path/to/header2.h": "hash2",
        }
        tracker.restore_processed_headers(saved_state)

        assert tracker.get_processed_count() == 2
        assert tracker.is_processed("/path/to/header1.h", "hash1")
        assert tracker.is_processed("/path/to/header2.h", "hash2")


class TestHeaderProcessingTrackerMultipleHeaders:
    """Tests for multiple header processing."""

    def test_multiple_headers_tracked_independently(self):
        """Each header should be tracked independently."""
        tracker = HeaderProcessingTracker()

        # Claim and complete multiple headers
        headers = [
            ("/path/to/header1.h", "hash1"),
            ("/path/to/header2.h", "hash2"),
            ("/path/to/header3.h", "hash3"),
        ]

        for path, file_hash in headers:
            assert tracker.try_claim_header(path, file_hash) is True
            tracker.mark_completed(path, file_hash)

        assert tracker.get_processed_count() == 3
        for path, file_hash in headers:
            assert tracker.is_processed(path, file_hash)

    def test_first_win_strategy(self):
        """First source to claim header should win (REQ-11.2.1)."""
        tracker = HeaderProcessingTracker()

        # First source claims
        result1 = tracker.try_claim_header("/shared/header.h", "abc123")

        # Second source tries to claim same header
        result2 = tracker.try_claim_header("/shared/header.h", "abc123")

        assert result1 is True
        assert result2 is False


class TestHeaderProcessingTrackerThreadSafety:
    """Thread safety tests for HeaderProcessingTracker (REQ-11.6)."""

    def test_concurrent_claims_only_one_wins(self):
        """Only one thread should win when concurrently claiming (REQ-11.6.4)."""
        tracker = HeaderProcessingTracker()
        results = []

        def try_claim():
            result = tracker.try_claim_header("/concurrent/header.h", "abc123")
            results.append(result)

        threads = [threading.Thread(target=try_claim) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one thread should win
        assert sum(results) == 1
        assert results.count(True) == 1
        assert results.count(False) == 9

    def test_concurrent_different_headers_all_succeed(self):
        """Concurrent claims for different headers should all succeed."""
        tracker = HeaderProcessingTracker()
        results = {}
        lock = threading.Lock()

        def claim_header(index):
            path = f"/path/to/header{index}.h"
            result = tracker.try_claim_header(path, f"hash{index}")
            with lock:
                results[index] = result

        threads = [threading.Thread(target=claim_header, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should succeed
        assert all(results.values())
        assert len(results) == 10

    def test_concurrent_read_write_operations(self):
        """Concurrent read/write operations should be thread-safe."""
        tracker = HeaderProcessingTracker()
        errors = []

        def writer():
            try:
                for i in range(100):
                    path = f"/path/header{i}.h"
                    if tracker.try_claim_header(path, f"hash{i}"):
                        tracker.mark_completed(path, f"hash{i}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    _ = tracker.get_processed_count()
                    _ = tracker.get_processed_headers()
            except Exception as e:
                errors.append(e)

        # Mix writers and readers
        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=writer))
            threads.append(threading.Thread(target=reader))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_high_concurrency_stress_test(self):
        """Stress test with many concurrent operations (REQ-11.6.4)."""
        tracker = HeaderProcessingTracker()
        successful_claims = []
        lock = threading.Lock()

        def worker(worker_id):
            local_claims = 0
            for i in range(50):
                path = f"/stress/header{i}.h"
                if tracker.try_claim_header(path, f"hash{i}"):
                    tracker.mark_completed(path, f"hash{i}")
                    local_claims += 1
            with lock:
                successful_claims.append(local_claims)

        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = [executor.submit(worker, i) for i in range(16)]
            for f in futures:
                f.result()

        # Each header should be processed exactly once
        assert tracker.get_processed_count() == 50
        # Total claims should be 50 (each header claimed once)
        assert sum(successful_claims) == 50


class TestHeaderProcessingTrackerChangeDetection:
    """Tests for header change detection (REQ-11.3)."""

    def test_hash_change_triggers_reprocessing(self):
        """Changed file hash should allow reprocessing (REQ-11.3.3)."""
        tracker = HeaderProcessingTracker()

        # Initial processing
        tracker.try_claim_header("/path/header.h", "original_hash")
        tracker.mark_completed("/path/header.h", "original_hash")

        # File content changed
        result = tracker.try_claim_header("/path/header.h", "new_hash")
        assert result is True

        # Complete with new hash
        tracker.mark_completed("/path/header.h", "new_hash")
        assert tracker.is_processed("/path/header.h", "new_hash")
        assert not tracker.is_processed("/path/header.h", "original_hash")

    def test_multiple_hash_changes(self):
        """Multiple consecutive hash changes should work correctly."""
        tracker = HeaderProcessingTracker()
        path = "/path/header.h"

        for i in range(5):
            current_hash = f"hash_v{i}"
            result = tracker.try_claim_header(path, current_hash)
            assert result is True
            tracker.mark_completed(path, current_hash)
            assert tracker.is_processed(path, current_hash)


class TestHeaderProcessingTrackerPersistence:
    """Tests for cache persistence (REQ-11.5)."""

    def test_save_and_restore_round_trip(self):
        """Should preserve state across save/restore cycle (REQ-11.5.1)."""
        tracker1 = HeaderProcessingTracker()

        # Build up state
        headers = {
            "/path/header1.h": "hash1",
            "/path/header2.h": "hash2",
            "/path/header3.h": "hash3",
        }

        for path, file_hash in headers.items():
            tracker1.try_claim_header(path, file_hash)
            tracker1.mark_completed(path, file_hash)

        # Save state
        saved = tracker1.get_processed_headers()

        # Restore to new tracker
        tracker2 = HeaderProcessingTracker()
        tracker2.restore_processed_headers(saved)

        # Verify state
        assert tracker2.get_processed_count() == 3
        for path, file_hash in headers.items():
            assert tracker2.is_processed(path, file_hash)

    def test_restore_replaces_existing_state(self):
        """restore_processed_headers should replace, not merge."""
        tracker = HeaderProcessingTracker()

        # Initial state
        tracker.try_claim_header("/old/header.h", "old_hash")
        tracker.mark_completed("/old/header.h", "old_hash")

        # Restore new state (should replace)
        new_state = {"/new/header.h": "new_hash"}
        tracker.restore_processed_headers(new_state)

        assert tracker.get_processed_count() == 1
        assert tracker.is_processed("/new/header.h", "new_hash")
        assert not tracker.is_processed("/old/header.h", "old_hash")


class TestHeaderProcessingTrackerEdgeCases:
    """Edge case tests for HeaderProcessingTracker."""

    def test_empty_path(self):
        """Should handle empty path gracefully."""
        tracker = HeaderProcessingTracker()
        result = tracker.try_claim_header("", "hash")
        assert result is True
        tracker.mark_completed("", "hash")
        assert tracker.is_processed("", "hash")

    def test_empty_hash(self):
        """Should handle empty hash gracefully."""
        tracker = HeaderProcessingTracker()
        result = tracker.try_claim_header("/path/header.h", "")
        assert result is True
        tracker.mark_completed("/path/header.h", "")
        assert tracker.is_processed("/path/header.h", "")

    def test_very_long_path(self):
        """Should handle very long paths."""
        tracker = HeaderProcessingTracker()
        long_path = "/very" + "/deep" * 100 + "/header.h"
        result = tracker.try_claim_header(long_path, "hash")
        assert result is True
        tracker.mark_completed(long_path, "hash")
        assert tracker.is_processed(long_path, "hash")

    def test_unicode_path(self):
        """Should handle Unicode characters in paths."""
        tracker = HeaderProcessingTracker()
        unicode_path = "/путь/到/ヘッダー.h"
        result = tracker.try_claim_header(unicode_path, "hash")
        assert result is True
        tracker.mark_completed(unicode_path, "hash")
        assert tracker.is_processed(unicode_path, "hash")

    def test_invalidate_non_existent_header(self):
        """Invalidating non-existent header should not error."""
        tracker = HeaderProcessingTracker()
        tracker.invalidate_header("/non/existent.h")  # Should not raise

    def test_mark_completed_not_in_progress(self):
        """Marking completed a header not in progress should work."""
        tracker = HeaderProcessingTracker()
        # Directly mark completed without claiming
        tracker.mark_completed("/path/header.h", "hash")
        assert tracker.is_processed("/path/header.h", "hash")
