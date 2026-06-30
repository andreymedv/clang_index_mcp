"""
Coordinates AST-based symbol extraction.

SymbolExtractor no longer performs libclang traversal directly. It delegates
parsing to a SymbolParser port and applies the returned ParseResult to the
shared symbol store, call graph, and cache.
"""

import json
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from clang.cindex import TranslationUnit

from .._core import diagnostics
from .._symbols.model import SymbolInfo
from .._symbols.ports.parser import ParseResult, SymbolParser
from .._compilation.template_resolver import TemplateResolver

if TYPE_CHECKING:
    from .._compilation.compilation_environment import CompilationEnvironment
    from .._core.concurrency_context import ConcurrencyContext
    from .._persistence.cache_orchestrator import CacheOrchestrator
    from .._symbols.symbol_index_store import SymbolIndexStore


class SymbolExtractor:
    """Coordinates symbol extraction from translation units."""

    def __init__(
        self,
        symbol_store: "SymbolIndexStore",
        concurrency: "ConcurrencyContext",
        compilation_env: "CompilationEnvironment",
        cache_orchestrator: "CacheOrchestrator",
        call_graph_service: Any,
        parser: SymbolParser,
    ):
        """
        Initialize SymbolExtractor.

        Args:
            symbol_store: In-memory symbol indexes.
            concurrency: Concurrency context with index_lock.
            compilation_env: Compilation environment for file scanning.
            cache_orchestrator: Cache orchestration and header tracking.
            call_graph_service: Call graph and dependency tracking.
            parser: SymbolParser port implementation responsible for AST traversal.
        """
        self.parser = parser
        self.symbol_store = symbol_store
        self.concurrency = concurrency
        self.compilation_env = compilation_env
        self.cache_orchestrator = cache_orchestrator
        self.call_graph_service = call_graph_service

    @property
    def index_lock(self):
        return self.concurrency.index_lock

    @property
    def class_index(self):
        return self.symbol_store.class_index

    @property
    def function_index(self):
        return self.symbol_store.function_index

    @property
    def file_index(self):
        return self.symbol_store.file_index

    @property
    def usr_index(self):
        return self.symbol_store.usr_index

    @property
    def dependency_graph(self):
        return self.call_graph_service.dependency_graph

    def _is_project_file(self, file_path: str) -> bool:
        return self.compilation_env.is_project_file(file_path)

    def get_file_hash(self, file_path: str) -> str:
        return self.cache_orchestrator.get_file_hash(file_path)

    def _find_primary_template_info(self, primary_template_usr: str) -> Optional[Any]:
        """Look up the primary template in class_index by USR."""
        with self.index_lock:
            for name, infos in self.class_index.items():
                for info in infos:
                    if info.usr == primary_template_usr:
                        return info
        return None

    def _parse_template_params(self, primary_info: Any) -> List[dict]:
        """Parse template_parameters JSON from a primary template info."""
        if not primary_info.template_parameters:
            return []
        try:
            result: List[Dict[str, Any]] = json.loads(primary_info.template_parameters)
            return result
        except (json.JSONDecodeError, TypeError):
            return []

    def _parse_json_field(self, field_value: Optional[str]) -> Any:
        """Safely parse a JSON field, returning None on failure."""
        if not field_value:
            return None
        try:
            return json.loads(field_value)
        except (json.JSONDecodeError, TypeError):
            return None

    def _process_deferred_instantiation(self, info: SymbolInfo) -> bool:
        """Process a single deferred instantiation and return True if resolved."""
        if not info.template_arguments or not info.primary_template_usr or info.base_classes:
            return False

        template_args = self._parse_json_field(info.template_arguments)
        if not template_args:
            return False

        primary_info = self.usr_index.get(info.primary_template_usr)
        if not primary_info:
            return False

        template_params = self._parse_json_field(primary_info.template_parameters)
        if not template_params:
            return False

        param_to_arg = TemplateResolver.build_param_mapping(template_params, template_args)

        resolved = TemplateResolver.substitute_in_bases(
            primary_info.base_classes, param_to_arg, template_args
        )

        if resolved:
            info.base_classes = resolved
            info.template_arguments = None
            diagnostics.debug(f"Deferred resolution: {info.qualified_name} -> bases={resolved}")
            return True
        return False

    def resolve_deferred_instantiation_bases(self) -> int:
        """Resolve base_classes for template instantiations that couldn't be resolved during parsing."""
        resolved_count = 0
        for name, infos in self.class_index.items():
            for info in infos:
                if self._process_deferred_instantiation(info):
                    resolved_count += 1

        if resolved_count > 0:
            diagnostics.info(
                f"Resolved base_classes for {resolved_count} template instantiation(s)"
            )
        return resolved_count

    def _extract_template_base_name_from_usr(self, usr: str) -> Optional[str]:
        """Extract the base template name from a USR."""
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

    def _should_extract_header(self, file_path: str) -> bool:
        """Check if a header file should be extracted based on project status and tracker."""
        if not self._is_project_file(file_path):
            return False

        try:
            file_hash = self.get_file_hash(file_path)
            result = bool(self.cache_orchestrator.try_claim_header(file_path, file_hash))
            return result
        except Exception as e:
            diagnostics.warning(f"Error checking header {file_path}: {e}")
            return False

    def _finalize_header_status(self, processed_headers: Dict[str, str]):
        """Mark successfully claimed headers as completed in the tracker."""
        for header, file_hash in processed_headers.items():
            try:
                self.cache_orchestrator.mark_header_completed(header, file_hash)
            except Exception as e:
                diagnostics.warning(f"Error marking header {header} as completed: {e}")

    def _update_dependency_graph(self, tu: TranslationUnit, source_file: str):
        """Extract and update dependencies for the given translation unit."""
        if self.dependency_graph is not None:
            try:
                includes = self.dependency_graph.extract_includes_from_tu(tu, source_file)
                self.dependency_graph.update_dependencies(source_file, includes)
            except Exception as e:
                diagnostics.warning(f"Failed to update dependencies for {source_file}: {e}")

    def _apply_parse_result(self, result: ParseResult) -> None:
        """Copy parser results into thread-local buffers for bulk writing."""
        symbols_buffer, calls_buffer, aliases_buffer = self.concurrency.get_thread_local_buffers()
        symbols_buffer.extend(result.symbols)
        calls_buffer.extend(result.call_sites)
        aliases_buffer.extend(result.type_aliases)

    def index_translation_unit(self, tu: TranslationUnit, source_file: str) -> Dict[str, Any]:
        """Process translation unit, extracting symbols from source and project headers."""
        processed_files: Set[str] = set()
        skipped_headers: Set[str] = set()
        headers_to_extract: Set[str] = set()

        def should_extract_from_file(file_path: str) -> bool:
            if file_path == source_file:
                processed_files.add(file_path)
                return True

            if file_path in headers_to_extract:
                return True
            if file_path in skipped_headers:
                return False

            if self._should_extract_header(file_path):
                headers_to_extract.add(file_path)
                processed_files.add(file_path)
                return True
            else:
                skipped_headers.add(file_path)
                return False

        self.concurrency.init_thread_local_buffers()
        result = self.parser.parse(tu, source_file, should_extract_from_file)
        self._apply_parse_result(result)
        self.symbol_store.bulk_write_symbols()

        self._finalize_header_status(result.processed_headers)
        self._update_dependency_graph(tu, source_file)

        return {
            "source_file": source_file,
            "processed": list(processed_files),
            "skipped": list(skipped_headers),
        }
