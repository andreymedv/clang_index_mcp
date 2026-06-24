"""File-scoped symbol lookup helpers for the query engine.

Contains implementations for `find_in_file` (exact path or glob) and
`get_files_containing_symbol`, keeping path matching and file traversal logic
out of the main QueryEngine class.
"""

from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .._search.pattern_matcher import matches_qualified_pattern
from .._search.search_criteria import SearchCriteria
from .._search.search_engine import SearchEngine
from .ports.search_deps import SearchDependencies


def matches_glob(indexed_file: str, glob_pattern: str, project_root: Optional[str]) -> bool:
    """Check if an indexed file matches a glob pattern using multiple strategies."""
    if fnmatch(indexed_file, glob_pattern):
        return True
    if fnmatch(indexed_file, "**/" + glob_pattern):
        return True
    if project_root:
        try:
            rel_path = str(Path(indexed_file).relative_to(project_root))
            return fnmatch(rel_path, glob_pattern)
        except ValueError:
            pass
    return False


def filter_results_by_files(
    items: List[Dict[str, Any]], matched_files: Set[str]
) -> List[Dict[str, Any]]:
    """Filter search results to only include items from specified files."""
    results = []
    for item in items:
        _item_loc = item.get("definition") or item.get("declaration") or {}
        item_file = _item_loc.get("file") or item.get("file", "")
        if item_file in matched_files:
            results.append(item)
    return results


def _project_root_str(context: SearchDependencies) -> Optional[str]:
    root = context.project_root
    return str(root) if root is not None else None


def find_in_files_glob(
    glob_pattern: str,
    symbol_pattern: str,
    context: SearchDependencies,
    search_engine: SearchEngine,
) -> Dict[str, Any]:
    """Search for symbols in files matching a glob pattern."""
    symbol_store = context.symbol_store
    assert symbol_store is not None
    project_root = _project_root_str(context)
    matched_files = [
        f for f in symbol_store.iter_file_paths() if matches_glob(f, glob_pattern, project_root)
    ]

    if not matched_files:
        return {
            "results": [],
            "matched_files": [],
            "suggestions": get_path_suggestions(glob_pattern, context),
            "message": f"No files found matching glob pattern '{glob_pattern}'",
        }

    class_criteria = SearchCriteria(pattern=symbol_pattern, project_only=False)
    all_classes = search_engine.search_classes(class_criteria)
    if isinstance(all_classes, tuple):
        all_classes = all_classes[0]

    function_criteria = SearchCriteria(pattern=symbol_pattern, project_only=False)
    all_functions = search_engine.search_functions(function_criteria)
    if isinstance(all_functions, tuple):
        all_functions = all_functions[0]

    matched_files_set = set(matched_files)
    results = filter_results_by_files(all_classes + all_functions, matched_files_set)

    return {
        "results": results,
        "matched_files": sorted(matched_files),
        "message": (
            f"Found {len(results)} symbols in {len(matched_files)} files "
            f"matching '{glob_pattern}'"
        ),
    }


def resolve_file_path(file_path: str, project_root: Optional[str]) -> Optional[str]:
    """Resolve a file path to absolute path for matching."""
    if Path(file_path).is_absolute():
        return str(Path(file_path).resolve())
    if project_root:
        potential_path = Path(project_root) / file_path
        if potential_path.exists():
            return str(potential_path.resolve())
    return None


def match_item_to_file(item: Dict[str, Any], file_path: str, abs_file_path: Optional[str]) -> bool:
    """Check if a search result item belongs to the given file."""
    _item_loc = item.get("definition") or item.get("declaration") or {}
    item_file = _item_loc.get("file") or item.get("file", "")
    if not item_file:
        return False

    item_abs = str(Path(item_file).resolve()) if item_file else ""

    if abs_file_path and item_abs == abs_file_path:
        return True
    if item_file.endswith(file_path) or item_abs.endswith(file_path):
        return True
    return False


