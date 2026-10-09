"""Read-only query/search context exposed to the MCP layer."""

from dataclasses import dataclass

from .query_engine import QueryEngine


@dataclass
class QueryContext:
    """Search/query surface for MCP tool handlers."""

    query_engine: QueryEngine | None = None
