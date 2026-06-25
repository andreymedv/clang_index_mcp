"""Persistence and cache context."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from .cache_manager import CacheManager
from .cache_orchestrator import CacheOrchestrator

if TYPE_CHECKING:
    from .._indexing.refresh_pipeline import RefreshPipeline


@dataclass
class PersistenceContext:
    """SQLite-backed cache, file-cache orchestration, and refresh integration."""

    cache_manager: CacheManager
    cache_orchestrator: Optional[CacheOrchestrator] = None
    refresh_pipeline: Optional["RefreshPipeline"] = None