def find_in_file_exact(
    file_path: str,
    pattern: str,
    context: SearchDependencies,
    search_engine: SearchEngine,
) -> Dict[str, Any]:
    """Search for symbols in a specific file (exact or suffix match)."""
    results = []
    matched_file = None

    class_criteria = SearchCriteria(pattern=pattern, project_only=False)
    all_classes = search_engine.search_classes(class_criteria)
    if isinstance(all_classes, tuple):
        all_classes = all_classes[0]

    function_criteria = SearchCriteria(pattern=pattern, project_only=False)
    all_functions = search_engine.search_functions(function_criteria)
    if isinstance(all_functions, tuple):
        all_functions = all_functions[0]

    abs_file_path = resolve_file_path(file_path, _project_root_str(context))

    for item in all_classes + all_functions:
        if match_item_to_file(item, file_path, abs_file_path):
            results.append(item)
            _item_loc = item.get("definition") or item.get("declaration") or {}
            matched_file = _item_loc.get("file") or item.get("file", "")

    if results:
        return {
            "results": results,
            "matched_files": [matched_file] if matched_file else [],
            "message": f"Found {len(results)} symbols in '{file_path}'",
        }
    else:
        suggestions = get_path_suggestions(file_path, context)
        return {
            "results": [],
            "matched_files": [],
            "suggestions": suggestions,
            "message": (
                f"No file found matching '{file_path}'. See suggestions for similar paths."
            ),
        }


def get_path_suggestions(
    partial_path: str, context: SearchDependencies, max_suggestions: int = 5
) -> List[str]:
    """Get suggestions for similar file paths based on partial input."""
    symbol_store = context.symbol_store
    assert symbol_store is not None
    suggestions = []
    partial_lower = partial_path.lower()
    partial_basename = Path(partial_path).name.lower()
    path_parts = [p.lower() for p in Path(partial_path).parts if p]

    for indexed_file in symbol_store.iter_file_paths():
        indexed_lower = indexed_file.lower()
        indexed_basename = Path(indexed_file).name.lower()

        score = 0

        if indexed_basename == partial_basename:
            score += 100
        elif partial_basename in indexed_basename:
            score += 50
        elif partial_lower in indexed_lower:
            score += 30

        for part in path_parts:
            if part in indexed_lower:
                score += 10

        if score > 0:
            suggestions.append((score, indexed_file))

    suggestions.sort(key=lambda x: (-x[0], x[1]))
    return [path for _, path in suggestions[:max_suggestions]]


def find_in_file(
    file_path: str,
    pattern: str,
    context: SearchDependencies,
    search_engine: SearchEngine,
) -> Dict[str, Any]:
    """Search for symbols within a specific file or files matching a glob pattern."""
    glob_chars = set("*?[]")
    is_glob = any(c in file_path for c in glob_chars)

    if is_glob:
        return find_in_files_glob(file_path, pattern, context, search_engine)
    return find_in_file_exact(file_path, pattern, context, search_engine)


def _find_class_definition_files(
    symbol_name: str,
    symbol_kind: Optional[str],
    simple_name: str,
    project_only: bool,
    files: Set[str],
    symbol_store,
) -> Optional[str]:
    """Find files where the class is defined and return its kind."""
    if symbol_kind in (None, "class"):
        for info in symbol_store.get_classes_by_name(simple_name):
            if matches_qualified_pattern(info.qualified_name or info.name, symbol_name):
                if not project_only or info.is_project:
                    files.add(info.file)
                    if info.header_file:
                        files.add(info.header_file)
                    return str(info.kind)  # type: ignore[no-any-return]
    return None


def _find_function_definition_files(
    symbol_name: str,
    symbol_kind: Optional[str],
    simple_name: str,
    project_only: bool,
    files: Set[str],
    symbol_store,
) -> Optional[str]:
    """Find files where the function/method is defined and return its kind."""
    kind = None
    if symbol_kind in (None, "function", "method"):
        for info in symbol_store.get_functions_by_name(simple_name):
            if matches_qualified_pattern(info.qualified_name or info.name, symbol_name):
                if not project_only or info.is_project:
                    files.add(info.file)
                    if info.header_file:
                        files.add(info.header_file)
                    if not kind:
                        kind = info.kind
    return kind


