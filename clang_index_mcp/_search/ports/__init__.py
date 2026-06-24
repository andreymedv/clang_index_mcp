"""Ports (interfaces) for the search layer."""

from .dependency_repository import DependencyRepository
from .include_extractor import IncludeExtractor

__all__ = ["DependencyRepository", "IncludeExtractor"]
