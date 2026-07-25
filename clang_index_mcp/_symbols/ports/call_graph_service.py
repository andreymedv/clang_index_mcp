"""Call graph service port for the symbols/domain layer."""

from typing import Any, Protocol


class CallGraphServiceProtocol(Protocol):
    """Minimal interface the symbols layer needs from the call graph service.

    Implemented by ``_search.call_graph_service.CallGraphService`` and wired
    by the composition root. Defined as a port in the symbols layer so the
    dependency direction stays ``_search`` -> ``_symbols``; attributes are
    typed as ``Any`` to avoid referencing search-layer types from here.
    """

    call_graph_analyzer: Any
    dependency_graph: Any
