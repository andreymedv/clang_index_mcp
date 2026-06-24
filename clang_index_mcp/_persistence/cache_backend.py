"""Backward-compatible re-export of the cache backend port.

The canonical location is ``clang_index_mcp._indexing.ports.cache_backend``.
This module is kept only for compatibility during the migration and will be
removed in a follow-up.
"""

from .._indexing.ports.cache_backend import CacheBackend

__all__ = ["CacheBackend"]
