"""
Unit tests for the SymbolIndexStore definition-wins dedup rule (2c57.2).

Both index-write paths must apply the same dedup outcomes:
- bulk_write_symbols (bulk indexing via SymbolExtractor)
- merge_symbol_into_indexes (incremental / worker-result merge)

Known intentional divergence: the bulk path additionally carries parent_class
over from a replaced declaration (see TestParentClassCarryOver).
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from clang_index_mcp._symbols.model import SymbolInfo
from clang_index_mcp._symbols.symbol_index_store import SymbolIndexStore


class _NullLock:
    """No-op LockProvider implementation."""

    def __enter__(self) -> bool:
        return True

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        return False


def _make_store() -> SymbolIndexStore:
    return SymbolIndexStore(
        lock_provider=_NullLock(),
        alias_persistence=MagicMock(),
        cache_manager=MagicMock(),
        call_graph_port=MagicMock(),
    )


def _sym(**overrides) -> SymbolInfo:
    defaults = {
        "name": "Widget",
        "kind": "class",
        "file": "a.h",
        "line": 1,
        "column": 1,
        "usr": "c:@S@Widget",
    }
    defaults.update(overrides)
    return SymbolInfo(**defaults)


def _apply_bulk(existing: SymbolInfo, new: SymbolInfo) -> SymbolIndexStore:
    store = _make_store()
    store.bulk_write_symbols([existing], [], [])
    store.bulk_write_symbols([new], [], [])
    return store


def _apply_merge(existing: SymbolInfo, new: SymbolInfo) -> SymbolIndexStore:
    store = _make_store()
    store.merge_symbol_into_indexes(existing)
    store.merge_symbol_into_indexes(new)
    return store


PATHS = {"bulk": _apply_bulk, "merge": _apply_merge}


def _winner(store: SymbolIndexStore, usr: str):
    """Identify the winning symbol by (file, line), or None if absent."""
    entry = store.usr_index.get(usr)
    return None if entry is None else (entry.file, entry.line)


# (scenario id, overrides for the first-inserted symbol, overrides for the
# second-inserted symbol, which one must survive: "existing" or "new")
SCENARIOS = [
    ("definition_replaces_declaration", {"is_definition": False}, {"is_definition": True}, "new"),
    ("declaration_never_replaces_definition", {"is_definition": True}, {"is_definition": False}, "existing"),
    ("declaration_never_replaces_declaration", {"is_definition": False}, {"is_definition": False}, "existing"),
    (
        "larger_span_definition_wins",
        {"is_definition": True, "start_line": 1, "end_line": 3},
        {"is_definition": True, "start_line": 50, "end_line": 80},
        "new",
    ),
    (
        "smaller_span_definition_keeps_existing",
        {"is_definition": True, "start_line": 1, "end_line": 80},
        {"is_definition": True, "start_line": 50, "end_line": 52},
        "existing",
    ),
    (
        "equal_definitions_keep_existing",
        {"is_definition": True, "start_line": 1, "end_line": 5},
        {"is_definition": True, "start_line": 50, "end_line": 54},
        "existing",
    ),
    (
        "base_classes_beat_larger_span",
        {"is_definition": True, "start_line": 1, "end_line": 100},
        {"is_definition": True, "base_classes": ["Base"], "start_line": 50, "end_line": 52},
        "new",
    ),
    (
        "definition_without_bases_keeps_existing_with_bases",
        {"is_definition": True, "base_classes": ["Base"]},
        {"is_definition": True, "start_line": 50, "end_line": 90},
        "existing",
    ),
]


class TestShouldReplacePredicate:
    """Unit tests for the shared _should_replace(existing, new) rule."""

    def test_definition_replaces_declaration(self):
        assert (
            SymbolIndexStore._should_replace(
                _sym(is_definition=False), _sym(is_definition=True)
            )
            is True
        )

    def test_declaration_replaces_nothing(self):
        assert (
            SymbolIndexStore._should_replace(
                _sym(is_definition=False), _sym(is_definition=False)
            )
            is False
        )
        assert (
            SymbolIndexStore._should_replace(
                _sym(is_definition=True), _sym(is_definition=False)
            )
            is False
        )

    def test_between_definitions_richer_wins(self):
        poor = _sym(is_definition=True, start_line=1, end_line=2)
        rich = _sym(is_definition=True, start_line=1, end_line=20)
        assert SymbolIndexStore._should_replace(poor, rich) is True
        assert SymbolIndexStore._should_replace(rich, poor) is False

    def test_equal_definitions_keep_existing(self):
        a = _sym(is_definition=True, start_line=1, end_line=5)
        b = _sym(is_definition=True, start_line=1, end_line=5)
        assert SymbolIndexStore._should_replace(a, b) is False


class TestDedupOutcomesAgreeAcrossPaths:
    """Bulk and incremental paths must pick the same winner for every conflict."""

    @pytest.mark.parametrize(
        "existing_kwargs,new_kwargs,expected",
        [pytest.param(e, n, w, id=rid) for rid, e, n, w in SCENARIOS],
    )
    def test_same_winner_on_both_paths(self, existing_kwargs, new_kwargs, expected):
        existing = _sym(file="a.h", line=1, **existing_kwargs)
        new = _sym(file="a.cpp", line=50, **new_kwargs)
        expected_winner = (
            (new.file, new.line) if expected == "new" else (existing.file, existing.line)
        )

        for path_name, apply in PATHS.items():
            store = apply(existing, new)
            assert _winner(store, new.usr) == expected_winner, (
                f"{path_name} path picked wrong winner "
                f"(expected {expected} at {expected_winner})"
            )
            # Replacement must not leave duplicate name-index entries behind
            assert len(store.class_index["Widget"]) == 1, path_name

    def test_new_usr_is_always_inserted(self):
        first = _sym(file="a.h", line=1, usr="c:@S@First", is_definition=True)
        second = _sym(file="a.cpp", line=50, usr="c:@S@Second", is_definition=False)

        for path_name, apply in PATHS.items():
            store = apply(first, second)
            assert _winner(store, first.usr) == ("a.h", 1), path_name
            assert _winner(store, second.usr) == ("a.cpp", 50), path_name

    def test_symbols_without_usr_never_deduplicate(self):
        first = _sym(file="a.h", line=1, usr="", is_definition=False)
        second = _sym(file="a.h", line=2, usr="", is_definition=True)

        for path_name, apply in PATHS.items():
            store = apply(first, second)
            assert len(store.class_index["Widget"]) == 2, path_name
            assert len(store.file_index["a.h"]) == 2, path_name

    def test_function_index_dedup_matches_class_index(self):
        existing = _sym(
            name="render", kind="function", usr="c:@F@render", is_definition=False
        )
        new = _sym(
            name="render",
            kind="function",
            usr="c:@F@render",
            file="a.cpp",
            line=50,
            is_definition=True,
        )

        for path_name, apply in PATHS.items():
            store = apply(existing, new)
            assert _winner(store, "c:@F@render") == ("a.cpp", 50), path_name
            assert len(store.function_index["render"]) == 1, path_name
            assert "Widget" not in store.class_index or not store.class_index["Widget"]


class TestFileIndexDedup:
    """Both paths must apply the same definition-wins rule inside file_index."""

    def test_same_file_definition_replaces_declaration_in_place(self):
        existing = _sym(file="a.h", line=1, is_definition=False)
        new = _sym(file="a.h", line=10, is_definition=True)

        for path_name, apply in PATHS.items():
            store = apply(existing, new)
            entries = [(s.file, s.line) for s in store.file_index["a.h"]]
            assert entries == [("a.h", 10)], path_name

    def test_same_file_losing_declaration_is_not_appended(self):
        existing = _sym(file="a.h", line=10, is_definition=True)
        new = _sym(file="a.h", line=1, is_definition=False)

        for path_name, apply in PATHS.items():
            store = apply(existing, new)
            entries = [(s.file, s.line) for s in store.file_index["a.h"]]
            assert entries == [("a.h", 10)], path_name

    def test_cross_file_replacement_keeps_both_file_entries(self):
        # Out-of-line definition replaces a header declaration: each file keeps
        # its own location entry while the USR index points at the definition.
        existing = _sym(file="a.h", line=1, is_definition=False)
        new = _sym(file="a.cpp", line=50, is_definition=True)

        for path_name, apply in PATHS.items():
            store = apply(existing, new)
            assert [(s.file, s.line) for s in store.file_index["a.h"]] == [("a.h", 1)], path_name
            assert [(s.file, s.line) for s in store.file_index["a.cpp"]] == [("a.cpp", 50)], path_name
            assert _winner(store, new.usr) == ("a.cpp", 50), path_name

    def test_symbol_without_file_is_not_added_to_file_index(self):
        symbol = _sym(file="", line=1, is_definition=True)

        for path_name, apply in PATHS.items():
            store = apply(symbol, _sym(file="a.cpp", line=50, usr="c:@S@Other"))
            assert "" not in store.file_index, path_name


class TestParentClassCarryOver:
    """Bulk path metadata behavior when a definition replaces a declaration."""

    def test_bulk_definition_inherits_parent_class_from_declaration(self):
        store = _make_store()
        decl = _sym(
            name="bar",
            kind="method",
            file="foo.h",
            line=3,
            usr="c:@S@Foo@F@bar#",
            is_definition=False,
            parent_class="Foo",
        )
        defn = _sym(
            name="bar",
            kind="method",
            file="foo.cpp",
            line=20,
            usr="c:@S@Foo@F@bar#",
            is_definition=True,
            parent_class="",
        )

        store.bulk_write_symbols([decl], [], [])
        store.bulk_write_symbols([defn], [], [])

        winner = store.usr_index["c:@S@Foo@F@bar#"]
        assert (winner.file, winner.line) == ("foo.cpp", 20)
        assert winner.parent_class == "Foo"


class TestBulkWriteCount:
    """bulk_write_symbols count semantics around dedup."""

    def test_replacement_counts_as_added(self):
        store = _make_store()
        decl = _sym(file="a.h", line=1, is_definition=False)
        defn = _sym(file="a.cpp", line=50, is_definition=True)
        assert store.bulk_write_symbols([decl, defn], [], []) == 2

    def test_skipped_symbol_is_not_counted(self):
        store = _make_store()
        defn = _sym(file="a.h", line=1, is_definition=True)
        decl = _sym(file="a.cpp", line=50, is_definition=False)
        assert store.bulk_write_symbols([defn], [], []) == 1
        assert store.bulk_write_symbols([decl], [], []) == 0

    def test_add_symbol_to_indexes_matches_merge_path(self):
        existing = _sym(file="a.h", line=1, is_definition=False)
        new = _sym(file="a.cpp", line=50, is_definition=True)

        store = _make_store()
        store.add_symbol_to_indexes(existing)
        store.add_symbol_to_indexes(new)

        assert _winner(store, new.usr) == ("a.cpp", 50)
        assert len(store.class_index["Widget"]) == 1
