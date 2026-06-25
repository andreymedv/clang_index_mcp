"""Read-only symbol resolution helpers for SymbolIndexStore.

Isolates lookup/accessor methods so SymbolIndexStore can focus on index
management.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .._core import diagnostics
from .._symbols.model import build_location_objects, omit_empty

if TYPE_CHECKING:
    from .._symbols.model import SymbolInfo
    from .symbol_index_store import SymbolIndexStore


def contains_usr(store: "SymbolIndexStore", usr: str) -> bool:
    """Return True if the given USR is present in the in-memory index."""
    return usr in store.usr_index


def get_file_hash(store: "SymbolIndexStore", file_path: str) -> Optional[str]:
    """Return the stored hash for a file, or None if not tracked."""
    return store.file_hashes.get(file_path)


def has_file_hash(store: "SymbolIndexStore", file_path: str) -> bool:
    """Return True if a file hash is tracked."""
    return file_path in store.file_hashes


def get_classes_by_name(store: "SymbolIndexStore", name: str) -> List["SymbolInfo"]:
    """Return all class symbols with the given simple name."""
    return store.class_index.get(name, [])


def get_functions_by_name(store: "SymbolIndexStore", name: str) -> List["SymbolInfo"]:
    """Return all function symbols with the given simple name."""
    return store.function_index.get(name, [])


def get_symbols_in_file(store: "SymbolIndexStore", file_path: str) -> List["SymbolInfo"]:
    """Return all symbols in a given file."""
    return store.file_index.get(file_path, [])


def has_class_name(store: "SymbolIndexStore", name: str) -> bool:
    """Return True if the class index contains the given name."""
    return name in store.class_index


def has_function_name(store: "SymbolIndexStore", name: str) -> bool:
    """Return True if the function index contains the given name."""
    return name in store.function_index


def iter_class_items(store: "SymbolIndexStore"):
    """Iterate over (name, symbols) pairs in the class index."""
    return store.class_index.items()


def iter_function_items(store: "SymbolIndexStore"):
    """Iterate over (name, symbols) pairs in the function index."""
    return store.function_index.items()


def iter_file_items(store: "SymbolIndexStore"):
    """Iterate over (file_path, symbols) pairs in the file index."""
    return store.file_index.items()


def class_name_count(store: "SymbolIndexStore") -> int:
    """Return the number of unique class names."""
    return len(store.class_index)


def function_name_count(store: "SymbolIndexStore") -> int:
    """Return the number of unique function names."""
    return len(store.function_index)


def file_index_count(store: "SymbolIndexStore") -> int:
    """Return the number of indexed files in the file index."""
    return len(store.file_index)


def total_class_symbols(store: "SymbolIndexStore") -> int:
    """Return total number of class symbols (including duplicates by name)."""
    return sum(len(v) for v in store.class_index.values())


def total_function_symbols(store: "SymbolIndexStore") -> int:
    """Return total number of function symbols (including duplicates by name)."""
    return sum(len(v) for v in store.function_index.values())


def get_symbol_by_usr(store: "SymbolIndexStore", usr: str) -> Optional["SymbolInfo"]:
    """
    Resolve a USR to a SymbolInfo.

    First checks the in-memory USR index, then falls back to the SQLite backend
    for symbols that are not currently loaded.
    """
    if usr in store.usr_index:
        return store.usr_index[usr]
    backend = getattr(store._cache_manager, "backend", None)
    if backend is not None and hasattr(backend, "load_symbol_by_usr"):
        try:
            info: Optional["SymbolInfo"] = backend.load_symbol_by_usr(usr)
            return info
        except Exception as e:
            diagnostics.warning(f"Failed to load symbol by USR {usr}: {e}")
    return None


def resolve_symbol_info(store: "SymbolIndexStore", usr: str) -> Optional[Dict[str, Any]]:
    """
    Return a rich symbol dict for a USR, using the backend fallback if needed.

    Returns None when the symbol cannot be found at all.
    """
    info = get_symbol_by_usr(store, usr)
    if info is None:
        return None

    is_project = info.is_project if usr in store.usr_index else False
    return omit_empty(
        {
            "qualified_name": info.qualified_name or info.name,
            "kind": info.kind,
            "signature": info.signature,
            "parent_class": info.parent_class or None,
            "is_project": is_project,
            **build_location_objects(info),
        }
    )