def _find_symbol_definition_files(
    symbol_name: str,
    symbol_kind: Optional[str],
    simple_name: str,
    project_only: bool,
    files: Set[str],
    symbol_store,
) -> Optional[str]:
    """Find files where the symbol is defined and return the first found kind."""
    kind = _find_class_definition_files(
        symbol_name, symbol_kind, simple_name, project_only, files, symbol_store
    )

    func_kind = _find_function_definition_files(
        symbol_name, symbol_kind, simple_name, project_only, files, symbol_store
    )

    return kind or func_kind


def _find_symbol_caller_files(
    symbol_name: str,
    symbol_kind: Optional[str],
    simple_name: str,
    project_only: bool,
    kind: Optional[str],
    files: Set[str],
    symbol_store,
    call_graph_service,
) -> int:
    """Find files that call the symbol and return the reference count."""
    total_refs = 0
    if kind in ("function", "method") or (not kind and symbol_kind in (None, "function", "method")):

        def _name_matches(info) -> bool:
            return matches_qualified_pattern(info.qualified_name or info.name, symbol_name)

        target_usrs = set()
        for info in symbol_store.get_functions_by_name(simple_name):
            if _name_matches(info) and info.usr:
                if not project_only or info.is_project:
                    target_usrs.add(info.usr)

        for usr in target_usrs:
            callers = call_graph_service.call_graph_analyzer.find_incoming_calls(usr)
            for caller_usr in callers:
                if symbol_store.contains_usr(caller_usr):
                    caller_info = symbol_store.get_symbol_by_usr(caller_usr)
                    assert caller_info is not None
                    if not project_only or caller_info.is_project:
                        files.add(caller_info.file)
                        total_refs += 1
    return total_refs


def _find_class_reference_files(
    symbol_name: str,
    symbol_kind: Optional[str],
    project_only: bool,
    kind: Optional[str],
    files: Set[str],
    symbol_store,
    compilation_env,
) -> None:
    """Find files that reference a class and add them to the set."""
    if kind in ("class", "struct") or (not kind and symbol_kind in (None, "class")):
        for file_path, symbols in symbol_store.iter_file_items():
            if not project_only or compilation_env.is_project_file(file_path):
                for symbol in symbols:
                    sym_qname = symbol.qualified_name or symbol.name
                    parent_qname = symbol.parent_class or ""
                    if matches_qualified_pattern(
                        sym_qname, symbol_name
                    ) or matches_qualified_pattern(parent_qname, symbol_name):
                        files.add(file_path)
                        break


async def get_files_containing_symbol(
    symbol_name: str,
    symbol_kind: Optional[str],
    project_only: bool,
    context: SearchDependencies,
) -> Dict[str, Any]:
    """Get all files that contain references to or define a symbol."""
    symbol_store = context.symbol_store
    assert symbol_store is not None
    files: Set[str] = set()
    total_refs = 0
    kind = None

    simple_name = symbol_name.split("::")[-1]

    with context.concurrency.index_lock:
        kind = _find_symbol_definition_files(
            symbol_name, symbol_kind, simple_name, project_only, files, symbol_store
        )

        total_refs = _find_symbol_caller_files(
            symbol_name,
            symbol_kind,
            simple_name,
            project_only,
            kind,
            files,
            symbol_store,
            context.call_graph_service,
        )

        _find_class_reference_files(
            symbol_name,
            symbol_kind,
            project_only,
            kind,
            files,
            symbol_store,
            context.compilation_env,
        )

    file_list = sorted(list(files))

    if total_refs == 0:
        total_refs = len(file_list)

    return {
        "symbol": symbol_name,
        "kind": kind,
        "files": file_list,
        "total_references": total_refs,
    }
