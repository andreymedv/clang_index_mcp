"""Persistence port for include dependency tracking."""

from typing import Dict, List, Protocol, Set, Union


class DependencyRepository(Protocol):
    """Store and query include dependencies between source files and headers."""

    def update_dependencies(self, source_file: str, included_files: List[str]) -> int:
        """Replace stored dependencies for ``source_file`` with ``included_files``."""
        ...

    def find_dependents(self, header_path: str) -> Set[str]:
        """Return source files that directly include ``header_path``."""
        ...

    def find_transitive_dependents(self, header_path: str) -> Set[str]:
        """Return all files that transitively include ``header_path``."""
        ...

    def remove_file_dependencies(self, file_path: str) -> int:
        """Remove all dependency records involving ``file_path``."""
        ...

    def get_dependency_stats(self) -> Dict[str, Union[int, float]]:
        """Return aggregate statistics about the dependency graph."""
        ...

    def get_include_count(self, source_file: str) -> int:
        """Return the number of files included by ``source_file``."""
        ...

    def clear_all_dependencies(self) -> int:
        """Remove all dependency records."""
        ...
