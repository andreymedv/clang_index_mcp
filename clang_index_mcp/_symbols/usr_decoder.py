"""USR → human-readable qualified name conversion.

This module is a pure-function extraction of the logic that turns clang USR
strings (e.g. ``c:@N@std@S@vector>#i``) into display names such as
``std::vector<int>``.  Keeping it separate from SymbolExtractor makes the
algorithm easier to test and reuse without pulling in AST traversal state.
"""

import re
from typing import Dict, List, Optional, Tuple

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


def _decode_template_param(s: str, pos: int) -> Tuple[str, int]:
    m = re.match(r"t(\d+)\.(\d+)", s[pos:])
    if m:
        depth = int(m.group(1))
        idx = int(m.group(2))
        total_idx = depth * 4 + idx
        letter = _TPARAM_LETTERS[total_idx] if total_idx < len(_TPARAM_LETTERS) else f"T{total_idx}"
        return (letter, pos + m.end())
    return ("unsigned short", pos + 1)


def _decode_pointer_or_reference(s: str, pos: int, ch: str) -> Tuple[str, int]:
    suffix = " &&" if ch == "O" else f" {ch}"
    inner, npos = _decode_usr_type(s, pos)
    return (f"{inner}{suffix}", npos)


def _decode_cv_qualified(s: str, pos: int, ch: str) -> Tuple[str, int]:
    prefix = "volatile " if ch in ("V", "2") else "const "
    inner, npos = _decode_usr_type(s, pos)
    return (f"{prefix}{inner}", npos)


def _try_decode_substitution(s: str, pos: int) -> Optional[Tuple[str, int]]:
    if s[pos] != "S" or pos + 1 >= len(s):
        return None
    if not (s[pos + 1].isdigit() or s[pos + 1] == "_"):
        return None
    end = pos + 1
    while end < len(s) and (s[end].isdigit() or s[end] == "_"):
        end += 1
    return ("type", end)


def _decode_usr_type(s: str, pos: int) -> Tuple[str, int]:
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


def _decode_class_ref(s: str, pos: int) -> Tuple[str, int]:
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


def _decode_template_args(s: str, pos: int) -> Tuple[str, int]:
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


def usr_to_display_name(usr: str) -> str:
    """Convert a clang USR string into a human-readable qualified name."""
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
