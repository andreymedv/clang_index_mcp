import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from clang.cindex import CursorKind

from . import diagnostics
from .symbol_info import SymbolInfo

# ---------------------------------------------------------------------------
# USR → human-readable qualified name conversion
# ---------------------------------------------------------------------------
_USR_TYPE_CODES: Dict[str, str] = {
    "v": "void",
    "b": "bool",
    "c": "char",
    "a": "signed char",
    "h": "unsigned char",
    "w": "wchar_t",
    "s": "short",
    "i": "int",
    "I": "unsigned int",
    "j": "long",
    "k": "unsigned long",
    "l": "long long",
    "m": "unsigned long long",
    "f": "float",
    "d": "double",
    "e": "long double",
    "D": "auto",
}

_TPARAM_LETTERS = "TUVWXYZABCDE"


def _decode_template_param(s: str, pos: int) -> tuple:
    m = re.match(r"t(\d+)\.(\d+)", s[pos:])
    if m:
        depth = int(m.group(1))
        idx = int(m.group(2))
        total_idx = depth * 4 + idx
        letter = _TPARAM_LETTERS[total_idx] if total_idx < len(_TPARAM_LETTERS) else f"T{total_idx}"
        return (letter, pos + m.end())
    return ("unsigned short", pos + 1)


def _decode_pointer_or_reference(s: str, pos: int, ch: str) -> tuple:
    suffix = " &&" if ch == "O" else f" {ch}"
    inner, npos = _decode_usr_type(s, pos)
    return (f"{inner}{suffix}", npos)


def _decode_cv_qualified(s: str, pos: int, ch: str) -> tuple:
    prefix = "volatile " if ch in ("V", "2") else "const "
    inner, npos = _decode_usr_type(s, pos)
    return (f"{prefix}{inner}", npos)


def _try_decode_substitution(s: str, pos: int) -> Optional[tuple]:
    if s[pos] != "S" or pos + 1 >= len(s):
        return None
    if not (s[pos + 1].isdigit() or s[pos + 1] == "_"):
        return None
    end = pos + 1
    while end < len(s) and (s[end].isdigit() or s[end] == "_"):
        end += 1
    return ("type", end)


def _decode_usr_type(s: str, pos: int) -> tuple:
    if pos >= len(s):
        return ("?", pos)

    ch = s[pos]

    if ch == "t":
        return _decode_template_param(s, pos)

    if ch in _USR_TYPE_CODES:
        return (_USR_TYPE_CODES[ch], pos + 1)

    if ch in ("*", "&", "O"):
        return _decode_pointer_or_reference(s, pos + 1, ch)

    if ch in ("K", "1", "V", "2"):
        return _decode_cv_qualified(s, pos + 1, ch)

    if ch == "$":
        return _decode_class_ref(s, pos + 1)

    sub = _try_decode_substitution(s, pos)
    if sub is not None:
        return sub

    return ("?", pos + 1)


def _decode_class_ref(s: str, pos: int) -> tuple:
    parts: List[str] = []
    i = pos
    while i < len(s):
        if s[i] != "@":
            break
        if i + 2 >= len(s):
            break
        kind = s[i + 1]
        if s[i + 2] != "@":
            break
        name_start = i + 3
        name_end = name_start
        while name_end < len(s) and s[name_end] not in ("@", "#", ">"):
            name_end += 1
        if name_end == name_start:
            break
        parts.append(s[name_start:name_end])
        i = name_end

        if kind in ("S", "C") and i < len(s) and s[i] == ">":
            if i + 1 < len(s) and s[i + 1] == "#":
                targs, i = _decode_template_args(s, i + 2)
                parts[-1] += targs
            else:
                i += 1
    name = "::".join(parts)
    return (name if name else "?", i)


def _decode_template_args(s: str, pos: int) -> tuple:
    args: List[str] = []
    i = pos
    while i < len(s):
        ch = s[i]
        if ch == "@":
            break
        if ch == "#":
            i += 1
            continue
        arg, i = _decode_usr_type(s, i)
        args.append(arg)
    if not args:
        return ("", i)
    return (f"<{', '.join(args)}>", i)


