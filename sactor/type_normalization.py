"""Shared helpers for libc/type normalization across the codebase."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Dict, Iterable, Tuple


_RESOURCE_PACKAGE = "sactor._resources"
_RESOURCE_NAME = "libc_scalar_map.txt"


def _read_resource_text() -> str:
    try:
        resource = resources.files(_RESOURCE_PACKAGE).joinpath(_RESOURCE_NAME)
        with resource.open("r", encoding="utf-8") as handle:
            return handle.read()
    except (FileNotFoundError, ModuleNotFoundError):
        fallback = Path(__file__).resolve().parent / "_resources" / _RESOURCE_NAME
        with open(fallback, "r", encoding="utf-8") as handle:
            return handle.read()


@lru_cache(maxsize=1)
def _load_libc_scalar_pairs() -> Tuple[Tuple[str, str], ...]:
    text = _read_resource_text()
    pairs: list[Tuple[str, str]] = []

    for idx, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(
                f"Invalid entry in {_RESOURCE_NAME} on line {idx}: '{raw_line}'"
            )
        lhs, rhs = line.split("=", 1)
        lhs = lhs.strip()
        rhs = rhs.strip()
        if not lhs or not rhs:
            raise ValueError(
                f"Invalid entry in {_RESOURCE_NAME} on line {idx}: '{raw_line}'"
            )
        pairs.append((lhs, rhs))

    return tuple(pairs)


def get_libc_scalar_pairs() -> Tuple[Tuple[str, str], ...]:
    """Return the ordered libc scalar pairs as defined in the resource file."""

    return _load_libc_scalar_pairs()


def get_libc_scalar_map() -> Dict[str, str]:
    """Return a mapping of libc scalar aliases to Rust primitive types."""

    return dict(_load_libc_scalar_pairs())


def map_libc_scalar(name: str | None) -> str | None:
    """Map ``name`` (with or without the ``libc::`` prefix) to a primitive."""

    if not isinstance(name, str):
        return None
    candidate = name.strip()
    if not candidate:
        return None

    for full, target in _load_libc_scalar_pairs():
        if candidate == full:
            return target
        tail = full.split("::")[-1]
        if candidate == tail:
            return target
    return None


def iter_numeric_primitives() -> Iterable[str]:
    """Return the supported Rust numeric primitive aliases."""

    # Duplicates the order used by the Rust side for consistency.
    return (
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
    )
