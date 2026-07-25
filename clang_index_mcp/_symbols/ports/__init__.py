"""Ports (interfaces) for the symbols/domain layer."""

from .alias_persistence import AliasPersistence
from .call_graph import CallGraphPort
from .call_graph_service import CallGraphServiceProtocol
from .lock_provider import LockProvider
from .parser import ParseResult, SymbolParser

__all__ = [
    "AliasPersistence",
    "CallGraphPort",
    "CallGraphServiceProtocol",
    "LockProvider",
    "ParseResult",
    "SymbolParser",
]