def _parse_template_definition(s: str, i: int, parts: List[str]) -> int:
    mt = re.match(r"@(ST|SP)>", s[i:])
    if not mt:
        return -1

    kind = mt.group(1)
    j = i + mt.end()
    inner_m = re.search(r"@([^@#>]+)", s[j:])
    if inner_m:
        raw_name = inner_m.group(1)
        name_only = re.match(r"([A-Za-z_]\w*?)(?=\d+t\d|\d*$)", raw_name)
        parts.append(name_only.group(1) if name_only else raw_name)
        new_i = j + inner_m.end()
        if kind == "SP" and new_i < len(s) and s[new_i] == ">":
            if new_i + 1 < len(s) and s[new_i + 1] == "#":
                targs, new_i = _decode_template_args(s, new_i + 2)
                parts[-1] += targs
            else:
                new_i += 1
        return new_i
    return j


def _skip_template_parameters(s: str, k: int, param_count: int) -> int:
    for _ in range(param_count):
        if k < len(s) and s[k] == "#":
            k += 1
            if k < len(s) and s[k] == "p":
                k += 1
            if k < len(s) and s[k] in ("T", "t"):
                k += 1
            elif k < len(s) and s[k] == "N":
                k += 1
                _, k = _decode_usr_type(s, k)
    return k


def _parse_function_template(s: str, i: int, parts: List[str]) -> int:
    if not s[i:].startswith("@FT@"):
        return -1

    j = i + 4
    if j < len(s) and s[j] == ">":
        j += 1

    bare_name = None
    count_m = re.match(r"(\d+)", s[j:])
    if count_m:
        param_count = int(count_m.group(1))
        k = j + count_m.end()
        k = _skip_template_parameters(s, k, param_count)
        name_m = re.match(r"([A-Za-z_]\w*)", s[k:])
        if name_m:
            bare_name = name_m.group(1)

    if bare_name is not None:
        parts.append(bare_name)
        return len(s)
    else:
        inner_m = re.search(r"@([A-Za-z])@([^@#>]+)", s[j:])
        if inner_m:
            return j + inner_m.start()
        return j


def _parse_regular_segment(s: str, i: int, parts: List[str]) -> int:
    m = re.match(r"@([A-Za-z])@", s[i:])
    if not m:
        return i + 1

    kind = m.group(1)
    name_start = i + m.end()
    name_end = name_start
    while name_end < len(s) and s[name_end] not in ("@", "#", ">"):
        name_end += 1

    if name_end == name_start:
        return name_start

    name = s[name_start:name_end]
    parts.append(name)
    new_i = name_end

    if kind in ("S", "C") and new_i < len(s) and s[new_i] == ">":
        if new_i + 1 < len(s) and s[new_i + 1] == "#":
            targs, new_i = _decode_template_args(s, new_i + 2)
            parts[-1] += targs
        else:
            new_i += 1

    if kind in ("F", "f") and new_i < len(s) and s[new_i] == "#":
        while new_i < len(s) and s[new_i] != "@":
            new_i += 1

    return new_i


def _usr_to_display_name(usr: str) -> str:
    if not usr:
        return usr

    s = usr[2:] if usr.startswith("c:") else usr
    parts: List[str] = []
    i = 0

    while i < len(s):
        next_i = _parse_template_definition(s, i, parts)
        if next_i != -1:
            i = next_i
            continue
        next_i = _parse_function_template(s, i, parts)
        if next_i != -1:
            i = next_i
            continue
        i = _parse_regular_segment(s, i, parts)

    return "::".join(parts) if parts else usr


