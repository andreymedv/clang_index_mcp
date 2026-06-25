"""Progress reporting data structures for the indexing layer."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class IndexingProgress:
    """Real-time indexing progress information."""

    total_files: int
    indexed_files: int
    failed_files: int
    cache_hits: int
    current_file: Optional[str]
    start_time: datetime
    estimated_completion: Optional[datetime]

    @property
    def completion_percentage(self) -> float:
        """Calculate completion percentage."""
        if self.total_files == 0:
            return 0.0
        return self.indexed_files / self.total_files * 100.0

    @property
    def is_complete(self) -> bool:
        """Check if indexing is complete."""
        return self.indexed_files + self.failed_files >= self.total_files

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
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
