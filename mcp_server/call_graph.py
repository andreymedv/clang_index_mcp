"""Call graph analysis for C++ code."""

from typing import Dict, List, Set, Optional, Any
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
            cache_backend: SQLiteCacheBackend for lazy loading call graph data.
                          Required for Task 4.3 memory optimization (~2 GB savings).
                          Call graph relationships are stored ONLY in SQLite,
                          not in memory.
        """
        # Phase 4: Task 4.3 - Remove in-memory call_graph and reverse_call_graph dicts
        # All call graph queries now go directly to SQLite (~2 GB memory savings)
        # The call_graph and reverse_call_graph dicts have been removed

        # Phase 3: Line-level call site tracking
        # Only stores call sites from CURRENT indexing session
        # Historical call sites are loaded on-demand from SQLite via cache_backend
        self.call_sites: Set[CallSite] = (
            set()
        )  # Current session call sites (using set to avoid duplicates)

        # Memory optimization: ALL call graph data stored in SQLite
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
            # Phase 4: Task 4.3 - Removed in-memory call_graph and reverse_call_graph
            # Call graph relationships are now stored ONLY in SQLite via call_sites table

            # Phase 3: Store call site with location if provided
            # Phase 4: Only store in memory if store_call_site=True
            # Main process should set store_call_site=False and save directly to SQLite
            if store_call_site and file and line:
                call_site = CallSite(caller_usr, callee_usr, file, line, column)
                self.call_sites.add(call_site)  # Using set.add() to automatically deduplicate

    def clear(self):
        """
        Clear all call graph data.

        Phase 4: Task 4.3 - Only clears current session call_sites.
        Historical call graph data in SQLite is not affected.
        """
        # Phase 4: Task 4.3 - Removed in-memory call_graph and reverse_call_graph
        # Only clear current session call sites
        self.call_sites.clear()

    def remove_symbol(self, usr: str):
        """
        Remove a symbol from the call graph completely.

        Phase 4: Task 4.3 - Deletes call sites from SQLite where USR appears as caller or callee.
        """
        # Phase 4: Task 4.3 - Delete from SQLite instead of in-memory dicts
        if self.cache_backend:
            try:
                self.cache_backend.delete_call_sites_by_usr(usr)
                # Silently ignore if no call sites found (not an error)
            except Exception:
                pass  # Silently ignore deletion errors

        # Also remove from current session call_sites (if any)
        self.call_sites = {
            cs for cs in self.call_sites if cs.caller_usr != usr and cs.callee_usr != usr
        }

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

        Phase 4: Task 4.3 - Queries ONLY SQLite (no in-memory dicts).
        All call graph data is now stored exclusively in the call_sites table.
        """
        result: Set[str] = set()

        # Phase 4: Task 4.3 - Query SQLite exclusively (no in-memory dicts)
        if self.cache_backend:
            try:
                db_results = self.cache_backend.get_call_sites_for_callee(function_usr)
                for cs_dict in db_results:
                    caller_usr = cs_dict.get("caller_usr")
                    if caller_usr:
                        result.add(caller_usr)
            except Exception:
                pass  # Silently ignore DB errors, return empty set

        # Also check current session call_sites (before they're saved to SQLite)
        for cs in self.call_sites:
            if cs.callee_usr == function_usr:
                result.add(cs.caller_usr)

        return result

    def find_callees(self, function_usr: str) -> Set[str]:
        """
        Find all functions called by the specified function.

        Phase 4: Task 4.3 - Queries ONLY SQLite (no in-memory dicts).
        All call graph data is now stored exclusively in the call_sites table.
        """
        result: Set[str] = set()

        # Phase 4: Task 4.3 - Query SQLite exclusively (no in-memory dicts)
        if self.cache_backend:
            try:
                db_results = self.cache_backend.get_call_sites_for_caller(function_usr)
                for cs_dict in db_results:
                    callee_usr = cs_dict.get("callee_usr")
                    if callee_usr:
                        result.add(callee_usr)
            except Exception:
                pass  # Silently ignore DB errors, return empty set

        # Also check current session call_sites (before they're saved to SQLite)
        for cs in self.call_sites:
            if cs.caller_usr == function_usr:
                result.add(cs.callee_usr)

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
        """
        Get statistics about the call graph.

        DEPRECATED (Phase 4, Task 4.3): This method is now deprecated.
        The in-memory call_graph and reverse_call_graph dicts were removed
        to save ~2 GB of memory. Statistics would require expensive SQLite queries.

        Returns placeholder data for backward compatibility.
        """
        # Phase 4: Task 4.3 - Return placeholder data (method deprecated)
        return {
            "total_functions_with_calls": 0,
            "total_functions_being_called": 0,
            "total_unique_calls": 0,
            "most_called_functions": [],
            "functions_with_most_calls": [],
            "note": "DEPRECATED: get_call_statistics() is deprecated in Phase 4 (Task 4.3). "
            "Use SQLite queries directly for call graph statistics if needed.",
        }

    def _get_most_called_functions(self, limit: int) -> List[tuple]:
        """
        Get the most frequently called functions.

        DEPRECATED (Phase 4, Task 4.3): Placeholder for backward compatibility.
        """
        return []

    def _get_functions_with_most_calls(self, limit: int) -> List[tuple]:
        """
        Get functions that make the most calls.

        DEPRECATED (Phase 4, Task 4.3): Placeholder for backward compatibility.
        """
        return []

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