class SymbolExtractor:
    """
    Handles AST traversal and symbol extraction from libclang cursors.
    """

    def __init__(self, analyzer: Any):
        """
        Initialize SymbolExtractor.

        Args:
            analyzer: Reference to the CppAnalyzer instance for access to indexes and config.
        """
        self.analyzer = analyzer

    @staticmethod
    def _get_qualified_name(cursor: Any) -> str:
        """Build fully qualified name by walking up semantic parent chain."""
        parts = []
        current = cursor
        max_depth = 100
        depth = 0
        visited = set()

        while current and depth < max_depth:
            cursor_id = id(current)
            if cursor_id in visited:
                diagnostics.warning(
                    f"Circular reference detected in semantic parent chain for {cursor.spelling}"
                )
                break
            visited.add(cursor_id)

            if current.kind == CursorKind.TRANSLATION_UNIT:
                break

            if current.spelling:
                parts.append(current.spelling)
            elif current.kind == CursorKind.NAMESPACE and current.is_anonymous():
                parts.append("(anonymous namespace)")

            current = current.semantic_parent
            depth += 1

        if depth >= max_depth:
            diagnostics.warning(
                f"Maximum depth ({max_depth}) exceeded when building qualified name for {cursor.spelling}"
            )

        parts.reverse()
        return "::".join(parts) if parts else cursor.spelling

    @staticmethod
    def _extract_namespace(qualified_name: str) -> str:
        """Extract namespace portion from qualified name."""
        if "::" not in qualified_name:
            return ""

        parts = qualified_name.split("::")
        return "::".join(parts[:-1])

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

    @staticmethod
    def _extract_template_args_from_displayname(displayname: str) -> List[str]:
        """Extract template arguments from a displayname like 'MyTemplate<Arg1, Arg2>'."""
        if "<" not in displayname:
            return []

        args_start = displayname.find("<")
        args_end = displayname.rfind(">")
        if args_start >= args_end:
            return []

        args_str = displayname[args_start + 1 : args_end]

        template_args: List[str] = []
        depth = 0
        current = ""
        for c in args_str:
            if c == "<":
                depth += 1
                current += c
            elif c == ">":
                depth -= 1
                current += c
            elif c == "," and depth == 0:
                template_args.append(current.strip())
                current = ""
            else:
                current += c
        if current.strip():
            template_args.append(current.strip())

        return template_args

    def _build_param_to_arg_mapping(
        self, template_params: List[Dict[str, Any]], template_args: List[str]
    ) -> Dict[str, str]:
        """Build mapping from template parameter names to template arguments."""
        param_to_arg = {}
        for i, param in enumerate(template_params):
            if i < len(template_args):
                param_name = param.get("name", "")
                if param_name:
                    param_to_arg[param_name] = template_args[i]
        return param_to_arg

    def _substitute_template_args_in_bases(
        self,
        base_classes: List[str],
        param_to_arg: Dict[str, str],
        template_args: List[str],
    ) -> List[str]:
        """Resolve base classes by substituting parameter names with actual arguments."""
        resolved = []
        for base in base_classes:
            if base in param_to_arg:
                resolved.append(param_to_arg[base])
            else:
                match = re.match(r"type-parameter-(\d+)-(\d+)", base)
                if match:
                    param_index = int(match.group(2))
                    if param_index < len(template_args):
                        resolved.append(template_args[param_index])
                else:
                    resolved.append(base)
        return resolved

    def _find_primary_template_info(self, primary_template_usr: str) -> Optional[Any]:
        """Look up the primary template in class_index by USR."""
        with self.analyzer.index_lock:
            for name, infos in self.analyzer.class_index.items():
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

        template_args = self._extract_template_args_from_displayname(cursor.displayname)
        if not template_args:
            return []

        primary_info = self._find_primary_template_info(primary_template_usr)
        if not primary_info:
            return []

        template_params = self._parse_template_params(primary_info)
        if not template_params:
            return []

        param_to_arg = self._build_param_to_arg_mapping(template_params, template_args)

        return self._substitute_template_args_in_bases(
            primary_info.base_classes, param_to_arg, template_args
        )

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

        primary_info = self.analyzer.usr_index.get(info.primary_template_usr)
        if not primary_info:
            return False

        template_params = self._parse_json_field(primary_info.template_parameters)
        if not template_params:
            return False

        param_to_arg = self._build_param_to_arg_mapping(template_params, template_args)

        resolved = self._substitute_template_args_in_bases(
            primary_info.base_classes, param_to_arg, template_args
        )

        if resolved:
            info.base_classes = resolved
            info.template_arguments = None
            diagnostics.debug(f"Deferred resolution: {info.qualified_name} -> bases={resolved}")
            return True
        return False

    def _resolve_deferred_instantiation_bases(self) -> int:
        """Resolve base_classes for template instantiations that couldn't be resolved during parsing."""
        resolved_count = 0
        for name, infos in self.analyzer.class_index.items():
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
        primary_file = SymbolExtractor._get_primary_file(cursor)
        start_line, end_line = SymbolExtractor._extract_cursor_extent(cursor, location)

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

        SymbolExtractor._extract_definition_location(cursor, result)

        return result

    @staticmethod
    def _extract_brief_comment(cursor: Any) -> Optional[str]:
        """Extract and truncate brief comment from cursor."""
        brief_comment = cursor.brief_comment
        if not brief_comment:
            return None
        brief = str(brief_comment).strip()
        if len(brief) > 200:
            brief = brief[:200]
        return brief

    @staticmethod
    def _extract_raw_doc_comment(cursor: Any) -> Optional[str]:
        """Extract and truncate full documentation comment from cursor."""
        raw_comment = cursor.raw_comment
        if not raw_comment:
            return None
        doc_comment = str(raw_comment).strip()
        if len(doc_comment) > 4000:
            doc_comment = doc_comment[:3997] + "..."
        return doc_comment

    @staticmethod
    def _extract_brief_from_doc(doc_comment: str) -> Optional[str]:
        """Extract first meaningful line from a documentation comment."""
        for line in doc_comment.split("\n"):
            cleaned = line.strip().lstrip("/*!/").lstrip("*").strip()
            if cleaned and not cleaned.startswith("@"):
                if len(cleaned) > 200:
                    cleaned = cleaned[:200]
                return cleaned
        return None

    @staticmethod
    def _extract_documentation(cursor: Any) -> dict:
        """Extract documentation from cursor comments."""
        result: Dict[str, Optional[str]] = {"brief": None, "doc_comment": None}

        try:
            result["brief"] = SymbolExtractor._extract_brief_comment(cursor)

            doc_comment = SymbolExtractor._extract_raw_doc_comment(cursor)
            if doc_comment:
                result["doc_comment"] = doc_comment
                if not result["brief"]:
                    result["brief"] = SymbolExtractor._extract_brief_from_doc(doc_comment)

        except Exception as e:
            diagnostics.debug(f"Could not extract documentation for {cursor.spelling}: {e}")

        return result

    @staticmethod
    def _get_type_spelling(cursor: Any):
        """Safely get cursor.type.spelling, returning None if unavailable."""
        if not cursor.type:
            return None
        return cursor.type.spelling or None

    @staticmethod
    def _get_return_type(cursor: Any) -> str:
        """Safely get cursor.result_type.spelling."""
        try:
            if cursor.result_type and cursor.result_type.spelling:
                return str(cursor.result_type.spelling)
        except Exception:
            pass
        return ""

    @staticmethod
    def _format_args(args: List[Any]) -> str:
        """Format a list of cursor arguments into a parameter string."""
        param_parts = []
        for arg in args:
            arg_type = arg.type.spelling if arg.type else ""
            arg_name = arg.spelling or ""
            if arg_name:
                param_parts.append(f"{arg_type} {arg_name}")
            else:
                param_parts.append(arg_type)
        return ", ".join(param_parts)

    @staticmethod
    def _extract_params_from_type_spelling(type_spelling: str) -> str:
        """Extract parameter types from a C function type spelling string."""
        if not type_spelling:
            return ""

        depth = 0
        start = -1
        for i, ch in enumerate(type_spelling):
            if ch == "(":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and start >= 0:
                    return type_spelling[start + 1 : i]

        return ""

    @staticmethod
    def _extract_trailing_qualifiers(type_spelling: str) -> str:
        """Extract trailing qualifiers from type spelling."""
        if not type_spelling:
            return ""

        depth = 0
        last_close = -1
        for i, ch in enumerate(type_spelling):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    last_close = i

        if last_close >= 0 and last_close < len(type_spelling) - 1:
            qualifiers = type_spelling[last_close + 1 :]
            return qualifiers

        return ""

    @staticmethod
    def _assemble_signature(return_type: str, name: str, params_str: str, qualifiers: str) -> str:
        """Assemble the final human-readable signature string."""
        if return_type:
            return f"{return_type} {name}({params_str}){qualifiers}"
        return f"{name}({params_str}){qualifiers}"

    @staticmethod
    def _fallback_signature(cursor: Any) -> str:
        """Return cursor.type.spelling as a fallback, or empty string on failure."""
        try:
            return cursor.type.spelling if cursor.type else ""
        except Exception:
            return ""

    def _get_params_str(self, cursor: Any, type_spelling: str) -> str:
        """Get parameter string from cursor arguments or type spelling fallback."""
        try:
            args = list(cursor.get_arguments())
            if args:
                return self._format_args(args)
            return self._extract_params_from_type_spelling(type_spelling)
        except Exception:
            return self._extract_params_from_type_spelling(type_spelling)

    def _try_build_human_readable_signature(self, cursor: Any) -> str:
        """Attempt to build signature without exception handling."""
        type_spelling = self._get_type_spelling(cursor)
        if type_spelling is None:
            return ""

        name = cursor.spelling or ""
        return_type = self._get_return_type(cursor)
        params_str = self._get_params_str(cursor, type_spelling)
        qualifiers = self._extract_trailing_qualifiers(type_spelling)

        return self._assemble_signature(return_type, name, params_str, qualifiers)

    def _build_human_readable_signature(self, cursor: Any) -> str:
        """Build a human-readable function signature from a libclang cursor."""
        try:
            return self._try_build_human_readable_signature(cursor)
        except Exception as e:
            diagnostics.debug(
                f"Could not build human-readable signature for " f"{cursor.spelling}: {e}"
            )
            return self._fallback_signature(cursor)

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

    def _extract_template_alias_info(
        self, cursor: Any
    ) -> Tuple[str, str, str, str, str, int, int, List[dict]]:
        """Extract alias info from a TYPE_ALIAS_TEMPLATE_DECL cursor."""
        template_params = []
        type_alias_decl = None

        for child in cursor.get_children():
            if child.kind == CursorKind.TEMPLATE_TYPE_PARAMETER:
                template_params.append({"name": child.spelling, "kind": "type"})
            elif child.kind == CursorKind.TEMPLATE_NON_TYPE_PARAMETER:
                template_params.append(
                    {"name": child.spelling, "kind": "non_type", "type": child.type.spelling}
                )
            elif child.kind == CursorKind.TYPE_ALIAS_DECL:
                type_alias_decl = child

        if type_alias_decl:
            alias_name = type_alias_decl.spelling
            qualified_name = self._get_qualified_name(type_alias_decl)

            try:
                underlying_type = type_alias_decl.underlying_typedef_type
                target_type = underlying_type.spelling
                canonical_type = underlying_type.get_canonical().spelling
            except AttributeError:
                target_type = type_alias_decl.type.spelling
                canonical_type = type_alias_decl.type.get_canonical().spelling
        else:
            alias_name = cursor.spelling
            qualified_name = self._get_qualified_name(cursor)
            target_type = ""
            canonical_type = ""

        file_path = str(cursor.location.file.name) if cursor.location.file else ""
        line = cursor.location.line
        column = cursor.location.column

        return (
            alias_name,
            qualified_name,
            target_type,
            canonical_type,
            file_path,
            line,
            column,
            template_params,
        )

    def _extract_simple_alias_info(
        self, cursor: Any
    ) -> Tuple[str, str, str, str, str, int, int, str]:
        """Extract alias info from a TYPEDEF_DECL or TYPE_ALIAS_DECL cursor."""
        alias_name = cursor.spelling
        qualified_name = self._get_qualified_name(cursor)

        try:
            underlying_type = cursor.underlying_typedef_type
            target_type = underlying_type.spelling
            canonical_type = underlying_type.get_canonical().spelling
        except AttributeError:
            target_type = cursor.type.spelling
            canonical_type = cursor.type.get_canonical().spelling

        if cursor.kind == CursorKind.TYPE_ALIAS_DECL:
            alias_kind = "using"
        elif cursor.kind == CursorKind.TYPEDEF_DECL:
            alias_kind = "typedef"
        else:
            alias_kind = "unknown"

        file_path = str(cursor.location.file.name) if cursor.location.file else ""
        line = cursor.location.line
        column = cursor.location.column

        return (
            alias_name,
            qualified_name,
            target_type,
            canonical_type,
            file_path,
            line,
            column,
            alias_kind,
        )

    def _extract_alias_info(self, cursor: Any) -> dict:
        """Extract type alias information from TYPEDEF_DECL, TYPE_ALIAS_DECL, or TYPE_ALIAS_TEMPLATE_DECL cursor."""
        is_template_alias = cursor.kind == CursorKind.TYPE_ALIAS_TEMPLATE_DECL

        if is_template_alias:
            (
                alias_name,
                qualified_name,
                target_type,
                canonical_type,
                file_path,
                line,
                column,
                template_params,
            ) = self._extract_template_alias_info(cursor)
            alias_kind = "using"
        else:
            (
                alias_name,
                qualified_name,
                target_type,
                canonical_type,
                file_path,
                line,
                column,
                alias_kind,
            ) = self._extract_simple_alias_info(cursor)
            template_params = []

        namespace = self._extract_namespace(qualified_name)

        return {
            "alias_name": alias_name,
            "qualified_name": qualified_name,
            "target_type": target_type,
            "canonical_type": canonical_type,
            "file": file_path,
            "line": line,
            "column": column,
            "alias_kind": alias_kind,
            "namespace": namespace,
            "is_template_alias": is_template_alias,
            "template_params": json.dumps(template_params) if template_params else None,
            "created_at": time.time(),
        }

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
        qualified_name = self._get_qualified_name(cursor)
        return {
            "qualified_name": qualified_name,
            "namespace": self._extract_namespace(qualified_name),
            "loc_info": self._extract_line_range_info(cursor),
            "doc_info": self._extract_documentation(cursor),
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
        if kind in (CursorKind.CLASS_TEMPLATE, CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION):
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
        symbols_buffer, _, _ = self.analyzer._get_thread_local_buffers()
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
                is_project=(
                    self.analyzer._is_project_file(loc_info["file"]) if loc_info["file"] else False
                ),
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
        symbols_buffer, _, _ = self.analyzer._get_thread_local_buffers()
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
                        targs = self._extract_template_args_from_displayname(cursor.displayname)
                        if targs:
                            stored_template_args = json.dumps(targs)

            info = SymbolInfo(
                name=cursor.spelling,
                kind="class" if kind == CursorKind.CLASS_DECL else "struct",
                file=loc_info["file"],
                line=loc_info["line"],
                column=loc_info["column"],
                qualified_name=qualified_name,
                is_project=(
                    self.analyzer._is_project_file(loc_info["file"]) if loc_info["file"] else False
                ),
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
        symbols_buffer, _, _ = self.analyzer._get_thread_local_buffers()
        if cursor.spelling and should_extract:
            common = self._get_common_symbol_data(cursor)
            qualified_name = common["qualified_name"]
            namespace = common["namespace"]
            loc_info = common["loc_info"]
            doc_info = common["doc_info"]

            signature = self._build_human_readable_signature(cursor)
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
                is_project=(
                    self.analyzer._is_project_file(loc_info["file"]) if loc_info["file"] else False
                ),
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
        symbols_buffer, _, _ = self.analyzer._get_thread_local_buffers()
        kind = cursor.kind
        if cursor.spelling and should_extract:
            common = self._get_common_symbol_data(cursor)
            qualified_name = common["qualified_name"]
            namespace = common["namespace"]
            loc_info = common["loc_info"]
            doc_info = common["doc_info"]

            signature = self._build_human_readable_signature(cursor)
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
                is_project=(
                    self.analyzer._is_project_file(loc_info["file"]) if loc_info["file"] else False
                ),
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
        _, _, aliases_buffer = self.analyzer._get_thread_local_buffers()
        kind = cursor.kind
        if cursor.spelling and should_extract:
            try:
                alias_info = self._extract_alias_info(cursor)
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
                    if self.analyzer._is_project_file(decl.location.file.name):
                        project_types.append(type_name)

            if not project_types:
                return (None, None)

            base_name = _usr_to_display_name(called_usr)
            display_name = f"{base_name}<{', '.join(all_type_names)}>"
            return (display_name, json.dumps(project_types))
        except Exception:
            return (None, None)

    def _handle_call_cursor(self, cursor: Any, parent_function_usr: str) -> None:
        """Process function calls within function bodies."""
        _, calls_buffer, _ = self.analyzer._get_thread_local_buffers()
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

    def _should_extract_header(self, file_path: str) -> bool:
        """Check if a header file should be extracted based on project status and tracker."""
        if not self.analyzer._is_project_file(file_path):
            return False

        try:
            file_hash = self.analyzer._get_file_hash(file_path)
            return bool(self.analyzer.header_tracker.try_claim_header(file_path, file_hash))
        except Exception as e:
            diagnostics.warning(f"Error checking header {file_path}: {e}")
            return False

    def _finalize_header_status(self, headers_to_extract: Set[str]):
        """Mark successfully claimed headers as completed in the tracker."""
        for header in headers_to_extract:
            try:
                file_hash = self.analyzer._get_file_hash(header)
                self.analyzer.header_tracker.mark_completed(header, file_hash)
            except Exception as e:
                diagnostics.warning(f"Error marking header {header} as completed: {e}")

    def _update_dependency_graph(self, tu: Any, source_file: str):
        """Extract and update dependencies for the given translation unit."""
        if self.analyzer.dependency_graph is not None:
            try:
                includes = self.analyzer.dependency_graph.extract_includes_from_tu(tu, source_file)
                self.analyzer.dependency_graph.update_dependencies(source_file, includes)
            except Exception as e:
                diagnostics.warning(f"Failed to update dependencies for {source_file}: {e}")

    def _index_translation_unit(self, tu: Any, source_file: str) -> Dict[str, Any]:
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

        self.analyzer._init_thread_local_buffers()
        self._process_cursor(tu.cursor, should_extract_from_file)
        self.analyzer._bulk_write_symbols()

        self._finalize_header_status(headers_to_extract)
        self._update_dependency_graph(tu, source_file)

        return {
            "source_file": source_file,
            "processed": list(processed_files),
            "skipped": list(skipped_headers),
        }
