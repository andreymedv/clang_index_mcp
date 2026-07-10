"""Persistence port for type aliases produced during indexing."""

from typing import List, Protocol

from .parser import TypeAliasRecord


class AliasPersistence(Protocol):
    """Port for persisting type aliases during bulk symbol writes.

    Implementations are provided by the persistence/infrastructure layer;
    the symbol index layer depends only on this protocol.
    """

    def save_aliases(self, aliases: List[TypeAliasRecord]) -> int:
        """Persist aliases and return the number saved."""
        ...
