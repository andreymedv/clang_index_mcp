"""Dependency Graph Builder for Incremental Analysis.

This module provides functionality to track include dependencies between
source files and headers, enabling cascade re-analysis when headers change.

Key Features:
- Extract include directives from translation units
- Build forward dependency graph (file → what it includes)
- Build reverse dependency graph (header → files that include it)
- Compute transitive closure for cascade analysis
- Efficient graph queries using recursive CTEs

The builder now depends on ports rather than concrete SQLite/libclang types.
"""

from typing import TYPE_CHECKING, Dict, List, Set, Union

from clang.cindex import TranslationUnit

if TYPE_CHECKING:
    from .._search.ports.dependency_repository import DependencyRepository
    from .._search.ports.include_extractor import IncludeExtractor


class DependencyGraphBuilder:
    """
    Builds and maintains the include dependency graph.

    This class tracks which files include which headers, enabling
    incremental analysis by identifying files affected by header changes.

    The dependency graph is stored via a ``DependencyRepository`` port and
    include extraction is performed by an ``IncludeExtractor`` port.
    """

    def __init__(
        self,
        repository: "DependencyRepository",
        include_extractor: "IncludeExtractor",
    ):
        """
        Initialize dependency graph builder.

        Args:
            repository: Persistence port for dependency storage/queries.
            include_extractor: Port for extracting includes from a TU.
        """
        self._repository = repository
        self._include_extractor = include_extractor

    def extract_includes_from_tu(self, tu: TranslationUnit, source_file: str) -> List[str]:
        """Extract all includes from a translation unit."""
        return self._include_extractor.extract_includes(tu, source_file)

    def update_dependencies(self, source_file: str, included_files: List[str]) -> int:
        """Update dependency graph for a source file."""
        return self._repository.update_dependencies(source_file, included_files)

    def find_dependents(self, header_path: str) -> Set[str]:
        """Find all files that directly depend on a header."""
        return self._repository.find_dependents(header_path)

    def find_transitive_dependents(self, header_path: str) -> Set[str]:
        """Find all files that depend on a header transitively."""
        return self._repository.find_transitive_dependents(header_path)

    def remove_file_dependencies(self, file_path: str) -> int:
        """Remove all dependencies for a file."""
        return self._repository.remove_file_dependencies(file_path)

    def get_dependency_stats(self) -> Dict[str, Union[int, float]]:
        """Get statistics about the dependency graph."""
        return self._repository.get_dependency_stats()

    def get_include_count(self, source_file: str) -> int:
        """Get number of files included by a source file."""
        return self._repository.get_include_count(source_file)

    def clear_all_dependencies(self) -> int:
        """Clear all dependencies from the graph."""
        return self._repository.clear_all_dependencies()
