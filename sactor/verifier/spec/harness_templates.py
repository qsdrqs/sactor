from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).with_name("templates")


@lru_cache(maxsize=None)
def _get_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _normalize_lines(lines: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for entry in lines:
        if entry is None:
            continue
        stripped = str(entry)
        parts = stripped.splitlines()
        if not parts:
            normalized.append("")
            continue
        for part in parts:
            normalized.append(part)
    return tuple(normalized)


@dataclass(frozen=True)
class StructHarnessContext:
    """Template inputs for struct harness generation."""

    uses: tuple[str, ...]
    struct_name: str
    idiomatic_type: str
    c_struct_bind: str
    idiom_struct_bind: str
    pointer_asserts: tuple[str, ...]
    init_lines: tuple[str, ...]
    back_lines: tuple[str, ...]
    c_struct_init_lines: tuple[str, ...]

    @classmethod
    def create(
        cls,
        *,
        uses: Iterable[str],
        struct_name: str,
        idiomatic_type: str,
        c_struct_bind: str,
        idiom_struct_bind: str,
        pointer_asserts: Iterable[str],
        init_lines: Iterable[str],
        back_lines: Iterable[str],
        c_struct_init_lines: Iterable[str],
    ) -> "StructHarnessContext":
        return cls(
            uses=_normalize_lines(uses),
            struct_name=struct_name,
            idiomatic_type=idiomatic_type,
            c_struct_bind=c_struct_bind,
            idiom_struct_bind=idiom_struct_bind,
            pointer_asserts=_normalize_lines(pointer_asserts),
            init_lines=_normalize_lines(init_lines),
            back_lines=_normalize_lines(back_lines),
            c_struct_init_lines=_normalize_lines(c_struct_init_lines),
        )

    def as_template_args(self) -> dict[str, Any]:
        return {
            "uses": self.uses,
            "struct_name": self.struct_name,
            "idiomatic_type": self.idiomatic_type,
            "c_struct_bind": self.c_struct_bind,
            "idiom_struct_bind": self.idiom_struct_bind,
            "pointer_asserts": self.pointer_asserts,
            "init_lines": self.init_lines,
            "back_lines": self.back_lines,
            "c_struct_init_lines": self.c_struct_init_lines,
        }


@dataclass(frozen=True)
class EnumHarnessContext:
    """Template inputs for enum harness conversion helpers."""

    uses: tuple[str, ...]
    struct_name: str
    idiom_type: str
    tag_field: str
    to_rust_arms: tuple[dict[str, str], ...]
    variants: tuple[dict[str, Any], ...]

    @classmethod
    def create(
        cls,
        *,
        uses: Iterable[str],
        struct_name: str,
        idiom_type: str,
        tag_field: str,
        to_rust_arms: Iterable[dict[str, str]],
        variants: Iterable[dict[str, Any]],
    ) -> "EnumHarnessContext":
        normalized_arms: list[dict[str, str]] = []
        for arm in to_rust_arms or []:
            match_value = str(arm.get("match_value", ""))
            expression = str(arm.get("expression", ""))
            normalized_arms.append(
                {"match_value": match_value, "expression": expression})
        normalized_variants: list[dict[str, Any]] = []
        for variant in variants or []:
            pattern = str(variant.get("pattern", ""))
            temps = _normalize_lines(variant.get("temps", ()))
            struct_fields = _normalize_lines(variant.get("struct_fields", ()))
            normalized_variants.append(
                {
                    "pattern": pattern,
                    "temps": temps,
                    "struct_fields": struct_fields,
                }
            )
        return cls(
            uses=_normalize_lines(uses),
            struct_name=struct_name,
            idiom_type=idiom_type,
            tag_field=tag_field,
            to_rust_arms=tuple(normalized_arms),
            variants=tuple(normalized_variants),
        )

    def as_template_args(self) -> dict[str, Any]:
        return {
            "uses": self.uses,
            "struct_name": self.struct_name,
            "idiom_type": self.idiom_type,
            "tag_field": self.tag_field,
            "to_rust_arms": self.to_rust_arms,
            "variants": self.variants,
        }


def render_struct_harness(context: StructHarnessContext) -> str:
    template = _get_env().get_template("struct_harness.j2")
    return template.render(context.as_template_args())


def render_enum_struct_converters(context: EnumHarnessContext) -> str:
    template = _get_env().get_template("enum_harness.j2")
    return template.render(context.as_template_args())


@dataclass(frozen=True)
class FunctionHarnessContext:
    """Template inputs for function harness generation."""

    uses: tuple[str, ...]
    signature: str
    call_line: str
    pre_lines: tuple[str, ...]
    ret_lines: tuple[str, ...]
    post_lines: tuple[str, ...]
    return_line: tuple[str, ...]

    @classmethod
    def create(
        cls,
        *,
        uses: Sequence[str] | None = None,
        signature: str,
        call_line: str,
        pre_lines: Sequence[str],
        ret_lines: Sequence[str],
        post_lines: Sequence[str],
        return_line: Sequence[str] | None,
    ) -> "FunctionHarnessContext":
        normalized_return = _normalize_lines(return_line or ())
        return cls(
            uses=_normalize_lines(uses or ()),
            signature=signature,
            call_line=call_line,
            pre_lines=_normalize_lines(pre_lines),
            ret_lines=_normalize_lines(ret_lines),
            post_lines=_normalize_lines(post_lines),
            return_line=normalized_return,
        )

    def as_template_args(self) -> dict[str, Any]:
        return {
            "uses": self.uses,
            "signature": self.signature,
            "call_line": self.call_line,
            "pre_lines": self.pre_lines,
            "ret_lines": self.ret_lines,
            "post_lines": self.post_lines,
            "return_line": self.return_line,
        }


def render_function_harness(context: FunctionHarnessContext) -> str:
    template = _get_env().get_template("function_harness.j2")
    rendered = template.render(context.as_template_args())
    return rendered.rstrip("\n")


@lru_cache(maxsize=None)
def _get_function_macro_module():
    template = _get_env().get_template("function_macros.j2")
    return template.module


def render_function_macro(name: str, **params: Any) -> str:
    module = _get_function_macro_module()
    try:
        macro = getattr(module, name)
    except AttributeError as exc:
        raise ValueError(f"unknown function harness macro: {name}") from exc
    rendered = macro(**params)
    if not isinstance(rendered, str):
        raise TypeError(f"macro {name} did not return string")
    return rendered
