"""
Symbol index storage and management — extracted from CppAnalyzer.

Handles symbol indexes (class, function, file, USR), file hashes,
and index maintenance operations.
"""

import dataclasses
import re
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from . import diagnostics
from .symbol_info import (
    CLASS_KINDS,
    SymbolInfo,
    build_location_objects,
    is_richer_definition,
    omit_empty,
)

if TYPE_CHECKING:
    from .project_context import ProjectContext


class SymbolIndexStore:
    """
    Manages symbol indexes and provides operations for adding, removing,
    and maintaining symbol data across multiple lookup structures.
    """

    def __init__(self, context: "ProjectContext"):
        """
        Initialize SymbolIndexStore.

        Args:
            context: Shared project context for access to call graph service
                     and concurrency utilities.
        """
        self.context = context
        assert context.call_graph_service is not None
        self.call_graph_service = context.call_graph_service
        self.call_graph_analyzer = self.call_graph_service.call_graph_analyzer
        assert context.concurrency is not None
        self._get_lock = context.concurrency.get_lock

        # Indexes for fast lookup
        self.class_index: Dict[str, List[SymbolInfo]] = defaultdict(list)
        self.function_index: Dict[str, List[SymbolInfo]] = defaultdict(list)
        self.file_index: Dict[str, List[SymbolInfo]] = defaultdict(list)
        self.usr_index: Dict[str, SymbolInfo] = {}

        # Track indexed files and hashes
        self.file_hashes: Dict[str, str] = {}
        self._indexed_file_count = 0

    def _remove_symbol_from_indexes(self, symbol: SymbolInfo) -> None:
        """Remove a single symbol from class/function/USR indexes and call graph."""
        # 1. Global name-based indexes
        target_index = (
            self.class_index
            if symbol.kind in ("class", "struct", "class_template", "partial_specialization")
            else self.function_index
        )

        if symbol.name in target_index:
            # Use USR for identity check if available, otherwise fallback to object equality
            if symbol.usr:
                target_index[symbol.name] = [
                    i for i in target_index[symbol.name] if i.usr != symbol.usr
                ]
            else:
                target_index[symbol.name] = [i for i in target_index[symbol.name] if i != symbol]

            if not target_index[symbol.name]:
                del target_index[symbol.name]

        # 2. USR and Call Graph
        if symbol.usr:
            if symbol.usr in self.usr_index:
                # Only delete if it's actually the same symbol (to avoid accidental deletion of replacements)
                existing = self.usr_index[symbol.usr]
                if existing == symbol or existing.usr == symbol.usr:
                    del self.usr_index[symbol.usr]
            self.call_graph_analyzer.remove_symbol(symbol.usr)

    def _handle_symbol_definition_wins(
        self, info: SymbolInfo, existing_symbol: SymbolInfo
    ) -> Optional[SymbolInfo]:
        """Apply definition-wins logic when a symbol already exists in the USR index.

        Returns the info object to use, or None if the symbol should be skipped.
        """
        # Definition-wins: If new symbol is a definition and existing is not, replace
        if info.is_definition and not existing_symbol.is_definition:
            # Preserve parent_class from declaration if definition lost it
            if not info.parent_class and existing_symbol.parent_class:
                info = dataclasses.replace(info, parent_class=existing_symbol.parent_class)

            diagnostics.debug(
                f"Definition-wins: Replacing declaration of {info.name} with definition "
                f"(from {existing_symbol.file}:{existing_symbol.line} to {info.file}:{info.line})"
            )

            # Remove from class/function/usr indexes but KEEP in file_index
            self._remove_symbol_from_indexes(existing_symbol)
            return info

        elif info.is_definition and existing_symbol.is_definition:
            # Both are definitions. Pick the richer one.
            if is_richer_definition(info, existing_symbol):
                diagnostics.debug(
                    f"Richer-definition: Replacing {info.name} "
                    f"(from {existing_symbol.file}:{existing_symbol.line} "
                    f"to {info.file}:{info.line})"
                )
                self._remove_symbol_from_indexes(existing_symbol)
                return info
            else:
                return None  # Keep existing (it's richer or equal)
        else:
            # Keep existing symbol (existing is definition, new is declaration)
            return None

    def _add_symbol_to_file_index(self, info: SymbolInfo) -> None:
        """Add symbol to file_index with deduplication check."""
        if not info.file:
            return

        if info.file not in self.file_index:
            self.file_index[info.file] = []

        already_in_file_index = False
        if info.usr:
            for idx_pos, existing in enumerate(self.file_index[info.file]):
                if existing.usr == info.usr:
                    if (info.is_definition and not existing.is_definition) or (
                        info.is_definition
                        and existing.is_definition
                        and is_richer_definition(info, existing)
                    ):
                        self.file_index[info.file][idx_pos] = info
                    already_in_file_index = True
                    break

        if not already_in_file_index:
            self.file_index[info.file].append(info)

    def _apply_cached_symbols(
        self, file_path: str, cached_symbols: List[SymbolInfo], current_hash: str
    ) -> None:
        """Apply cached symbols to indexes and update file hash."""
        # Build updates for class_index and function_index
        class_updates = defaultdict(list)
        function_updates = defaultdict(list)
        usr_updates = {}

        for symbol in cached_symbols:
            if symbol.kind in ("class", "struct"):
                class_updates[symbol.name].append(symbol)
            else:
                function_updates[symbol.name].append(symbol)

            if symbol.usr:
                usr_updates[symbol.usr] = symbol

        # Apply all updates with a single lock acquisition
        with self.context.concurrency.get_lock():
            # Clear old entries for this file
            self._clear_file_index_entries(file_path)

            # Add cached symbols
            self.file_index[file_path] = cached_symbols

            # Apply class/function/USR updates
            for name, symbols in class_updates.items():
                self.class_index[name].extend(symbols)
            for name, symbols in function_updates.items():
                self.function_index[name].extend(symbols)
            self.usr_index.update(usr_updates)

            self.file_hashes[file_path] = current_hash

    def _clear_file_index_entries(self, file_path: str) -> None:
        """Clear existing index entries for a file (atomicity should be handled by caller)."""
        self._remove_file_from_indexes(file_path)

    def _add_to_file_index(self, symbol: SymbolInfo):
        """Add symbol to file index with deduplication."""
        if symbol.file not in self.file_index:
            self.file_index[symbol.file] = []
            self.file_index[symbol.file].append(symbol)
            return

        if not symbol.usr:
            self.file_index[symbol.file].append(symbol)
            return

        for idx_pos, existing in enumerate(self.file_index[symbol.file]):
            if existing.usr == symbol.usr:
                if (symbol.is_definition and not existing.is_definition) or (
                    symbol.is_definition
                    and existing.is_definition
                    and is_richer_definition(symbol, existing)
                ):
                    self.file_index[symbol.file][idx_pos] = symbol
                return

        self.file_index[symbol.file].append(symbol)

    def _merge_symbol_into_indexes(self, symbol: SymbolInfo):
        """Merge a single symbol into the main process indexes with deduplication."""
        if symbol.usr and symbol.usr in self.usr_index:
            existing = self.usr_index[symbol.usr]
            if symbol.is_definition and not existing.is_definition:
                self._remove_symbol_from_indexes(existing)
            elif symbol.is_definition and existing.is_definition:
                if is_richer_definition(symbol, existing):
                    self._remove_symbol_from_indexes(existing)
                else:
                    return
            else:
                return

        if symbol.kind in CLASS_KINDS:
            self.class_index[symbol.name].append(symbol)
        else:
            self.function_index[symbol.name].append(symbol)

        if symbol.usr:
            self.usr_index[symbol.usr] = symbol

        if symbol.file:
            self._add_to_file_index(symbol)

    def _populate_indexes_from_cache(self, cache_data: Dict[str, Any]) -> None:
        """Populate main and file indexes from cache data."""
        # Load indexes - Memory optimization: SymbolInfo objects come directly
        # from SQLite backend (no dict conversion needed, saves ~500 MB peak)
        self.class_index.clear()
        for name, infos in cache_data.get("class_index", {}).items():
            self.class_index[name] = infos

        self.function_index.clear()
        for name, infos in cache_data.get("function_index", {}).items():
            self.function_index[name] = infos

        # Rebuild file index mapping from loaded symbols
        self.file_index.clear()
        for infos in self.class_index.values():
            for symbol in infos:
                if symbol.file:
                    self.file_index[symbol.file].append(symbol)
        for infos in self.function_index.values():
            for symbol in infos:
                if symbol.file:
                    self.file_index[symbol.file].append(symbol)

        self.file_hashes = cache_data.get("file_hashes", {})
        self._indexed_file_count = cache_data.get("indexed_file_count", 0)

    def _rebuild_auxiliary_structures(self) -> None:
        """Rebuild USR index and call graph from loaded symbols."""
        self.usr_index.clear()
        self.call_graph_analyzer.clear()

        # Rebuild from all loaded symbols
        all_symbols = []
        for class_list in self.class_index.values():
            for symbol in class_list:
                if symbol.usr:
                    self.usr_index[symbol.usr] = symbol
                    all_symbols.append(symbol)

        for func_list in self.function_index.values():
            for symbol in func_list:
                if symbol.usr:
                    self.usr_index[symbol.usr] = symbol
                    all_symbols.append(symbol)

        # Rebuild call graph from all symbols
        self.call_graph_analyzer.rebuild_from_symbols(all_symbols)

    def _bulk_write_symbols(self) -> int:
        """
        Bulk write collected symbols to shared indexes with a single lock acquisition.

        Takes all symbols collected in thread-local buffers during parsing and adds
        them to the shared indexes in one atomic operation, reducing lock contention.

        Returns:
            Number of symbols actually added (after deduplication)
        """
        symbols_buffer, calls_buffer, aliases_buffer = (
            self.context.concurrency.get_thread_local_buffers()
        )

        if not symbols_buffer and not calls_buffer and not aliases_buffer:
            return 0

        added_count = 0

        # Single lock acquisition for all symbols (conditional based on execution mode)
        with self._get_lock():
            # Add all collected symbols
            for info in symbols_buffer:
                # USR-based deduplication with definition-wins logic
                if info.usr and info.usr in self.usr_index:
                    existing_symbol = self.usr_index[info.usr]
                    resolved_info = self._handle_symbol_definition_wins(info, existing_symbol)
                    if resolved_info is None:
                        continue
                    info = resolved_info

                # New symbol or replacement - add to all indexes
                if info.kind in CLASS_KINDS:
                    self.class_index[info.name].append(info)
                else:
                    self.function_index[info.name].append(info)

                if info.usr:
                    self.usr_index[info.usr] = info

                self._add_symbol_to_file_index(info)
                added_count += 1

            # Add all collected call relationships
            self.call_graph_service._process_call_buffer(calls_buffer)

            # Add all collected type aliases
            if aliases_buffer:
                diagnostics.debug(f"Processing {len(aliases_buffer)} type aliases from buffer")
                saved_count = self.context.cache_manager.save_type_aliases_batch(aliases_buffer)
                diagnostics.debug(f"Saved {saved_count} type aliases to cache")

        # Clear buffers for next use
        symbols_buffer.clear()
        calls_buffer.clear()
        aliases_buffer.clear()

        return added_count

    def remove_file(self, file_path: str) -> None:
        """Remove all symbols and metadata for a deleted file from the in-memory indexes."""
        with self.context.concurrency.index_lock:
            self._remove_file_from_indexes(file_path)
            self.file_hashes.pop(file_path, None)

    def contains_usr(self, usr: str) -> bool:
        """Return True if the given USR is present in the in-memory index."""
        return usr in self.usr_index

    # ------------------------------------------------------------------
    # file_hashes accessors
    # ------------------------------------------------------------------

    def get_file_hash(self, file_path: str) -> Optional[str]:
        """Return the stored hash for a file, or None if not tracked."""
        return self.file_hashes.get(file_path)

    def has_file_hash(self, file_path: str) -> bool:
        """Return True if a file hash is tracked."""
        return file_path in self.file_hashes

    def set_file_hash(self, file_path: str, file_hash: str) -> None:
        """Store or update the hash for a file."""
        self.file_hashes[file_path] = file_hash

    def pop_file_hash(self, file_path: str) -> None:
        """Remove a file hash entry if it exists."""
        self.file_hashes.pop(file_path, None)

    def iter_file_paths(self):
        """Return an iterable of all tracked file paths."""
        return self.file_hashes.keys()

    # ------------------------------------------------------------------
    # indexed_file_count property
    # ------------------------------------------------------------------

    @property
    def indexed_file_count(self) -> int:
        """Number of files that have been indexed."""
        return self._indexed_file_count

    @indexed_file_count.setter
    def indexed_file_count(self, value: int) -> None:
        self._indexed_file_count = value

    # ------------------------------------------------------------------
    # Bulk mutation methods
    # ------------------------------------------------------------------

    def clear_all_indexes(self) -> List[SymbolInfo]:
        """Clear all in-memory indexes and file hashes.

        Returns the list of symbols that were in file_index (used by workers
        to persist their results before clearing).
        """
        symbols = list(self.file_index.values())
        flat: List[SymbolInfo] = []
        for batch in symbols:
            flat.extend(batch)
        self.file_index.clear()
        self.class_index.clear()
        self.function_index.clear()
        self.usr_index.clear()
        self.file_hashes.clear()
        return flat

    def add_symbol_to_indexes(self, symbol: SymbolInfo) -> None:
        """Add a symbol to all in-memory indexes (class/function/usr/file).

        Delegates to the internal merge logic with deduplication.
        Used by incremental analyzer for individual symbol additions.
        """
        with self.context.concurrency.index_lock:
            self._merge_symbol_into_indexes(symbol)

    def remove_symbol_from_indexes(self, symbol: SymbolInfo) -> None:
        """Remove a symbol from all in-memory indexes.

        Used by incremental analyzer for individual symbol removals.
        """
        with self.context.concurrency.index_lock:
            self._remove_symbol_from_indexes(symbol)

    # ------------------------------------------------------------------
    # Read accessors
    # ------------------------------------------------------------------

    def get_classes_by_name(self, name: str) -> List[SymbolInfo]:
        """Return all class symbols with the given simple name."""
        return self.class_index.get(name, [])

    def get_functions_by_name(self, name: str) -> List[SymbolInfo]:
        """Return all function symbols with the given simple name."""
        return self.function_index.get(name, [])

    def get_symbols_in_file(self, file_path: str) -> List[SymbolInfo]:
        """Return all symbols in a given file."""
        return self.file_index.get(file_path, [])

    def has_class_name(self, name: str) -> bool:
        """Return True if the class index contains the given name."""
        return name in self.class_index

    def has_function_name(self, name: str) -> bool:
        """Return True if the function index contains the given name."""
        return name in self.function_index

    def iter_class_items(self):
        """Iterate over (name, symbols) pairs in the class index."""
        return self.class_index.items()

    def iter_function_items(self):
        """Iterate over (name, symbols) pairs in the function index."""
        return self.function_index.items()

    def iter_file_items(self):
        """Iterate over (file_path, symbols) pairs in the file index."""
        return self.file_index.items()

    def class_name_count(self) -> int:
        """Return the number of unique class names."""
        return len(self.class_index)

    def function_name_count(self) -> int:
        """Return the number of unique function names."""
        return len(self.function_index)

    def file_index_count(self) -> int:
        """Return the number of indexed files in the file index."""
        return len(self.file_index)

    def total_class_symbols(self) -> int:
        """Return total number of class symbols (including duplicates by name)."""
        return sum(len(v) for v in self.class_index.values())

    def total_function_symbols(self) -> int:
        """Return total number of function symbols (including duplicates by name)."""
        return sum(len(v) for v in self.function_index.values())

    def get_symbol_by_usr(self, usr: str) -> Optional[SymbolInfo]:
        """
        Resolve a USR to a SymbolInfo.

        First checks the in-memory USR index, then falls back to the SQLite backend
        for symbols that are not currently loaded.
        """
        if usr in self.usr_index:
            return self.usr_index[usr]
        backend = getattr(self.context.cache_manager, "backend", None)
        if backend is not None and hasattr(backend, "load_symbol_by_usr"):
            try:
                info: Optional[SymbolInfo] = backend.load_symbol_by_usr(usr)
                return info
            except Exception as e:
                diagnostics.warning(f"Failed to load symbol by USR {usr}: {e}")
        return None

    def resolve_symbol_info(self, usr: str) -> Optional[Dict[str, Any]]:
        """
        Return a rich symbol dict for a USR, using the backend fallback if needed.

        Returns None when the symbol cannot be found at all.
        """
        info = self.get_symbol_by_usr(usr)
        if info is None:
            return None

        is_project = info.is_project if usr in self.usr_index else False
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

    def _remove_file_from_indexes(self, file_path: str):
        """Remove all symbols from a deleted file from all indexes"""
        # Get all symbols that were in this file
        symbols_to_remove = self.file_index.get(file_path, []).copy()
        if symbols_to_remove:
            diagnostics.debug(f"Removing {len(symbols_to_remove)} symbols for file {file_path}")

        for symbol in symbols_to_remove:
            self._remove_symbol_from_indexes(symbol)

        # Finally remove from file_index
        if file_path in self.file_index:
            del self.file_index[file_path]
            diagnostics.debug(f"Removed file {file_path} from file_index")

    @staticmethod
    def extract_template_base_name_from_usr(usr: str) -> Optional[str]:
        """
        Extract the base template name from a USR.

        USR Format Examples:
        - Generic Template:        c:@ST>1#T@Container
        - Explicit Specialization: c:@S@Container>#I
        - Partial Specialization:  c:@SP>1#T@Container>#*t0.0

        Returns:
            Base template name (e.g., "Container") or None if not a template-related USR
        """
        if not usr:
            return None

        match = re.search(r"c:@ST>[^@]*@(\w+)", usr)
        if match:
            return match.group(1)

        match = re.search(r"c:@S@(\w+)", usr)
        if match:
            return match.group(1)

        match = re.search(r"c:@SP>[^@]*@(\w+)", usr)
        if match:
            return match.group(1)

        return None

    def _add_class_template_symbols(self, base_name: str, results: List[SymbolInfo]) -> None:
        """Add class template and specialization symbols to results."""
        if base_name not in self.class_index:
            return
        for symbol in self.class_index[base_name]:
            if symbol.kind in ("class_template", "partial_specialization"):
                results.append(symbol)
            elif symbol.kind in ("class", "struct"):
                if symbol.usr and ">#" in symbol.usr:
                    results.append(symbol)

    def _add_function_template_symbols(self, base_name: str, results: List[SymbolInfo]) -> None:
        """Add function template and specialization symbols to results."""
        if base_name not in self.function_index:
            return
        for symbol in self.function_index[base_name]:
            if symbol.kind == "function_template":
                results.append(symbol)
            elif symbol.kind in ("function", "method"):
                if symbol.is_template_specialization or (
                    symbol.usr and ("<#" in symbol.usr or ">#" in symbol.usr)
                ):
                    results.append(symbol)

    def find_template_specializations(self, base_name: str) -> List[SymbolInfo]:
        """
        Find all specializations of a template by base name.

        Searches for:
        1. Generic template definition (kind=class_template, function_template)
        2. Explicit full specializations (kind=class, function with template args in USR)
        3. Partial specializations (kind=partial_specialization)
        """
        results: List[SymbolInfo] = []

        with self.context.concurrency.index_lock:
            self._add_class_template_symbols(base_name, results)
            self._add_function_template_symbols(base_name, results)

        return results
