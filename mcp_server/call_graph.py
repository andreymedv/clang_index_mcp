"""Call graph analysis for C++ code."""

import re
from typing import Dict, List, Set, Optional, Any, Tuple
from collections import defaultdict
from .symbol_info import SymbolInfo


class CallSite:
    """Represents a single call site with location information."""

    def __init__(
        self, caller_usr: str, callee_usr: str, file: str, line: int, column: Optional[int] = None
    ):
        self.caller_usr = caller_usr
        self.callee_usr = callee_usr
        self.file = file
        self.line = line
        self.column = column

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "caller_usr": self.caller_usr,
            "callee_usr": self.callee_usr,
            "file": self.file,
            "line": self.line,
            "column": self.column,
        }

    def __eq__(self, other):
        if not isinstance(other, CallSite):
            return False
        return (
            self.caller_usr == other.caller_usr
            and self.callee_usr == other.callee_usr
            and self.file == other.file
            and self.line == other.line
        )

    def __hash__(self):
        return hash((self.caller_usr, self.callee_usr, self.file, self.line))

    def __repr__(self):
        return f"CallSite({self.caller_usr} -> {self.callee_usr} at {self.file}:{self.line})"


class CallGraphAnalyzer:
    """Manages call graph analysis for C++ code with line-level precision."""

    def __init__(self, cache_backend=None):
        """
        Initialize CallGraphAnalyzer.

        Args:
            cache_backend: Optional SQLiteCacheBackend for lazy loading call sites.
                          If provided, call sites are loaded on-demand from SQLite
                          instead of being kept in memory (~150-200 MB savings).
        """
        self.call_graph: Dict[str, Set[str]] = defaultdict(
            set
        )  # Function USR -> Set of called USRs
        self.reverse_call_graph: Dict[str, Set[str]] = defaultdict(
            set
        )  # Function USR -> Set of caller USRs

        # Phase 3: Line-level call site tracking
        # Only stores call sites from CURRENT indexing session
        # Historical call sites are loaded on-demand from SQLite via cache_backend
        self.call_sites: Set[CallSite] = (
            set()
        )  # Current session call sites (using set to avoid duplicates)

        # Memory optimization: lazy load call sites from SQLite
        self.cache_backend = cache_backend

    def add_call(
        self,
        caller_usr: str,
        callee_usr: str,
        file: Optional[str] = None,
        line: Optional[int] = None,
        column: Optional[int] = None,
        store_call_site: bool = True,
    ):
        """
        Add a function call relationship with optional location information.

        Args:
            caller_usr: USR of calling function
            callee_usr: USR of called function
            file: Source file containing call (Phase 3)
            line: Line number of call (Phase 3)
            column: Column number of call (Phase 3, optional)
            store_call_site: If True, store CallSite in memory (default).
                           Set to False when main process saves directly to SQLite
                           to avoid memory accumulation (~1.9 GB for large projects).
        """
        if caller_usr and callee_usr:
            self.call_graph[caller_usr].add(callee_usr)
            self.reverse_call_graph[callee_usr].add(caller_usr)

            # Phase 3: Store call site with location if provided
            # Phase 4: Only store in memory if store_call_site=True
            # Main process should set store_call_site=False and save directly to SQLite
            if store_call_site and file and line:
                call_site = CallSite(caller_usr, callee_usr, file, line, column)
                self.call_sites.add(call_site)  # Using set.add() to automatically deduplicate

    def clear(self):
        """Clear all call graph data"""
        self.call_graph.clear()
        self.reverse_call_graph.clear()
        self.call_sites.clear()  # Phase 3

    def remove_symbol(self, usr: str):
        """Remove a symbol from the call graph completely"""
        if usr in self.call_graph:
            # Remove all calls made by this function
            called_functions = self.call_graph[usr].copy()
            for called_usr in called_functions:
                self.reverse_call_graph[called_usr].discard(usr)
                # Clean up empty sets
                if not self.reverse_call_graph[called_usr]:
                    del self.reverse_call_graph[called_usr]
            del self.call_graph[usr]

        if usr in self.reverse_call_graph:
            # Remove all calls to this function
            calling_functions = self.reverse_call_graph[usr].copy()
            for caller_usr in calling_functions:
                self.call_graph[caller_usr].discard(usr)
                # Clean up empty sets
                if not self.call_graph[caller_usr]:
                    del self.call_graph[caller_usr]
            del self.reverse_call_graph[usr]

    def rebuild_from_symbols(self, symbols: List[SymbolInfo]):
        """
        Rebuild call graph from symbol list.

        DEPRECATED (v9.0): This method is now a no-op.
        Call graph data is loaded lazily from SQLite via find_callers/find_callees.
        The calls/called_by fields were removed from SymbolInfo in v9.0.

        For backward compatibility, this method is kept but does nothing.
        """
        # v9.0: No-op - call graph is now loaded lazily from SQLite
        # The calls/called_by fields were removed from SymbolInfo
        pass

    def restore_call_sites(self, call_sites_data: List[Dict[str, Any]]):
        """
        Restore call sites from database-loaded dictionaries.

        Args:
            call_sites_data: List of dicts with keys: caller_usr, callee_usr, file, line, column
        """
        for cs_dict in call_sites_data:
            call_site = CallSite(
                caller_usr=cs_dict["caller_usr"],
                callee_usr=cs_dict["callee_usr"],
                file=cs_dict["file"],
                line=cs_dict["line"],
                column=cs_dict.get("column"),
            )
            self.call_sites.add(call_site)  # Using set.add() to automatically deduplicate

    def find_callers(self, function_usr: str) -> Set[str]:
        """
        Find all functions that call the specified function.

        Uses in-memory reverse_call_graph first (for current session),
        then falls back to SQLite for historical data (lazy loading).
        """
        # First check in-memory (current session or freshly indexed)
        result = self.reverse_call_graph.get(function_usr, set()).copy()

        # Then check SQLite if available (historical data / lazy loading)
        if self.cache_backend:
            try:
                db_results = self.cache_backend.get_call_sites_for_callee(function_usr)
                for cs_dict in db_results:
                    caller_usr = cs_dict.get("caller_usr")
                    if caller_usr:
                        result.add(caller_usr)
            except Exception:
                pass  # Silently ignore DB errors, use in-memory only

        return result

    def find_callees(self, function_usr: str) -> Set[str]:
        """
        Find all functions called by the specified function.

        Uses in-memory call_graph first (for current session),
        then falls back to SQLite for historical data (lazy loading).
        """
        # First check in-memory (current session or freshly indexed)
        result = self.call_graph.get(function_usr, set()).copy()

        # Then check SQLite if available (historical data / lazy loading)
        if self.cache_backend:
            try:
                db_results = self.cache_backend.get_call_sites_for_caller(function_usr)
                for cs_dict in db_results:
                    callee_usr = cs_dict.get("callee_usr")
                    if callee_usr:
                        result.add(callee_usr)
            except Exception:
                pass  # Silently ignore DB errors, use in-memory only

        return result

    def get_call_paths(self, from_usr: str, to_usr: str, max_depth: int = 10) -> List[List[str]]:
        """Find all call paths from one function to another"""
        if from_usr == to_usr:
            return [[from_usr]]

        if max_depth <= 0:
            return []

        paths = []

        # Get direct callees
        callees = self.find_callees(from_usr)

        for callee in callees:
            if callee == to_usr:
                # Direct call found
                paths.append([from_usr, to_usr])
            else:
                # Recursively search for paths
                sub_paths = self.get_call_paths(callee, to_usr, max_depth - 1)
                for sub_path in sub_paths:
                    paths.append([from_usr] + sub_path)

        return paths

    def get_call_statistics(self) -> Dict[str, Any]:
        """Get statistics about the call graph"""
        return {
            "total_functions_with_calls": len(self.call_graph),
            "total_functions_being_called": len(self.reverse_call_graph),
            "total_unique_calls": sum(len(calls) for calls in self.call_graph.values()),
            "most_called_functions": self._get_most_called_functions(10),
            "functions_with_most_calls": self._get_functions_with_most_calls(10),
        }

    def _get_most_called_functions(self, limit: int) -> List[tuple]:
        """Get the most frequently called functions"""
        call_counts = [(usr, len(callers)) for usr, callers in self.reverse_call_graph.items()]
        return sorted(call_counts, key=lambda x: x[1], reverse=True)[:limit]

    def _get_functions_with_most_calls(self, limit: int) -> List[tuple]:
        """Get functions that make the most calls"""
        call_counts = [(usr, len(callees)) for usr, callees in self.call_graph.items()]
        return sorted(call_counts, key=lambda x: x[1], reverse=True)[:limit]

    # Phase 3: Line-level call site methods

    def get_call_sites_for_caller(self, caller_usr: str) -> List[CallSite]:
        """
        Get all call sites from a specific caller function.

        Uses lazy loading: first checks in-memory call_sites (current session),
        then queries SQLite for historical call sites.

        Args:
            caller_usr: USR of the calling function

        Returns:
            List of CallSite objects for this caller
        """
        # First, get call sites from current session (in-memory)
        current_session = [cs for cs in self.call_sites if cs.caller_usr == caller_usr]

        # Then, get historical call sites from SQLite (lazy loading)
        if self.cache_backend:
            try:
                db_results = self.cache_backend.get_call_sites_for_caller(caller_usr)
                for cs_dict in db_results:
                    call_site = CallSite(
                        caller_usr=caller_usr,  # Use parameter, not from db result
                        callee_usr=cs_dict["callee_usr"],
                        file=cs_dict["file"],
                        line=cs_dict["line"],
                        column=cs_dict.get("column"),
                    )
                    # Avoid duplicates (current session may have same call sites)
                    if call_site not in current_session:
                        current_session.append(call_site)
            except Exception:
                pass  # SQLite errors shouldn't break the query

        return sorted(current_session, key=lambda cs: (cs.file, cs.line))

    def get_call_sites_for_callee(self, callee_usr: str) -> List[CallSite]:
        """
        Get all call sites to a specific callee function.

        Uses lazy loading: first checks in-memory call_sites (current session),
        then queries SQLite for historical call sites.

        Args:
            callee_usr: USR of the called function

        Returns:
            List of CallSite objects for this callee
        """
        # First, get call sites from current session (in-memory)
        current_session = [cs for cs in self.call_sites if cs.callee_usr == callee_usr]

        # Then, get historical call sites from SQLite (lazy loading)
        if self.cache_backend:
            try:
                db_results = self.cache_backend.get_call_sites_for_callee(callee_usr)
                for cs_dict in db_results:
                    call_site = CallSite(
                        caller_usr=cs_dict["caller_usr"],
                        callee_usr=callee_usr,  # Use parameter, not from db result
                        file=cs_dict["file"],
                        line=cs_dict["line"],
                        column=cs_dict.get("column"),
                    )
                    # Avoid duplicates (current session may have same call sites)
                    if call_site not in current_session:
                        current_session.append(call_site)
            except Exception:
                pass  # SQLite errors shouldn't break the query

        return sorted(current_session, key=lambda cs: (cs.file, cs.line))

    def get_all_call_sites(self) -> List[Dict[str, Any]]:
        """
        Get all call sites as dictionaries for storage.

        Returns:
            List of call site dictionaries (sorted by file and line)
        """
        sorted_call_sites = sorted(self.call_sites, key=lambda cs: (cs.file, cs.line))
        return [cs.to_dict() for cs in sorted_call_sites]
