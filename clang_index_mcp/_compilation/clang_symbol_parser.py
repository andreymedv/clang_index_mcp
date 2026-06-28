"""libclang-based adapter for the SymbolParser port."""

import json
import re
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from clang.cindex import CursorKind

from .._core import diagnostics
from .._symbols.model import SymbolInfo
from .._symbols.ports.parser import ParseResult, SymbolParser
from .._symbols.alias_extractor import extract_alias_info
from .._symbols.cursor_utils import extract_namespace, get_qualified_name
from .._symbols.documentation_extractor import extract_documentation
from .._symbols.signature_builder import build_human_readable_signature
from .._symbols.usr_decoder import usr_to_display_name
from .template_resolver import TemplateResolver

if TYPE_CHECKING:
    from .._compilation.compilation_environment import CompilationEnvironment
    from .._persistence.cache_orchestrator import CacheOrchestrator
    from .._symbols.symbol_index_store import SymbolIndexStore


class ClangSymbolParser(SymbolParser):
    """AST traversal and symbol extraction backed by libclang cursors."""

    def __init__(
        self,
        compilation_env: "CompilationEnvironment",
        symbol_store: "SymbolIndexStore",
        cache_orchestrator: "CacheOrchestrator",
    ):
        """
        Initialize ClangSymbolParser.

        Args:
            compilation_env: Compilation environment for project file detection.
            symbol_store: In-memory symbol indexes.
            cache_orchestrator: Cache orchestration for file hashing.
        """
        self.compilation_env = compilation_env
        self.symbol_store = symbol_store
        self.cache_orchestrator = cache_orchestrator

        # Buffers are normally reset by parse(); they are also kept available so
        # _process_cursor can be exercised directly in tests and diagnostics.
        self._symbols_buffer: List[SymbolInfo] = []
        self._calls_buffer: List[Any] = []
        self._aliases_buffer: List[Dict[str, Any]] = []

    def _is_project_file(self, file_path: str) -> bool:
        return self.compilation_env.is_project_file(file_path)

    def _get_file_hash(self, file_path: str) -> str:
        return self.cache_orchestrator.get_file_hash(file_path)

    @property
    def index_lock(self):
        return self.symbol_store.index_lock

    @property
    def class_index(self):
        return self.symbol_store.class_index

    def _build_type_param_map(self, cursor: Any) -> Dict[str, str]:
        """Build a map from 'type-parameter-D-I' to actual template parameter names."""
        type_param_map: Dict[str, str] = {}
        param_index = 0
        for child in cursor.get_children():
            if child.kind in (
                CursorKind.TEMPLATE_TYPE_PARAMETER,
                CursorKind.TEMPLATE_NON_TYPE_PARAMETER,
                CursorKind.TEMPLATE_TEMPLATE_PARAMETER,
            ):
                if child.spelling:
                    type_param_map[f"type-parameter-0-{param_index}"] = child.spelling
                param_index += 1
        return type_param_map

    def _resolve_base_name(self, base_type: Any, type_param_map: Dict[str, str]) -> str:
        """Resolve the qualified name of a base type, substituting template parameters."""
        canonical_type = base_type.get_canonical()
        base_name_qualified = canonical_type.spelling

        if "type-parameter-" in base_name_qualified and type_param_map:

            def _replace_type_param(m: re.Match[str]) -> str:
                key: str = m.group(0)
                return type_param_map.get(key, key)

            base_name_qualified = re.sub(
                r"type-parameter-\d+-\d+", _replace_type_param, base_name_qualified
            )

        if re.search(r"type-parameter-\d+-\d+", base_name_qualified):
            base_name_qualified = base_type.spelling

        if base_name_qualified.startswith("class "):
            base_name_qualified = base_name_qualified[6:]
        elif base_name_qualified.startswith("struct "):
            base_name_qualified = base_name_qualified[7:]

        return str(base_name_qualified)

    def _get_base_classes(self, cursor: Any) -> List[str]:
        """Extract base class names from a class cursor."""
        type_param_map = self._build_type_param_map(cursor)

        base_classes = []
        for child in cursor.get_children():
            if child.kind == CursorKind.CXX_BASE_SPECIFIER:
                base_classes.append(self._resolve_base_name(child.type, type_param_map))

        return base_classes

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

    def _resolve_instantiation_base_classes(
        self, cursor: Any, primary_template_usr: Optional[str]
    ) -> List[str]:
        """Resolve base classes for explicit template instantiations."""
        if not primary_template_usr:
            return []

        template_args = TemplateResolver.extract_args_from_displayname(cursor.displayname)
        if not template_args:
            return []

        primary_info = self._find_primary_template_info(primary_template_usr)
        if not primary_info:
            return []

        template_params = self._parse_template_params(primary_info)
        if not template_params:
            return []

        param_to_arg = TemplateResolver.build_param_mapping(template_params, template_args)

        return TemplateResolver.substitute_in_bases(
            primary_info.base_classes, param_to_arg, template_args
        )

    @staticmethod
    def _get_primary_file(cursor: Any) -> str:
        """Determine the primary file path for a cursor using extent or location."""
        if cursor.extent and cursor.extent.start.file:
            return str(cursor.extent.start.file.name)
        if cursor.location.file:
            return str(cursor.location.file.name)
        return ""

    @staticmethod
    def _extract_cursor_extent(cursor: Any, location: Any) -> Tuple[int, int]:
        """Extract start and end lines from a cursor's extent, falling back to location line."""
        try:
            extent = cursor.extent
            if extent and extent.start.file and extent.end.file:
                return extent.start.line, extent.end.line
        except Exception as e:
            diagnostics.debug(f"Could not extract extent for {cursor.spelling}: {e}")
        return location.line, location.line

    @staticmethod
    def _extract_definition_location(cursor: Any, result: dict) -> None:
        """Populate header_* fields when declaration and definition are in different files."""
        try:
            definition_cursor = cursor.get_definition()
            if not definition_cursor or definition_cursor == cursor:
                return

            decl_location = cursor.location
            def_location = definition_cursor.location

            if not decl_location.file or not def_location.file:
                return

            decl_file = str(decl_location.file.name)
            def_file = str(def_location.file.name)

            if decl_file == def_file:
                return

            result["header_file"] = def_file
            result["header_line"] = def_location.line

            try:
                def_extent = definition_cursor.extent
                if def_extent and def_extent.start.file:
                    result["header_start_line"] = def_extent.start.line
                    result["header_end_line"] = def_extent.end.line
            except Exception:
                result["header_start_line"] = def_location.line
                result["header_end_line"] = def_location.line

        except Exception as e:
            diagnostics.debug(f"Could not track declaration/definition for {cursor.spelling}: {e}")

    @staticmethod
    def _extract_line_range_info(cursor: Any) -> dict:
        """Extract line range and location information from a cursor."""
        location = cursor.location
        primary_file = ClangSymbolParser._get_primary_file(cursor)
        start_line, end_line = ClangSymbolParser._extract_cursor_extent(cursor, location)

        result = {
            "file": primary_file,
            "line": location.line,
            "column": location.column,
            "start_line": start_line,
            "end_line": end_line,
            "header_file": None,
            "header_line": None,
            "header_start_line": None,
            "header_end_line": None,
        }

        ClangSymbolParser._extract_definition_location(cursor, result)

        return result

    @staticmethod
    def _extract_template_parameters(cursor: Any) -> Optional[str]:
        """Extract template parameters from a template cursor."""
        template_params = []

        for child in cursor.get_children():
            if child.kind == CursorKind.TEMPLATE_TYPE_PARAMETER:
                template_params.append({"name": child.spelling, "kind": "type"})
            elif child.kind == CursorKind.TEMPLATE_NON_TYPE_PARAMETER:
                template_params.append(
                    {"name": child.spelling, "kind": "non_type", "type": child.type.spelling}
                )
            elif child.kind == CursorKind.TEMPLATE_TEMPLATE_PARAMETER:
                template_params.append({"name": child.spelling, "kind": "template"})

        if template_params:
            return json.dumps(template_params)
        return None

    @staticmethod
    def _get_primary_template_usr(cursor: Any) -> Optional[str]:
        """Get the USR of the primary template for a template specialization."""
        from clang import cindex

        try:
            specialized_cursor = cindex.conf.lib.clang_getSpecializedCursorTemplate(cursor)
            if specialized_cursor and not specialized_cursor.kind.is_invalid():
                usr: Optional[str] = specialized_cursor.get_usr()
                if usr:
                    return usr
        except Exception:
            pass

        return None

    def _detect_template_specialization(self, cursor: Any) -> bool:
        """Detect if cursor represents a template specialization."""
        try:
            kind = cursor.kind
        except ValueError:
            return False

        if kind == CursorKind.FUNCTION_TEMPLATE:
            return False

        if kind in (
            CursorKind.FUNCTION_DECL,
            CursorKind.CXX_METHOD,
            CursorKind.CLASS_DECL,
            CursorKind.STRUCT_DECL,
        ):
            try:
                displayname = cursor.displayname
                if not isinstance(displayname, str):
                    return False
                if kind in (CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD):
                    paren_pos = displayname.find("(")
                    name_part = displayname[:paren_pos] if paren_pos >= 0 else displayname
                else:
                    name_part = displayname
                return "<" in name_part and ">" in name_part
            except (AttributeError, TypeError):
                return False

        return False

    def _get_common_symbol_data(self, cursor: Any) -> Dict[str, Any]:
        """Extract common metadata for any symbol."""
        qualified_name = get_qualified_name(cursor)
        return {
            "qualified_name": qualified_name,
            "namespace": extract_namespace(qualified_name),
            "loc_info": self._extract_line_range_info(cursor),
            "doc_info": extract_documentation(cursor),
        }

    def _process_cursor(
        self,
        cursor: Any,
        should_extract_from_file: Optional[Callable[[str], bool]] = None,
        parent_class: str = "",
        parent_function_usr: str = "",
    ) -> None:
        """Process a cursor and its children, extracting symbols based on file filter."""
        should_extract = True
        if cursor.location.file and should_extract_from_file is not None:
            file_path = str(cursor.location.file.name)
            should_extract = should_extract_from_file(file_path)

            if not should_extract and not parent_function_usr:
                return

        try:
            kind = cursor.kind
        except ValueError as e:
            diagnostics.debug(f"Skipping cursor with unknown kind: {e}")
            for child in cursor.get_children():
                self._process_cursor(
                    child, should_extract_from_file, parent_class, parent_function_usr
                )
            return

        handler = self._get_cursor_handler(kind)
        if handler is not None:
            handler(
                cursor,
                should_extract,
                should_extract_from_file,
                parent_class,
                parent_function_usr,
            )
            return

        if kind == CursorKind.CALL_EXPR and parent_function_usr:
            self._handle_call_cursor(cursor, parent_function_usr)

        for child in cursor.get_children():
            self._process_cursor(child, should_extract_from_file, parent_class, parent_function_usr)

    def _get_cursor_handler(self, kind: CursorKind) -> Optional[Callable]:
        """Return the handler method for a given cursor kind, or None."""
        if kind == CursorKind.CLASS_TEMPLATE:
            return self._handle_class_template_cursor
        if kind == CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION:
            return self._handle_class_template_cursor
        if kind in (CursorKind.CLASS_DECL, CursorKind.STRUCT_DECL):
            return self._handle_class_cursor
        if kind == CursorKind.FUNCTION_TEMPLATE:
            return self._handle_function_template_cursor
        if kind in (
            CursorKind.FUNCTION_DECL,
            CursorKind.CXX_METHOD,
            CursorKind.CONSTRUCTOR,
            CursorKind.DESTRUCTOR,
            CursorKind.CONVERSION_FUNCTION,
        ):
            return self._handle_function_cursor
        if kind in (
            CursorKind.TYPEDEF_DECL,
            CursorKind.TYPE_ALIAS_DECL,
            CursorKind.TYPE_ALIAS_TEMPLATE_DECL,
        ):
            return self._handle_type_alias_cursor
        return None

    def _handle_class_template_cursor(
        self,
        cursor: Any,
        should_extract: bool,
        should_extract_from_file: Optional[Callable[[str], bool]],
        parent_class: str,
        parent_function_usr: str,
    ) -> None:
        """Process template classes (generic and partial specializations)."""
        symbols_buffer = self._symbols_buffer
        kind = cursor.kind

        if cursor.spelling and should_extract:
            common = self._get_common_symbol_data(cursor)
            qualified_name = common["qualified_name"]
            namespace = common["namespace"]
            loc_info = common["loc_info"]
            doc_info = common["doc_info"]

            base_classes = self._get_base_classes(cursor)
            template_params = self._extract_template_parameters(cursor)

            if kind == CursorKind.CLASS_TEMPLATE:
                symbol_kind = "class_template"
                primary_usr = None
            else:
                symbol_kind = "partial_specialization"
                primary_usr = self._get_primary_template_usr(cursor)

            info = SymbolInfo(
                name=cursor.spelling,
                kind=symbol_kind,
                file=loc_info["file"],
                line=loc_info["line"],
                column=loc_info["column"],
                qualified_name=qualified_name,
                is_project=(self._is_project_file(loc_info["file"]) if loc_info["file"] else False),
                namespace=namespace,
                parent_class="",
                base_classes=base_classes,
                usr=cursor.get_usr() if cursor.get_usr() else "",
                is_template=True,
                template_kind=symbol_kind,
                template_parameters=template_params,
                primary_template_usr=primary_usr,
                start_line=loc_info["start_line"],
                end_line=loc_info["end_line"],
                header_file=loc_info["header_file"],
                header_line=loc_info["header_line"],
                header_start_line=loc_info["header_start_line"],
                header_end_line=loc_info["header_end_line"],
                is_definition=cursor.is_definition(),
                brief=doc_info["brief"],
                doc_comment=doc_info["doc_comment"],
            )
            symbols_buffer.append(info)

        for child in cursor.get_children():
            self._process_cursor(
                child,
                should_extract_from_file,
                cursor.spelling if should_extract else parent_class,
                parent_function_usr,
            )

    def _handle_class_cursor(
        self,
        cursor: Any,
        should_extract: bool,
        should_extract_from_file: Optional[Callable[[str], bool]],
        parent_class: str,
        parent_function_usr: str,
    ) -> None:
        """Process classes and structs."""
        symbols_buffer = self._symbols_buffer
        kind = cursor.kind

        if cursor.spelling and should_extract:
            common = self._get_common_symbol_data(cursor)
            qualified_name = common["qualified_name"]
            namespace = common["namespace"]
            loc_info = common["loc_info"]
            doc_info = common["doc_info"]

            base_classes = self._get_base_classes(cursor)
            is_class_template_spec = self._detect_template_specialization(cursor)

            primary_usr = None
            stored_template_args = None
            if is_class_template_spec:
                primary_usr = self._get_primary_template_usr(cursor)
                if not base_classes and primary_usr:
                    base_classes = self._resolve_instantiation_base_classes(cursor, primary_usr)
                    if not base_classes:
                        targs = TemplateResolver.extract_args_from_displayname(cursor.displayname)
                        if targs:
                            stored_template_args = json.dumps(targs)

            info = SymbolInfo(
                name=cursor.spelling,
                kind="class" if kind == CursorKind.CLASS_DECL else "struct",
                file=loc_info["file"],
                line=loc_info["line"],
                column=loc_info["column"],
                qualified_name=qualified_name,
                is_project=(self._is_project_file(loc_info["file"]) if loc_info["file"] else False),
                namespace=namespace,
                parent_class="",
                base_classes=base_classes,
                usr=cursor.get_usr() if cursor.get_usr() else "",
                is_template_specialization=is_class_template_spec,
                is_template=is_class_template_spec,
                template_kind="full_specialization" if is_class_template_spec else None,
                primary_template_usr=primary_usr,
                template_arguments=stored_template_args,
                start_line=loc_info["start_line"],
                end_line=loc_info["end_line"],
                header_file=loc_info["header_file"],
                header_line=loc_info["header_line"],
                header_start_line=loc_info["header_start_line"],
                header_end_line=loc_info["header_end_line"],
                is_definition=cursor.is_definition(),
                brief=doc_info["brief"],
                doc_comment=doc_info["doc_comment"],
            )
            symbols_buffer.append(info)

        for child in cursor.get_children():
            self._process_cursor(
                child,
                should_extract_from_file,
                cursor.spelling if should_extract else parent_class,
                parent_function_usr,
            )

    def _handle_function_template_cursor(
        self,
        cursor: Any,
        should_extract: bool,
        should_extract_from_file: Optional[Callable[[str], bool]],
        parent_class: str,
        parent_function_usr: str,
    ) -> None:
        """Process template functions."""
        symbols_buffer = self._symbols_buffer
        if cursor.spelling and should_extract:
            common = self._get_common_symbol_data(cursor)
            qualified_name = common["qualified_name"]
            namespace = common["namespace"]
            loc_info = common["loc_info"]
            doc_info = common["doc_info"]

            signature = build_human_readable_signature(cursor)
            function_usr = cursor.get_usr() if cursor.get_usr() else ""
            template_params = self._extract_template_parameters(cursor)

            effective_parent_class = parent_class
            if not parent_class:
                sem_parent = cursor.semantic_parent
                if sem_parent and sem_parent.kind in (
                    CursorKind.CLASS_DECL,
                    CursorKind.STRUCT_DECL,
                    CursorKind.CLASS_TEMPLATE,
                ):
                    effective_parent_class = sem_parent.spelling

            is_method_template = bool(effective_parent_class)
            is_virtual = cursor.is_virtual_method() if is_method_template else False
            is_pure_virtual = cursor.is_pure_virtual_method() if is_method_template else False
            is_const = cursor.is_const_method() if is_method_template else False
            is_static = cursor.is_static_method()
            access_spec = cursor.access_specifier
            access = access_spec.name.lower() if access_spec else "public"
            if access in ("none", "invalid"):
                access = "public"

            info = SymbolInfo(
                name=cursor.spelling,
                kind="function_template",
                file=loc_info["file"],
                line=loc_info["line"],
                column=loc_info["column"],
                qualified_name=qualified_name,
                signature=signature,
                is_project=(self._is_project_file(loc_info["file"]) if loc_info["file"] else False),
                namespace=namespace,
                access=access,
                parent_class=effective_parent_class,
                usr=function_usr,
                is_template_specialization=False,
                is_template=True,
                template_kind="function_template",
                template_parameters=template_params,
                start_line=loc_info["start_line"],
                end_line=loc_info["end_line"],
                header_file=loc_info["header_file"],
                header_line=loc_info["header_line"],
                header_start_line=loc_info["header_start_line"],
                header_end_line=loc_info["header_end_line"],
                is_virtual=is_virtual,
                is_pure_virtual=is_pure_virtual,
                is_const=is_const,
                is_static=is_static,
                is_definition=cursor.is_definition(),
                brief=doc_info["brief"],
                doc_comment=doc_info["doc_comment"],
            )
            symbols_buffer.append(info)

        for child in cursor.get_children():
            self._process_cursor(
                child,
                should_extract_from_file,
                parent_class,
                cursor.get_usr() if cursor.get_usr() else parent_function_usr,
            )

    def _handle_function_cursor(
        self,
        cursor: Any,
        should_extract: bool,
        should_extract_from_file: Optional[Callable[[str], bool]],
        parent_class: str,
        parent_function_usr: str,
    ) -> None:
        """Process functions and methods."""
        symbols_buffer = self._symbols_buffer
        kind = cursor.kind
        if cursor.spelling and should_extract:
            common = self._get_common_symbol_data(cursor)
            qualified_name = common["qualified_name"]
            namespace = common["namespace"]
            loc_info = common["loc_info"]
            doc_info = common["doc_info"]

            signature = build_human_readable_signature(cursor)
            function_usr = cursor.get_usr() if cursor.get_usr() else ""
            is_template_spec = self._detect_template_specialization(cursor)
            primary_usr = self._get_primary_template_usr(cursor) if is_template_spec else None

            is_method = kind in (
                CursorKind.CXX_METHOD,
                CursorKind.CONSTRUCTOR,
                CursorKind.DESTRUCTOR,
                CursorKind.CONVERSION_FUNCTION,
            )
            is_virtual = cursor.is_virtual_method() if is_method else False
            is_pure_virtual = cursor.is_pure_virtual_method() if is_method else False
            is_const = cursor.is_const_method() if is_method else False
            is_static = cursor.is_static_method()
            access_spec = cursor.access_specifier
            access = access_spec.name.lower() if access_spec else "public"
            if access in ("none", "invalid"):
                access = "public"

            effective_parent_class = parent_class
            if is_method and not parent_class:
                sem_parent = cursor.semantic_parent
                if sem_parent and sem_parent.kind in (
                    CursorKind.CLASS_DECL,
                    CursorKind.STRUCT_DECL,
                    CursorKind.CLASS_TEMPLATE,
                ):
                    effective_parent_class = sem_parent.spelling

            info = SymbolInfo(
                name=cursor.spelling,
                kind="function" if kind == CursorKind.FUNCTION_DECL else "method",
                file=loc_info["file"],
                line=loc_info["line"],
                column=loc_info["column"],
                qualified_name=qualified_name,
                signature=signature,
                is_project=(self._is_project_file(loc_info["file"]) if loc_info["file"] else False),
                namespace=namespace,
                access=access,
                parent_class=effective_parent_class if is_method else "",
                usr=function_usr,
                is_template_specialization=is_template_spec,
                is_template=is_template_spec,
                template_kind="full_specialization" if is_template_spec else None,
                primary_template_usr=primary_usr,
                start_line=loc_info["start_line"],
                end_line=loc_info["end_line"],
                header_file=loc_info["header_file"],
                header_line=loc_info["header_line"],
                header_start_line=loc_info["header_start_line"],
                header_end_line=loc_info["header_end_line"],
                is_virtual=is_virtual,
                is_pure_virtual=is_pure_virtual,
                is_const=is_const,
                is_static=is_static,
                is_definition=cursor.is_definition(),
                brief=doc_info["brief"],
                doc_comment=doc_info["doc_comment"],
            )
            symbols_buffer.append(info)

        current_function_usr = (
            cursor.get_usr() if (should_extract and cursor.get_usr()) else parent_function_usr
        )
        for child in cursor.get_children():
            self._process_cursor(
                child, should_extract_from_file, parent_class, current_function_usr
            )

    def _handle_type_alias_cursor(
        self,
        cursor: Any,
        should_extract: bool,
        should_extract_from_file: Optional[Callable[[str], bool]],
        parent_class: str,
        parent_function_usr: str,
    ) -> None:
        """Process type aliases."""
        aliases_buffer = self._aliases_buffer
        kind = cursor.kind
        if cursor.spelling and should_extract:
            try:
                alias_info = extract_alias_info(cursor)
                aliases_buffer.append(alias_info)
            except Exception as e:
                diagnostics.warning(
                    f"Failed to extract alias info for {cursor.spelling} at "
                    f"{cursor.location.file.name if cursor.location.file else 'unknown'}:"
                    f"{cursor.location.line}: {e}"
                )

        if kind != CursorKind.TYPE_ALIAS_TEMPLATE_DECL:
            for child in cursor.get_children():
                self._process_cursor(
                    child, should_extract_from_file, parent_class, parent_function_usr
                )

    def _extract_template_call_info(
        self, referenced: Any, called_usr: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Extract display_name and project-type template args from a template call."""
        try:
            num_args = referenced.get_num_template_arguments()
            if num_args <= 0:
                return (None, None)

            project_types = []
            all_type_names = []
            for idx in range(num_args):
                arg_type = referenced.get_template_argument_type(idx)
                if arg_type is None or arg_type.spelling == "":
                    continue
                type_name = arg_type.spelling
                all_type_names.append(type_name)
                decl = arg_type.get_declaration()
                if decl and decl.location and decl.location.file:
                    if self._is_project_file(decl.location.file.name):
                        project_types.append(type_name)

            if not project_types:
                return (None, None)

            base_name = usr_to_display_name(called_usr)
            display_name = f"{base_name}<{', '.join(all_type_names)}>"
            return (display_name, json.dumps(project_types))
        except Exception:
            return (None, None)

    def _handle_call_cursor(self, cursor: Any, parent_function_usr: str) -> None:
        """Process function calls within function bodies."""
        calls_buffer = self._calls_buffer
        referenced = cursor.referenced
        if referenced and referenced.get_usr():
            called_usr = referenced.get_usr()
            from clang import cindex

            display_name = None
            template_project_types = None

            try:
                template_cursor = cindex.conf.lib.clang_getSpecializedCursorTemplate(referenced)
                if template_cursor and not template_cursor.kind.is_invalid():
                    template_usr = template_cursor.get_usr()
                    if template_usr:
                        display_name, template_project_types = self._extract_template_call_info(
                            referenced, template_usr
                        )
                        called_usr = template_usr

                        if display_name and cursor.spelling:
                            base_before_template = display_name.split("<", 1)[0]
                            source_name = cursor.spelling
                            last_component = base_before_template.rsplit("::", 1)[-1]
                            if last_component and last_component != source_name:
                                template_args = display_name.split("<", 1)[1]
                                ns_parts = base_before_template.rsplit("::", 1)
                                if len(ns_parts) == 2:
                                    new_base = f"{ns_parts[0]}::{source_name}"
                                else:
                                    new_base = source_name
                                display_name = f"{new_base}<{template_args}"
            except Exception:
                pass

            location = cursor.location
            calls_buffer.append(
                (
                    parent_function_usr,
                    called_usr,
                    location.file.name if location.file else None,
                    location.line if location.line else None,
                    location.column if location.column else None,
                    display_name,
                    template_project_types,
                )
            )

    def parse(
        self,
        tu: Any,
        source_file: str,
        should_extract_from_file: Optional[Callable[[str], bool]] = None,
    ) -> ParseResult:
        """Parse a translation unit and return extracted symbol data."""
        self._symbols_buffer = []
        self._calls_buffer = []
        self._aliases_buffer = []
        processed_headers: Dict[str, str] = {}

        def _wrapped_should_extract(file_path: str) -> bool:
            if file_path == source_file:
                return True
            if should_extract_from_file is None:
                return True
            extract = should_extract_from_file(file_path)
            if extract and file_path != source_file:
                try:
                    processed_headers[file_path] = self._get_file_hash(file_path)
                except Exception as e:
                    diagnostics.warning(f"Could not hash processed header {file_path}: {e}")
            return extract

        self._process_cursor(tu.cursor, _wrapped_should_extract)

        return ParseResult(
            symbols=self._symbols_buffer,
            call_sites=self._calls_buffer,
            type_aliases=self._aliases_buffer,
            processed_headers=processed_headers,
        )
