"""
Call graph analysis service — extracted from CppAnalyzer.

Handles call graph queries: incoming/outgoing calls, call sites,
and call paths between functions.
"""

import json
from typing import Any, Dict, List, Optional, Set

from .._core import diagnostics
from .._search.call_graph import CallGraphAnalyzer
from .._search.dependency_graph import DependencyGraphBuilder
from .._persistence.persistence_context import PersistenceContext
from .._symbols.usr_decoder import usr_to_display_name
from .._symbols.model import build_location_objects, omit_empty


class CallGraphService:
    """
    Manages call graph analysis: incoming/outgoing calls, call sites,
    and call path queries.
    """

    def __init__(self, context: PersistenceContext):
        """
        Initialize CallGraphService.

        Args:
            context: Persistence context for access to cache_manager.
        """
        self.context = context
        assert context.cache_manager is not None
        self.cache_manager = context.cache_manager

        # Dependencies set after construction to break the circular dependency
        # between CallGraphService and SymbolIndexStore/QueryEngine.
        self.symbol_store: Any = None
        self.query_engine: Any = None

        self.call_graph_analyzer = CallGraphAnalyzer()
        self.dependency_graph: Optional[DependencyGraphBuilder] = None

    def set_dependencies(self, symbol_store: Any, query_engine: Any) -> None:
        """Wire symbol store and query engine after they are created."""
        self.symbol_store = symbol_store
        self.query_engine = query_engine

    def set_dependency_graph(self, builder: Optional[DependencyGraphBuilder]) -> None:
        """Set the dependency graph builder, wired by the composition root."""
        self.dependency_graph = builder
        if builder is not None:
            diagnostics.debug("Dependency graph builder initialized")
        else:
            diagnostics.debug("Dependency graph not available (non-SQLite backend)")

    def setup_cache_backend(self) -> None:
        """Wire the call graph analyzer to the SQLite cache backend."""
        self.call_graph_analyzer.cache_backend = self.cache_manager.backend

    # ------------------------------------------------------------------
    # Call site streaming (used during indexing)
    # ------------------------------------------------------------------

    def _process_call_buffer(self, calls_buffer: List[Any]) -> None:
        """Process the call buffer and add relationships to the call graph analyzer."""
        if not calls_buffer:
            return

        diagnostics.debug(f"Processing {len(calls_buffer)} calls from buffer")
        diagnostics.debug(f"First call format: {calls_buffer[0]}")

        self.call_graph_analyzer.process_call_buffer(calls_buffer)

    def stream_call_sites(self, file_path: str, call_sites: List[Dict]):
        """Stream call sites to SQLite and update in-memory call graph."""
        diagnostics.debug(f"Streaming {len(call_sites)} call sites from {file_path} to SQLite")
        cache_manager = self.cache_manager
        if cache_manager and cache_manager.backend:
            cache_manager.backend.delete_call_sites_by_file(file_path)
            cache_manager.backend.save_call_sites_batch(call_sites)

        for cs_dict in call_sites:
            self.call_graph_analyzer.add_call(
                cs_dict["caller_usr"],
                cs_dict["callee_usr"],
                cs_dict["file"],
                cs_dict["line"],
                cs_dict.get("column"),
                store_call_site=False,
            )

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    def find_incoming_calls(
        self,
        function_name: str,
        class_name: str = "",
        include_call_sites: bool = True,
        project_only: bool = True,
    ) -> Dict[str, Any]:
        """
        Find all functions that call the specified function.

        Args:
            function_name: Name of the target function
            class_name: Optional class name to disambiguate methods
            include_call_sites: Whether to include call site locations (Phase 3)
            project_only: When True (default), only return callers from project files.
                When False, also include callers from external dependencies (shown as
                {"usr": "<USR>", "is_project": false} entries since no metadata is indexed).

        Returns:
            Dictionary with:
                - callers: List of caller function info (backward compatible)
                - call_sites: List of call site locations (Phase 3, if include_call_sites=True)
        """
        callers_list: List[Dict[str, Any]] = []
        call_sites_list: List[Dict[str, Any]] = []

        target_functions = self.query_engine.search_functions(
            function_name, project_only=False, class_name=class_name
        )

        target_usrs = self._collect_target_usrs(target_functions)

        total_raw_callers = 0
        for usr in target_usrs:
            callers = self.call_graph_analyzer.find_incoming_calls(usr)
            total_raw_callers += len(callers)
            for caller_usr in callers:
                self._add_caller(caller_usr, callers_list, project_only)

            if include_call_sites:
                call_sites = self.call_graph_analyzer.get_call_sites_for_callee(usr)
                for call_site in call_sites:
                    self._add_call_site(call_site, call_sites_list, project_only)

        target_qualified_name = (
            target_functions[0]["qualified_name"] if target_functions else function_name
        )
        result: Dict[str, Any] = {
            "function": function_name,
            "callers": callers_list,
            "_function_found": len(target_usrs) > 0,
            "_has_any_in_graph": total_raw_callers > 0,
            "_target_qualified_name": target_qualified_name,
        }

        if include_call_sites:
            call_sites_list.sort(key=lambda cs: (cs["file"], cs["line"]))
            result["call_sites"] = call_sites_list
            result["total_call_sites"] = len(call_sites_list)

        return result

    def find_callees(
        self, function_name: str, class_name: str = "", project_only: bool = True
    ) -> Dict[str, Any]:
        """
        Find all functions called by the specified function.

        Args:
            function_name: Name of the source function
            class_name: Optional class name to disambiguate methods
            project_only: When True (default), only return callees from project files.
                When False, also include callees from external dependencies.

        Returns:
            Dictionary with:
                - function: The source function name
                - callees: List of callee function info
        """
        callees_list: List[Dict[str, Any]] = []

        target_functions = self.query_engine.search_functions(
            function_name, project_only=False, class_name=class_name
        )

        target_usrs = self._collect_target_usrs(target_functions)

        total_raw_callees = 0
        for usr in target_usrs:
            callees = self.call_graph_analyzer.find_callees(usr)
            total_raw_callees += len(callees)
            for callee_usr in callees:
                self._add_callee(callee_usr, callees_list, project_only, target_usrs)

        target_qualified_name = (
            target_functions[0]["qualified_name"] if target_functions else function_name
        )
        return {
            "function": function_name,
            "callees": callees_list,
            "_function_found": len(target_usrs) > 0,
            "_has_any_in_graph": total_raw_callees > 0,
            "_target_qualified_name": target_qualified_name,
        }

    def get_call_sites(self, function_name: str, class_name: str = "") -> List[Dict[str, Any]]:
        """
        Get all call sites FROM a specific function with line-level precision (Phase 3).

        Args:
            function_name: Name of the source function
            class_name: Optional class name to disambiguate methods

        Returns:
            List of call site dictionaries with exact file:line:column locations
        """
        call_sites_list: List[Dict[str, Any]] = []

        source_functions = self.query_engine.search_functions(
            function_name, project_only=False, class_name=class_name
        )

        source_usrs = self._collect_target_usrs(source_functions)

        for usr in source_usrs:
            call_sites = self.call_graph_analyzer.get_call_sites_for_caller(usr)
            for call_site in call_sites:
                if self.symbol_store.contains_usr(call_site.callee_usr):
                    call_sites_list.append(self._build_call_site_entry(call_site))
                else:
                    self._add_external_call_site(call_site, call_sites_list)

        call_sites_list.sort(key=lambda cs: (cs["file"], cs["line"]))

        return call_sites_list

    def get_call_path(
        self, from_function: str, to_function: str, max_depth: int = 10
    ) -> List[List[str]]:
        """Find call paths from one function to another using BFS"""
        from_funcs = self.query_engine.search_functions(from_function, project_only=False)
        to_funcs = self.query_engine.search_functions(to_function, project_only=False)

        if not from_funcs or not to_funcs:
            return []

        from_usrs = self._get_usrs_for_functions(from_funcs)
        to_usrs = self._get_usrs_for_functions(to_funcs)

        return self._find_paths_bfs(from_usrs, to_usrs, max_depth)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_target_usrs(self, target_functions: List[Dict[str, Any]]) -> Set[str]:
        """Collect USRs for target functions by matching file/line metadata."""
        target_usrs = set()
        for func in target_functions:
            _loc = func.get("definition") or func.get("declaration") or {}
            _func_file = _loc.get("file")
            _func_line = _loc.get("line")
            for symbol in self.symbol_store.get_functions_by_name(
                func["qualified_name"].split("::")[-1]
            ):
                if symbol.usr and symbol.file == _func_file and symbol.line == _func_line:
                    target_usrs.add(symbol.usr)
        return target_usrs

    def _add_caller(
        self, caller_usr: str, callers_list: List[Dict[str, Any]], project_only: bool
    ) -> None:
        """Add a single caller to the callers list, respecting project_only filter."""
        caller_info = self.symbol_store.get_symbol_by_usr(caller_usr)
        if caller_info is not None:
            callers_list.append(
                omit_empty(
                    {
                        "qualified_name": caller_info.qualified_name or caller_info.name,
                        "kind": caller_info.kind,
                        "signature": caller_info.signature,
                        "parent_class": caller_info.parent_class or None,
                        "is_project": caller_info.is_project,
                        **build_location_objects(caller_info),
                    }
                )
            )
        elif not project_only:
            rich = self.symbol_store.resolve_symbol_info(caller_usr)
            if rich is not None:
                callers_list.append(rich)
            else:
                callers_list.append(
                    {
                        "qualified_name": usr_to_display_name(caller_usr),
                        "is_project": False,
                    }
                )

    def _add_call_site(
        self, call_site, call_sites_list: List[Dict[str, Any]], project_only: bool
    ) -> None:
        """Add a single call site to the call sites list, respecting project_only filter."""
        caller_info = self.symbol_store.get_symbol_by_usr(call_site.caller_usr)
        if caller_info is not None:
            call_sites_list.append(
                {
                    "file": call_site.file,
                    "line": call_site.line,
                    "column": call_site.column,
                    "caller": caller_info.name,
                    "caller_file": caller_info.file,
                    "caller_signature": caller_info.signature,
                }
            )
        elif not project_only:
            call_sites_list.append(
                {
                    "file": call_site.file,
                    "line": call_site.line,
                    "column": call_site.column,
                    "caller": usr_to_display_name(call_site.caller_usr),
                }
            )

    def _build_call_site_entry(self, call_site: Any) -> Dict[str, Any]:
        """Build a call site entry for a callee that exists in the project index."""
        target_info = self.symbol_store.get_symbol_by_usr(call_site.callee_usr)
        assert target_info is not None
        entry: Dict[str, Any] = {
            "target": target_info.name,
            "target_signature": target_info.signature,
            "target_file": target_info.file,
            "target_kind": target_info.kind,
            "file": call_site.file,
            "line": call_site.line,
            "column": call_site.column,
        }
        if call_site.display_name:
            entry["target"] = call_site.display_name
        return entry

    def _add_external_call_site(
        self, call_site: Any, call_sites_list: List[Dict[str, Any]]
    ) -> None:
        """Add an external call site if it is template-mediated."""
        if not (call_site.display_name and call_site.template_project_types):
            return
        try:
            tmpl_types = json.loads(call_site.template_project_types)
        except (json.JSONDecodeError, TypeError):
            tmpl_types = []
        call_sites_list.append(
            {
                "target": call_site.display_name,
                "target_kind": "function",
                "file": call_site.file,
                "line": call_site.line,
                "column": call_site.column,
                "is_template_mediated": True,
                "template_types": tmpl_types,
            }
        )

    def _add_callee(
        self,
        callee_usr: str,
        callees_list: List[Dict[str, Any]],
        project_only: bool,
        target_usrs: Set[str],
    ) -> None:
        """Add a single callee to the callees list, respecting project_only filter."""
        callee_info = self.symbol_store.get_symbol_by_usr(callee_usr)
        if callee_info is not None:
            callees_list.append(
                omit_empty(
                    {
                        "qualified_name": callee_info.qualified_name or callee_info.name,
                        "kind": callee_info.kind,
                        "signature": callee_info.signature,
                        "parent_class": callee_info.parent_class or None,
                        "is_project": callee_info.is_project,
                        **build_location_objects(callee_info),
                    }
                )
            )
            return

        tmpl_info = self._get_template_mediated_info(target_usrs, callee_usr)
        if tmpl_info:
            callees_list.append(tmpl_info)
            return

        if not project_only:
            rich = self.symbol_store.resolve_symbol_info(callee_usr)
            if rich is not None:
                callees_list.append(rich)
            else:
                callees_list.append(
                    {
                        "qualified_name": usr_to_display_name(callee_usr),
                        "is_project": False,
                    }
                )

    def _get_usrs_for_functions(self, funcs: List[Dict[str, Any]]) -> set:
        """Resolve a list of function search results to a set of USRs."""
        usrs = set()
        for func in funcs:
            _loc = func.get("definition") or func.get("declaration") or {}
            _func_file = _loc.get("file")
            _func_line = _loc.get("line")
            for symbol in self.symbol_store.get_functions_by_name(
                func["qualified_name"].split("::")[-1]
            ):
                if symbol.usr and symbol.file == _func_file and symbol.line == _func_line:
                    usrs.add(symbol.usr)
        return usrs

    def _find_paths_bfs(self, from_usrs: set, to_usrs: set, max_depth: int) -> List[List[str]]:
        """Perform BFS to find paths between sets of USRs."""
        paths = []
        for from_usr in from_usrs:
            queue = [(from_usr, [from_usr])]
            visited = {from_usr}
            depth = 0

            while queue and depth < max_depth:
                next_queue = []
                for current_usr, path in queue:
                    if current_usr in to_usrs:
                        name_path = []
                        for usr in path:
                            info = self.symbol_store.get_symbol_by_usr(usr)
                            if info is not None:
                                name_path.append(
                                    f"{info.parent_class}::{info.name}"
                                    if info.parent_class
                                    else info.name
                                )
                        paths.append(name_path)
                        continue

                    for callee_usr in self.call_graph_analyzer.find_callees(current_usr):
                        if callee_usr not in visited:
                            visited.add(callee_usr)
                            next_queue.append((callee_usr, path + [callee_usr]))

                queue = next_queue
                depth += 1

        return paths

    def _get_template_mediated_info(
        self, target_usrs: set, callee_usr: str
    ) -> Optional[Dict[str, Any]]:
        """Check if a callee has template-mediated project type relevance.

        When an external template function (e.g. std::make_shared) is called with a
        project type as a template argument, this returns a result dict that surfaces
        the call even when project_only=True.

        Returns None if no project-type template args are found.
        """
        backend = self.cache_manager.backend
        if backend is None or not hasattr(backend, "get_template_mediated_call_sites"):
            return None
        rows = backend.get_template_mediated_call_sites(list(target_usrs), callee_usr)
        if not rows:
            return None
        row = rows[0]
        display_name = row.get("display_name") or usr_to_display_name(callee_usr)
        try:
            project_types = json.loads(row["template_project_types"])
        except (json.JSONDecodeError, TypeError):
            project_types = []
        return {
            "qualified_name": display_name,
            "is_project": False,
            "is_template_mediated": True,
            "template_types": project_types,
        }
