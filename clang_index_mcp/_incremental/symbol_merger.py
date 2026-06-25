"""Symbol merge helpers for incremental analysis.

These helpers take a batch of symbols produced by a worker process and merge them
into the analyzer's in-memory symbol store while applying the "definition wins"
deduplication rule.
"""

from typing import TYPE_CHECKING, Any, List

if TYPE_CHECKING:
    from .._contexts.incremental_context import IncrementalContext


def remove_symbol_from_index(ctx: "IncrementalContext", symbol: Any) -> None:
    """Remove a symbol from the appropriate index (class or function)."""
    ctx.symbol_store.remove_symbol_from_indexes(symbol)


def handle_definition_wins(ctx: "IncrementalContext", symbol: Any, existing: Any) -> bool:
    """
    Apply 'definition wins' rule for duplicate symbols.

    Returns True if the incoming symbol should be skipped (existing kept),
    False if the existing symbol should be replaced.
    """
    if symbol.is_definition and not existing.is_definition:
        remove_symbol_from_index(ctx, existing)
        return False
    return True


def add_symbol_to_indices(ctx: "IncrementalContext", symbol: Any) -> None:
    """Add a symbol to the analyzer's indices."""
    ctx.symbol_store.add_symbol_to_indexes(symbol)


def merge_symbols(ctx: "IncrementalContext", symbols: List[Any]) -> None:
    """Merge symbols from a worker process into the main analyzer index."""
    store = ctx.symbol_store
    with ctx.concurrency.index_lock:
        for symbol in symbols:
            skip_symbol = False
            if symbol.usr and store.contains_usr(symbol.usr):
                existing = store.get_symbol_by_usr(symbol.usr)
                assert existing is not None
                skip_symbol = handle_definition_wins(ctx, symbol, existing)

            if not skip_symbol:
                add_symbol_to_indices(ctx, symbol)
