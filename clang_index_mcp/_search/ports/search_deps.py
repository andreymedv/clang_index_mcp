"""Port defining the dependencies needed by search layer components.

This module defines the minimal interface that search functions require
from outer layers (compilation, persistence, symbols). This keeps the
search layer decoupled from concrete implementations.
"""

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SearchIndexStore(Protocol):
    """Minimal interface for symbol index access used by search."""

    def iter_class_items(self) -> Any:
        pass

    def iter_file_paths(self) -> Any:
        pass

    def get_classes_by_name(self, name: str) -> Any:
        pass

    def get_functions_by_name(self, name: str) -> Any:
        pass

    def iter_file_items(self) -> Any:
        pass

    def contains_usr(self, usr: str) -> bool:
        pass

    def get_symbol_by_usr(self, usr: str) -> Any:
        pass


@runtime_checkable
class SearchConcurrency(Protocol):
    """Minimal interface for concurrency primitives used by search."""

    @property
    def index_lock(self) -> Any:
        pass


@runtime_checkable
class SearchCacheManager(Protocol):
    """Minimal interface for cache access used by search type alias resolution."""

    def get_canonical_for_alias(self, type_name: str) -> Any:
        pass

    def get_type_alias_info(self, type_name: str) -> Any:
        pass

    def get_aliases_for_canonical(self, canonical_type: str) -> Any:
        pass

    def get_type_alias_details(self, alias_names: list) -> Any:
        pass


@runtime_checkable
class SearchCompilationEnv(Protocol):
    """Minimal interface for compilation environment used by search."""

    def is_project_file(self, file_path: str) -> bool:
        pass


@runtime_checkable
class SearchCallGraphService(Protocol):
    """Minimal interface for call graph service used by search."""

    @property
    def call_graph_analyzer(self) -> Any:
        pass


@runtime_checkable
class SearchDependencies(Protocol):
    """Combined protocol for all search-layer dependencies.

    Components in _search accept this protocol instead of the full
    ProjectContext, ensuring they depend only on the interfaces they need.
    """

    @property
    def symbol_store(self) -> SearchIndexStore:
        pass

    @property
    def concurrency(self) -> SearchConcurrency:
        pass

    @property
    def cache_manager(self) -> SearchCacheManager:
        pass

    @property
    def compilation_env(self) -> SearchCompilationEnv:
        pass

    @property
    def call_graph_service(self) -> SearchCallGraphService:
        pass

    @property
    def project_root(self) -> Path:
        pass
