import logging
import re
from typing import Optional, Set

from sactor import rust_ast_parser


logger = logging.getLogger(__name__)

IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

NUMERIC_PRIMITIVES: set[str] = {
    "u8",
    "i8",
    "u16",
    "i16",
    "u32",
    "i32",
    "u64",
    "i64",
    "usize",
    "isize",
    "f32",
    "f64",
}

ALLOWED_LEN_WORDS = {"as"} | NUMERIC_PRIMITIVES

_C_LIB_TYPE_NAMES = {
    "c_char",
    "c_schar",
    "c_uchar",
    "c_short",
    "c_ushort",
    "c_int",
    "c_uint",
    "c_long",
    "c_ulong",
    "c_longlong",
    "c_ulonglong",
    "c_float",
    "c_double",
    "c_void",
}

def canonical_type_string(value: Optional[str]) -> str:
    if not isinstance(value, str):
        return ""
    stripped = value.strip()
    if not stripped:
        return ""
    try:
        traits = rust_ast_parser.parse_type_traits(stripped)
        normalized = traits.get("normalized")
        if isinstance(normalized, str) and normalized.strip():
            stripped = normalized.strip()
    except Exception as exc:
        logger.warning("parse_type_traits failed for type '%s': %s", value, exc)
    return " ".join(stripped.split())


_RAW_LIBC_SCALAR_TO_PRIMITIVE = {
    "libc::c_char": "u8",
    "libc::c_schar": "i8",
    "libc::c_uchar": "u8",
    "libc::c_int": "i32",
    "libc::c_uint": "u32",
    "libc::c_long": "isize",
    "libc::c_ulong": "usize",
    "libc::c_float": "f32",
    "libc::c_double": "f64",
}

LIBC_SCALAR_TO_PRIMITIVE = {
    canonical_type_string(key): value
    for key, value in _RAW_LIBC_SCALAR_TO_PRIMITIVE.items()
}

_RAW_SCALAR_CAST_OVERRIDES = set(_RAW_LIBC_SCALAR_TO_PRIMITIVE) - {
    "libc::c_char",
    "libc::c_schar",
    "libc::c_uchar",
}

SCALAR_CAST_OVERRIDES = {
    canonical_type_string(key) for key in _RAW_SCALAR_CAST_OVERRIDES
}

SCALAR_CAST_IDENTITY = {
    canonical_type_string(key) for key in {"i32", "u32", "f32", "f64"}
}

SCALAR_TYPES = {
    canonical_type_string(key)
    for key in {"i32", "u32", "i64", "u64", "f32", "f64", "usize", "isize"}
}


def _track_libc_name(name: Optional[str], acc: Set[str]) -> None:
    if not isinstance(name, str):
        return
    candidate = name.strip()
    if not candidate or "::" in candidate:
        return
    if candidate in _C_LIB_TYPE_NAMES:
        acc.add(candidate)


def _collect_libc_from_traits(traits: Optional[dict]) -> Set[str]:
    if not isinstance(traits, dict):
        return set()
    found: Set[str] = set()
    normalized = traits.get("normalized")
    _track_libc_name(normalized, found)

    path_ident = traits.get("path_ident")
    if isinstance(path_ident, str):
        if not (isinstance(normalized, str) and "::" in normalized):
            _track_libc_name(path_ident, found)
    _track_libc_name(traits.get("pointer_base_normalized"), found)

    for key in ("pointer_inner", "reference_inner", "option_inner", "box_inner"):
        inner = traits.get(key)
        if isinstance(inner, dict):
            found.update(_collect_libc_from_traits(inner))

    return found


def collect_libc_from_type(type_str: Optional[str]) -> Set[str]:
    if not isinstance(type_str, str) or not type_str.strip():
        return set()
    try:
        traits = rust_ast_parser.parse_type_traits(type_str)
    except Exception as exc:
        logger.warning("collect libc types: failed to parse '%s': %s", type_str, exc)
        return set()
    return _collect_libc_from_traits(traits)
