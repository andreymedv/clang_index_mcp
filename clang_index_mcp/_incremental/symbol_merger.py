"""Symbol merge helpers for incremental analysis.

These helpers take a batch of symbols produced by a worker process and merge them
into the analyzer's in-memory symbol store while applying the "definition wins"
deduplication rule.
"""

from typing import TYPE_CHECKING, Any, List

if TYPE_CHECKING:
    from ..cpp_analyzer import CppAnalyzer


def remove_symbol_from_index(analyzer: "CppAnalyzer", symbol: Any) -> None:
    """Remove a symbol from the appropriate index (class or function)."""
    symbol_store = analyzer.context.symbol_store
    assert symbol_store is not None
    symbol_store.remove_symbol_from_indexes(symbol)


def handle_definition_wins(analyzer: "CppAnalyzer", symbol: Any, existing: Any) -> bool:
    """
    Apply 'definition wins' rule for duplicate symbols.

    Returns True if the incoming symbol should be skipped (existing kept),
    False if the existing symbol should be replaced.
    """
    if symbol.is_definition and not existing.is_definition:
        remove_symbol_from_index(analyzer, existing)
        return False
    return True


def add_symbol_to_indices(analyzer: "CppAnalyzer", symbol: Any) -> None:
    """Add a symbol to the analyzer's indices."""
    symbol_store = analyzer.context.symbol_store
    assert symbol_store is not None
    symbol_store.add_symbol_to_indexes(symbol)


def merge_symbols(analyzer: "CppAnalyzer", symbols: List[Any]) -> None:
    """Merge symbols from a worker process into the main analyzer index."""
    store = analyzer.context.symbol_store
    assert store is not None
    with analyzer.context.concurrency.index_lock:
        for symbol in symbols:
            skip_symbol = False
            if symbol.usr and store.contains_usr(symbol.usr):
                existing = store.get_symbol_by_usr(symbol.usr)
                assert existing is not None
                skip_symbol = handle_definition_wins(analyzer, symbol, existing)

            if not skip_symbol:
                add_symbol_to_indices(analyzer, symbol)
