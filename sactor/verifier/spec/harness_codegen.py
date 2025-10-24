import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from sactor import rust_ast_parser
from sactor.verifier.spec._type_utils import (ALLOWED_LEN_WORDS, IDENTIFIER_RE,
                                              LIBC_SCALAR_TO_PRIMITIVE,
                                              SCALAR_CAST_IDENTITY,
                                              SCALAR_CAST_OVERRIDES,
                                              SCALAR_TYPES,
                                              canonical_type_string,
                                              collect_libc_from_type)
from sactor.verifier.spec.harness_templates import (
    EnumHarnessContext, FunctionHarnessContext, StructHarnessContext,
    render_enum_struct_converters, render_function_harness,
    render_function_macro, render_struct_harness)

logger = logging.getLogger(__name__)

_TYPE_TRAITS_CACHE: dict[str, dict] = {}

_C_STRUCT_BIND = "c_struct"
_IDIOM_STRUCT_BIND = "idiom_struct"


def _build_function_use_lines(
    c_params: Sequence[dict],
    c_ret: Optional[dict],
) -> list[str]:
    libc_types: set[str] = set()

    for param in c_params:
        type_str = param.get("type") if isinstance(param, dict) else None
        libc_types.update(collect_libc_from_type(type_str))

    if isinstance(c_ret, dict):
        libc_types.update(collect_libc_from_type(c_ret.get("type")))

    if not libc_types:
        return []

    joined = ", ".join(sorted(libc_types))
    return [f"use std::os::raw::{{{joined}}};"]


@dataclass
class PointerInfo:
    kind: Optional[str] = None
    null: str = "empty"
    len_from: Any = None
    len_const: Optional[int] = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_shape(cls, shape: Any) -> Optional["PointerInfo"]:
        if not isinstance(shape, dict):
            return None
        ptr = shape.get("ptr")
        if not isinstance(ptr, dict):
            return None
        len_const = ptr.get("len_const")
        if isinstance(len_const, (int, float)):
            len_const_val: Optional[int] = int(len_const)
        else:
            len_const_val = None
        return cls(
            kind=ptr.get("kind"),
            null=ptr.get("null", "empty"),
            len_from=ptr.get("len_from"),
            len_const=len_const_val,
            raw=ptr,
        )

    @property
    def is_nullable(self) -> bool:
        return self.null in {"nullable", "none"}

    @property
    def is_forbidden(self) -> bool:
        return self.null == "forbidden"


@dataclass
class FieldDescriptor:
    name: str = ""
    type: str = ""
    raw_shape: Any = None

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "FieldDescriptor":
        if not isinstance(data, dict):
            data = {}
        return cls(
            name=data.get("name") or "",
            type=canonical_type_string(data.get("type")),
            raw_shape=data.get("shape"),
        )

    @property
    def is_scalar(self) -> bool:
        return isinstance(self.raw_shape, str) and self.raw_shape == "scalar"

    @property
    def pointer(self) -> Optional[PointerInfo]:
        return PointerInfo.from_shape(self.raw_shape)


@dataclass
class FieldMapping:
    u: FieldDescriptor = field(default_factory=FieldDescriptor)
    i: FieldDescriptor = field(default_factory=FieldDescriptor)
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "FieldMapping":
        if not isinstance(data, dict):
            data = {}
        return cls(
            u=FieldDescriptor.from_dict(data.get("u_field")),
            i=FieldDescriptor.from_dict(data.get("i_field")),
            raw=data,
        )


@dataclass
class StructSpec:
    fields: list[FieldMapping] = field(default_factory=list)
    variants: list[dict] = field(default_factory=list)
    raw_i_kind: Optional[str] = None
    raw_i_type: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "StructSpec":
        if not isinstance(data, dict):
            data = {}
        fields = [FieldMapping.from_dict(entry)
                  for entry in data.get("fields", [])]
        variants = list(data.get("variants") or [])
        return cls(
            fields=fields,
            variants=variants,
            raw_i_kind=data.get("i_kind"),
            raw_i_type=data.get("i_type"),
        )


@dataclass
class FunctionSpec:
    fields: list[FieldMapping] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "FunctionSpec":
        if not isinstance(data, dict):
            data = {}
        return cls(fields=[FieldMapping.from_dict(entry) for entry in data.get("fields", [])])


@dataclass
class StructPreflightResult:
    i_type: str
    i_kind: Optional[str]
    blocking_todos: list[str] = field(default_factory=list)
    derived_len_i_fields: set[str] = field(default_factory=set)
    derived_len_c_fields: set[str] = field(default_factory=set)


@dataclass
class FunctionSpecContext:
    spec: FunctionSpec
    by_rust: dict[str, FieldMapping] = field(default_factory=dict)
    by_u: dict[str, FieldMapping] = field(default_factory=dict)

    @classmethod
    def from_spec(cls, spec: FunctionSpec) -> "FunctionSpecContext":
        by_rust: dict[str, FieldMapping] = {}
        by_u: dict[str, FieldMapping] = {}
        for mapping in spec.fields:
            if mapping.i.name:
                by_rust[mapping.i.name] = mapping
            if mapping.u.name:
                by_u[mapping.u.name] = mapping
        return cls(spec=spec, by_rust=by_rust, by_u=by_u)


@dataclass
class FunctionArgumentPlan:
    pre_lines: list[str] = field(default_factory=list)
    call_args: list[str] = field(default_factory=list)
    mut_struct_params: list[dict[str, str]] = field(default_factory=list)


def _load_spec_json(spec_path: str) -> Optional[dict]:
    if not os.path.exists(spec_path):
        return None
    try:
        with open(spec_path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _preflight_struct_spec(
    struct_name: str,
    idiomatic_struct_code: str,
    spec: StructSpec,
) -> StructPreflightResult:
    blocking: list[str] = []

    # Normalize the kind: accept "struct"/"enum" and map "union" to "struct".
    raw_kind_value = spec.raw_i_kind
    if isinstance(raw_kind_value, str):
        candidate_kind = raw_kind_value.strip()
        lowered_kind = candidate_kind.lower() if candidate_kind else ""
        if lowered_kind == "union":
            lowered_kind = "struct"
        i_kind = lowered_kind if lowered_kind in {"struct", "enum"} else None
    else:
        i_kind = None

    if i_kind is None:
        raw_value = spec.raw_i_kind
        if isinstance(raw_value, str) and raw_value.strip():
            blocking.append(f"spec i_kind unsupported: {raw_value}")
        else:
            blocking.append("spec missing i_kind")

    i_type = struct_name
    if isinstance(spec.raw_i_type, str):
        candidate_type = spec.raw_i_type.strip()
        if candidate_type:
            i_type = candidate_type
        else:
            blocking.append("spec i_type empty")
    else:
        blocking.append("spec missing i_type")

    if i_kind is not None:
        # Verify that the idiomatic type exists in the provided Rust code.
        try:
            if i_kind == "enum":
                rust_ast_parser.get_enum_definition(
                    idiomatic_struct_code, i_type)
            else:
                rust_ast_parser.get_struct_definition(
                    idiomatic_struct_code, i_type)
        except Exception:
            blocking.append(
                f"spec i_type '{i_type}' not found as {i_kind} in idiomatic code")

    derived_len_i_fields: set[str] = set()
    derived_len_c_fields: set[str] = set()

    if i_kind == "enum":
        for mapping in spec.fields:
            if "." in mapping.u.name:
                blocking.append(
                    f"enum: nested field path not supported: {mapping.u.name}")
    elif i_kind == "struct":
        for mapping in spec.fields:
            c_name = mapping.u.name
            i_name = mapping.i.name
            if "." in c_name:
                blocking.append(
                    f"nested field path not supported: u={c_name} i={i_name}")
                continue
            if "." in i_name:
                base, _, suffix = i_name.partition(".")
                if suffix == "len" and base:
                    derived_len_i_fields.add(i_name)
                    if c_name:
                        derived_len_c_fields.add(c_name)
                    continue
                blocking.append(
                    f"nested field path not supported: u={c_name} i={i_name}")

    return StructPreflightResult(
        i_type=i_type,
        i_kind=i_kind,
        blocking_todos=blocking,
        derived_len_i_fields=derived_len_i_fields,
        derived_len_c_fields=derived_len_c_fields,
    )


def _render_struct_harness(
    struct_name: str,
    idiomatic_type: str,
    spec: StructSpec,
    preflight: StructPreflightResult,
    u_field_types: dict[str, str],
) -> Optional[str]:
    ptr_len_info: dict[str, dict] = {}
    init_lines: list[str] = []
    pointer_asserts: list[str] = []
    field_comment_indent = " " * 12

    for mapping in spec.fields:
        u_desc = mapping.u
        i_desc = mapping.i
        c_field = u_desc.name
        rust_path = i_desc.name
        shape = u_desc.raw_shape
        c_ty = u_field_types.get(c_field, u_desc.type or "")

        if not c_field or not rust_path:
            msg = f"missing field mapping: u={c_field} i={rust_path}"
            init_lines.append(f"{field_comment_indent}// TODO: {msg}")
            continue

        init_lines.append(
            f"{field_comment_indent}// Field '{c_field}' -> '{rust_path}' (C -> idiomatic)"
        )

        if rust_path in preflight.derived_len_i_fields:
            init_lines.append(
                f"{field_comment_indent}// Derived field '{rust_path}' computed via slice metadata"
            )
            continue

        c_access = _c_field(c_field)

        if isinstance(shape, str) and shape == "scalar":
            # Choose cast targets for libc scalar types when needed.
            if c_ty in SCALAR_CAST_OVERRIDES:
                cast_ty = LIBC_SCALAR_TO_PRIMITIVE.get(c_ty)
            elif c_ty in SCALAR_CAST_IDENTITY:
                cast_ty = c_ty
            else:
                cast_ty = None
            if cast_ty:
                init_lines.append(
                    f"            {rust_path}: {c_access} as {cast_ty},")
            else:
                init_lines.append(f"            {rust_path}: {c_access},")
            continue

        pointer = u_desc.pointer
        if pointer is None:
            msg = f"unsupported shape for field {c_field}"
            init_lines.append(f"{field_comment_indent}// TODO: {msg}")
            continue
        if pointer.is_forbidden and c_field:
            pointer_asserts.append(f"    assert!(!{c_access}.is_null());")

        kind = pointer.kind
        raw_i_ty = i_desc.type or ""
        i_ty = raw_i_ty.replace(" ", "")
        struct_ptr = None
        if kind == "ref":
            struct_ptr = _analyze_struct_ptr_conversion(c_ty, raw_i_ty)

        if struct_ptr:
            conv_name = f"C{struct_ptr['idiom_ident']}_to_{struct_ptr['idiom_ident']}_mut"
            ptr_expr = f"{c_access} as *mut C{struct_ptr['idiom_ident']}"
            if struct_ptr['is_option']:
                init_lines.append(
                    f"""            {rust_path}: if !{c_access}.is_null() {{
                let tmp = unsafe {{ {conv_name}({ptr_expr}) }};
                Some((*tmp).clone())
            }} else {{
                None
            }},""".rstrip()
                )
            else:
                init_lines.append(
                    f"""            {rust_path}: {{
                let tmp = unsafe {{ {conv_name}({ptr_expr}) }};
                (*tmp).clone()
            }},""".rstrip()
                )
            continue

        if kind == "cstring":
            is_opt = i_ty.startswith("Option<")
            null_mode = pointer.null
            if is_opt or null_mode == "none":
                init_lines.append(
                    f"""            {rust_path}: if !{c_access}.is_null() {{
                Some(unsafe {{ std::ffi::CStr::from_ptr({c_access}) }}.to_string_lossy().into_owned())
            }} else {{
                None
            }},""".rstrip()
                )
            else:
                init_lines.append(
                    f"""            {rust_path}: if !{c_access}.is_null() {{
                unsafe {{ std::ffi::CStr::from_ptr({c_access}) }}.to_string_lossy().into_owned()
            }} else {{
                String::new()
            }},""".rstrip()
                )
            continue

        if kind in {"slice", "ref"}:
            raw_len_from = pointer.len_from
            len_from_value = raw_len_from
            len_from_is_field = False
            len_expr: Optional[str] = None
            if kind == "ref":
                len_expr = "1usize"
            if isinstance(raw_len_from, str):
                candidate = raw_len_from.strip()
                if _is_simple_identifier(candidate) and candidate in u_field_types:
                    len_expr = f"({_c_field(candidate)} as usize)"
                    len_from_is_field = True
                    len_from_value = candidate
                else:
                    rendered = _render_len_expression(
                        raw_len_from, u_field_types, f"{_C_STRUCT_BIND}.")
                    if rendered is None:
                        msg = f"unsupported len_from expression '{raw_len_from}' for field {c_field}"
                        init_lines.append(
                            f"{field_comment_indent}// TODO: {msg}")
                        ptr_len_info[c_field] = {
                            "len_from": raw_len_from,
                            "len_expr": None,
                            "len_from_is_field": False,
                            "supported": False,
                        }
                        continue
                    len_expr = rendered
            elif isinstance(raw_len_from, (int, float)):
                len_expr = f"{int(raw_len_from)}usize"
            elif raw_len_from is not None:
                msg = f"unsupported len_from metadata for field {c_field}"
                init_lines.append(f"{field_comment_indent}// TODO: {msg}")
                ptr_len_info[c_field] = {
                    "len_from": raw_len_from,
                    "len_expr": None,
                    "len_from_is_field": False,
                    "supported": False,
                }
                continue
            elif kind == "slice" and pointer.len_const is not None:
                len_expr = f"{pointer.len_const}usize"

            ptr_len_info[c_field] = {
                "len_from": len_from_value,
                "len_expr": len_expr,
                "len_from_is_field": len_from_is_field,
                "supported": True,
            }

            elem = _infer_slice_elem_from_ptr_ty(c_ty)
            is_opt = i_ty.startswith("Option<")
            box_inner = _extract_box_inner(raw_i_ty)
            if kind == "ref" and box_inner:
                conv_name = f"C{box_inner}_to_{box_inner}_mut"
                if is_opt:
                    init_lines.append(
                        f"""            {rust_path}: if !{c_access}.is_null() {{
                Some(Box::new(unsafe {{ {conv_name}({c_access}) }}.clone()))
            }} else {{
                None
            }},""".rstrip()
                    )
                else:
                    init_lines.append(
                        f"""            {rust_path}: {{
                let tmp = unsafe {{ {conv_name}({c_access}) }};
                Box::new((*tmp).clone())
            }},""".rstrip()
                    )
                continue

            null_mode = pointer.null
            le_render = len_expr or "0usize"
            if is_opt or null_mode == "none":
                init_lines.append(
                    f"""            {rust_path}: if !{c_access}.is_null() && {le_render} > 0 {{
                Some(unsafe {{ std::slice::from_raw_parts({c_access} as *const {elem}, {le_render}) }}.to_vec())
            }} else {{
                None
            }},""".rstrip()
                )
            else:
                init_lines.append(
                    f"""            {rust_path}: if !{c_access}.is_null() && {le_render} > 0 {{
                unsafe {{ std::slice::from_raw_parts({c_access} as *const {elem}, {le_render}) }}.to_vec()
            }} else {{
                Vec::<{elem}>::new()
            }},""".rstrip()
                )
            continue

        msg = f"unsupported ptr kind for field {c_field}"
        init_lines.append(f"{field_comment_indent}// TODO: {msg}")

    back_lines: list[str] = []
    for mapping in spec.fields:
        u_desc = mapping.u
        i_desc = mapping.i
        c_field = u_desc.name
        rust_path = i_desc.name
        pointer = u_desc.pointer
        c_ty = u_field_types.get(c_field, u_desc.type or "")

        if (rust_path in preflight.derived_len_i_fields) or (c_field in preflight.derived_len_c_fields):
            continue

        if not c_field or not rust_path:
            msg = f"missing field mapping: u={c_field} i={rust_path}"
            back_lines.append(f"    // TODO: {msg}")
            continue

        back_lines.append(
            f"    // Field '{rust_path}' -> '{c_field}' (idiomatic -> C)"
        )

        # Directly read the idiomatic struct field for writing back.
        idiom_access = f"{_IDIOM_STRUCT_BIND}.{rust_path}"

        if u_desc.is_scalar:
            back_lines.append(f"    let _{c_field} = {idiom_access};")
            continue

        if pointer is None:
            msg = f"unsupported shape for field {c_field}"
            back_lines.append(f"    // TODO: {msg}")
            continue

        kind = pointer.kind
        raw_i_ty = i_desc.type or ""
        i_ty = raw_i_ty.replace(" ", "")
        struct_ptr = None
        if kind == "ref":
            struct_ptr = _analyze_struct_ptr_conversion(c_ty, raw_i_ty)

        if struct_ptr:
            conv_back = f"{struct_ptr['idiom_ident']}_to_{struct_ptr['c_ident']}_mut"
            if struct_ptr['is_option']:
                back_lines.append(
                    f"""    let _{c_field}_ptr: {c_ty} = match {idiom_access}.as_mut() {{
        Some(v) => unsafe {{ {conv_back}(v) }},
        None => core::ptr::null_mut(),
    }};"""
                )
            else:
                back_lines.append(
                    f"    let _{c_field}_ptr: {c_ty} = unsafe {{ {conv_back}({idiom_access}) }};"
                )
            continue

        if kind == "cstring":
            is_opt = _infer_option(raw_i_ty)
            if is_opt:
                back_lines.append(
                    f"""    let _{c_field}_ptr: *mut libc::c_char = match {idiom_access} {{
        Some(s) => {{
            let s = std::ffi::CString::new(s)
                .unwrap_or_else(|_| std::ffi::CString::new("").unwrap());
            s.into_raw()
        }},
        None => core::ptr::null_mut(),
    }};"""
                )
            else:
                back_lines.append(
                    f"""    let _{c_field}_ptr: *mut libc::c_char = {{
        let s = std::ffi::CString::new({idiom_access}.clone())
            .unwrap_or_else(|_| std::ffi::CString::new("").unwrap());
        s.into_raw()
    }};"""
                )
            continue

        if kind in {"slice", "ref"}:
            box_inner = _extract_box_inner(raw_i_ty)
            if kind == "ref" and box_inner:
                conv = f"{box_inner}_to_C{box_inner}_mut"
                if _infer_option(raw_i_ty):
                    back_lines.append(
                        f"""    let _{c_field}_ptr: {c_ty} = match {idiom_access}.as_mut() {{
        Some(v) => {conv}(v.as_mut()),
        None => core::ptr::null_mut(),
    }};"""
                    )
                else:
                    back_lines.append(
                        f"    let _{c_field}_ptr: {c_ty} = {conv}({idiom_access}.as_mut());"
                    )
                continue

            elem = _infer_slice_elem_from_ptr_ty(c_ty)
            is_opt = _infer_option(raw_i_ty)
            if is_opt:
                back_lines.append(
                    f"""    let _{c_field}_ptr: *mut {elem} = match {idiom_access}.as_ref() {{
        Some(v) => if v.is_empty() {{
            core::ptr::null_mut()
        }} else {{
            let mut b = v.clone().into_boxed_slice();
            let p = b.as_mut_ptr();
            core::mem::forget(b);
            p
        }},
        None => core::ptr::null_mut(),
    }};"""
                )
            else:
                back_lines.append(
                    f"""    let _{c_field}_ptr: *mut {elem} = if {idiom_access}.is_empty() {{
        core::ptr::null_mut()
    }} else {{
        let mut b = {idiom_access}.clone().into_boxed_slice();
        let p = b.as_mut_ptr();
        core::mem::forget(b);
        p
    }};"""
                )

            if kind == "slice":
                len_info = ptr_len_info.get(c_field, {})
                lf = len_info.get("len_from")
                if len_info.get("len_from_is_field") and isinstance(lf, str) and _is_simple_identifier(lf):
                    lf_clean = lf.strip()
                    lf_ty = u_field_types.get(lf_clean, None)
                    if is_opt:
                        if lf_ty is None:
                            back_lines.append(
                                f"    let _{lf_clean} = {idiom_access}.as_ref().map(|v| v.len()).unwrap_or(0) as usize;"
                            )
                        else:
                            back_lines.append(
                                f"    let _{lf_clean}: {lf_ty} = ({idiom_access}.as_ref().map(|v| v.len()).unwrap_or(0) as usize) as {lf_ty};"
                            )
                    else:
                        if lf_ty is None:
                            back_lines.append(
                                f"    let _{lf_clean} = {idiom_access}.len() as usize;"
                            )
                        else:
                            back_lines.append(
                                f"    let _{lf_clean}: {lf_ty} = ({idiom_access}.len() as usize) as {lf_ty};"
                            )
            continue

        msg = f"unsupported ptr kind for field {c_field}"
        back_lines.append(f"    // TODO: {msg}")

    c_fields_init: list[str] = []
    for mapping in spec.fields:
        u_desc = mapping.u
        pointer = u_desc.pointer
        c_field = u_desc.name
        i_desc = mapping.i
        i_name = i_desc.name

        if i_name in preflight.derived_len_i_fields or c_field in preflight.derived_len_c_fields:
            continue

        if u_desc.is_scalar:
            c_fields_init.append(f"        {c_field}: _{c_field},")
        elif pointer is not None:
            kind = pointer.kind
            if kind == "cstring":
                c_fields_init.append(f"        {c_field}: _{c_field}_ptr,")
            elif kind in {"slice", "ref"}:
                c_fields_init.append(f"        {c_field}: _{c_field}_ptr,")
                len_info = ptr_len_info.get(c_field, {})
                lf = len_info.get("len_from")
                if (
                    kind == "slice"
                    and len_info.get("len_from_is_field")
                    and isinstance(lf, str)
                    and _is_simple_identifier(lf)
                ):
                    lf_clean = lf.strip()
                    c_fields_init.append(f"        {lf_clean}: _{lf_clean},")
            else:
                return None
        else:
            return None

    uses = [
        "use core::ptr;",
        "use std::ffi;",
    ]

    context = StructHarnessContext.create(
        uses=uses,
        struct_name=struct_name,
        idiomatic_type=idiomatic_type,
        c_struct_bind=_C_STRUCT_BIND,
        idiom_struct_bind=_IDIOM_STRUCT_BIND,
        pointer_asserts=pointer_asserts,
        init_lines=init_lines,
        back_lines=back_lines,
        c_struct_init_lines=c_fields_init,
    )
    return render_struct_harness(context)


def _build_mut_struct_post_lines(mut_struct_params: list[dict[str, str]]) -> list[str]:
    post_lines: list[str] = []
    for entry in mut_struct_params:
        mode = entry.get("mode")
        struct_name = entry.get("struct_name")
        c_name = entry.get("c_name", struct_name)
        u_name = entry.get("u_name")
        param_name = entry.get("param_name")
        idiom_var = entry.get("idiom_var", param_name)
        tmp_var = f"__c_{param_name}"
        if mode == "direct_mut_struct":
            post_lines.append(
                render_function_macro(
                    "post_direct_struct",
                    u_name=u_name,
                    tmp_var=tmp_var,
                    struct_name=struct_name,
                    c_name=c_name,
                    param_name=idiom_var,
                )
            )
        elif mode == "option_mut_struct":
            storage_var = entry.get("storage_var")
            post_lines.append(
                render_function_macro(
                    "post_option_struct",
                    u_name=u_name,
                    storage_var=storage_var,
                    tmp_var=tmp_var,
                    struct_name=struct_name,
                    c_name=c_name,
                )
            )
        else:
            post_lines.append(
                f"    // TODO: unsupported post-call conversion for {param_name}")
    return post_lines


def _prepare_function_arguments(
    id_params: list[dict],
    context: FunctionSpecContext,
    idiom_names: set[str],
    c_alias_for: Callable[[str], str],
    u_param_map: dict[str, dict],
) -> FunctionArgumentPlan:
    plan = FunctionArgumentPlan()

    for param in id_params:
        pname = (param or {}).get("name")
        if not pname:
            plan.pre_lines.append(
                "    // TODO: parameter without name in idiomatic signature")
            plan.call_args.append("/* TODO unnamed param */")
            continue

        traits = _ensure_traits_dict((param or {}).get("traits"))
        raw_type = (param or {}).get("type") or traits.get("raw") or ""
        norm_type = traits.get("normalized") or raw_type.replace(" ", "")

        spec_entry = context.by_rust.get(
            pname) or context.by_u.get(pname) or FieldMapping()
        u_field = spec_entry.u
        u_name = u_field.name or pname
        u_shape = u_field.raw_shape
        u_param_info = u_param_map.get(u_name, {})
        c_type_for_param = (
            u_param_info.get("type") if isinstance(
                u_param_info, dict) else None
        ) or u_field.type or ""

        if norm_type in idiom_names and not traits.get("is_reference"):
            c_alias = c_alias_for(norm_type)
            struct_ptr = _analyze_struct_ptr_conversion(
                c_type_for_param, raw_type)
            if struct_ptr and struct_ptr["idiom_ident"] == norm_type:
                plan.pre_lines.append(
                    f"    // Arg '{pname}': convert {c_type_for_param or '*mut _'} to {norm_type}"
                )
                plan.pre_lines.append(f"    assert!(!{u_name}.is_null());")
                plan.pre_lines.append(
                    f"    let mut {pname}_ref: &'static mut {norm_type} = unsafe {{ C{c_alias}_to_{norm_type}_mut({u_name}) }};"
                )
                plan.pre_lines.append(
                    f"    let {pname}_val: {norm_type} = {pname}_ref.clone();"
                )
                plan.call_args.append(f"{pname}_val")
            else:
                msg = f"param {pname}: unsupported struct conversion"
                plan.pre_lines.append(f"    // TODO: {msg}")
                plan.call_args.append(f"/* TODO {pname} */")
            continue

        if traits.get("is_option"):
            option_inner = _ensure_traits_dict(traits.get("option_inner"))
            if option_inner.get("is_reference") and option_inner.get("is_mut_reference"):
                inner = _ensure_traits_dict(
                    option_inner.get("reference_inner"))
                inner_name = (
                    inner.get("path_ident")
                    or inner.get("normalized")
                    or inner.get("raw")
                    or ""
                )
                if inner_name in idiom_names:
                    c_alias_inner = c_alias_for(inner_name)
                    plan.pre_lines.append(
                        f"    // Arg '{pname}': optional *mut {inner_name} to Option<&mut {inner_name}>"
                    )
                    plan.pre_lines.append(
                        render_function_macro(
                            "option_struct_storage",
                            storage_var=f"{pname}_storage",
                            struct_name=inner_name,
                            converter=f"C{c_alias_inner}_to_{inner_name}_mut",
                            ptr_name=u_name,
                        )
                    )
                    plan.call_args.append(f"{pname}_storage.as_deref_mut()")
                    plan.mut_struct_params.append(
                        {
                            "mode": "option_mut_struct",
                            "storage_var": f"{pname}_storage",
                            "struct_name": inner_name,
                            "c_name": c_alias_inner,
                            "u_name": u_name,
                            "param_name": pname,
                        }
                    )
                    continue

        if traits.get("is_reference") and traits.get("is_mut_reference"):
            inner = _ensure_traits_dict(traits.get("reference_inner"))
            inner_name = (
                inner.get("path_ident")
                or inner.get("normalized")
                or inner.get("raw")
                or ""
            )
            if inner_name in idiom_names:
                c_alias_inner = c_alias_for(inner_name)
                if u_name not in u_param_map:
                    msg = f"&mut {inner_name}: cannot find matching U param"
                    plan.pre_lines.append(f"    // TODO: {msg}")
                    plan.call_args.append(f"/* TODO &mut {inner_name} */")
                else:
                    idiom_var = f"{pname}_idiom"
                    plan.pre_lines.append(
                        f"    // Arg '{pname}': convert *mut {inner_name} to &mut {inner_name}"
                    )
                    plan.pre_lines.append(
                        render_function_macro(
                            "convert_struct_ptr",
                            var_name=idiom_var,
                            struct_name=inner_name,
                            converter=f"C{c_alias_inner}_to_{inner_name}_mut",
                            ptr_name=u_name,
                        )
                    )
                    plan.pre_lines.append(
                        f"    // will copy back after call for {pname}")
                    plan.call_args.append(idiom_var)
                    plan.mut_struct_params.append(
                        {
                            "mode": "direct_mut_struct",
                            "param_name": pname,
                            "idiom_var": idiom_var,
                            "struct_name": inner_name,
                            "c_name": c_alias_inner,
                            "u_name": u_name,
                        }
                    )
                continue

            pointer = PointerInfo.from_shape(u_shape)
            if pointer and pointer.kind == "ref":
                inner_ty = (
                    inner.get("normalized")
                    or inner.get("path_ident")
                    or inner.get("raw")
                    or raw_type.replace("&mut", "").strip()
                )
                if pointer.is_forbidden:
                    plan.pre_lines.append(
                        f"    // Arg '{pname}': convert *mut {inner_ty} to &mut {inner_ty}"
                    )
                    plan.pre_lines.append(f"    assert!(!{u_name}.is_null());")
                    plan.pre_lines.append(
                        f"    let {pname}_ref: &'static mut {inner_ty} = unsafe {{ &mut *{u_name} }};"
                    )
                    plan.call_args.append(f"{pname}_ref")
                else:
                    msg = f"param {pname}: nullable mutable pointer conversion unsupported"
                    plan.pre_lines.append(f"    // TODO: {msg}")
                    plan.call_args.append(f"/* TODO {pname} */")
                continue

        is_slice, is_slice_optional, slice_elem, is_mut_slice = _classify_slice_traits(
            traits)
        if is_slice:
            pointer = PointerInfo.from_shape(u_shape)
            if pointer is None or pointer.kind != "slice":
                msg = f"slice arg {pname}: spec.kind is not slice"
                plan.pre_lines.append(f"    // TODO: {msg}")
                plan.call_args.append(f"/* TODO slice {pname} */")
                continue
            c_ptr_name = u_name
            len_from = pointer.len_from
            if isinstance(len_from, str) and len_from in u_param_map:
                len_expr = f"{len_from} as usize"
            elif pointer.len_const is not None:
                len_expr = f"{pointer.len_const}usize"
            else:
                msg = f"slice arg {pname}: need len_from or len_const"
                plan.pre_lines.append(f"    // TODO: {msg}")
                plan.call_args.append(f"/* TODO slice {pname} */")
                continue
            elem = (slice_elem or "").replace(
                " ", "") or _infer_slice_elem_from_ptr_ty(u_field.type or "")
            len_var = f"{pname}_len"
            usable_len_var = f"{len_var}_non_null"
            if is_slice_optional:
                plan.pre_lines.append(
                    f"    // Arg '{pname}': optional slice from {c_ptr_name} with len {len_expr}")
            else:
                plan.pre_lines.append(
                    f"    // Arg '{pname}': slice from {c_ptr_name} with len {len_expr}")
            plan.pre_lines.append(f"    let {len_var} = {len_expr};")
            plan.pre_lines.append(
                f"    let {usable_len_var} = if {c_ptr_name}.is_null() {{ 0 }} else {{ {len_var} }};"
            )
            if is_slice_optional:
                if is_mut_slice:
                    plan.pre_lines.append(
                        render_function_macro(
                            "slice_option_mut",
                            var_name=f"{pname}_opt",
                            elem_type=elem,
                            len_expr=usable_len_var,
                            ptr_expr=f"{c_ptr_name} as *mut {elem}",
                        )
                    )
                else:
                    plan.pre_lines.append(
                        render_function_macro(
                            "slice_option_ref",
                            var_name=f"{pname}_opt",
                            elem_type=elem,
                            len_expr=usable_len_var,
                            ptr_expr=f"{c_ptr_name} as *const {elem}",
                        )
                    )
                plan.call_args.append(f"{pname}_opt")
            else:
                if is_mut_slice:
                    plan.pre_lines.append(
                        render_function_macro(
                            "slice_required_mut",
                            var_name=pname,
                            elem_type=elem,
                            len_expr=usable_len_var,
                            ptr_expr=f"{c_ptr_name} as *mut {elem}",
                        )
                    )
                else:
                    plan.pre_lines.append(
                        render_function_macro(
                            "slice_required_ref",
                            var_name=pname,
                            elem_type=elem,
                            len_expr=usable_len_var,
                            ptr_expr=f"{c_ptr_name} as *const {elem}",
                        )
                    )
                plan.call_args.append(pname)
            continue

        string_kind = _classify_string_traits(traits)
        if string_kind in {"owned", "borrowed", "option_owned", "option_borrowed"}:
            pointer = PointerInfo.from_shape(u_shape)
            if pointer is None or pointer.kind != "cstring":
                msg = f"string arg {pname}: spec.kind is not cstring"
                plan.pre_lines.append(f"    // TODO: {msg}")
                plan.call_args.append(f"/* TODO string {pname} */")
                continue
            c_ptr_name = u_name
            if string_kind in {"option_owned", "option_borrowed"}:
                plan.pre_lines.append(
                    f"    // Arg '{pname}': optional C string at {c_ptr_name}"
                )
                plan.pre_lines.append(
                    render_function_macro(
                        "cstring_optional",
                        var_name=f"{pname}_opt",
                        ptr_name=c_ptr_name,
                    )
                )
                if string_kind == "option_borrowed":
                    plan.call_args.append(f"{pname}_opt.as_deref()")
                else:
                    plan.call_args.append(f"{pname}_opt")
            elif string_kind == "owned":
                plan.pre_lines.append(
                    f"    // Arg '{pname}': C string at {c_ptr_name}"
                )
                plan.pre_lines.append(
                    render_function_macro(
                        "cstring_owned",
                        var_name=f"{pname}_str",
                        ptr_name=c_ptr_name,
                    )
                )
                plan.call_args.append(f"{pname}_str")
            else:
                plan.pre_lines.append(
                    f"    // Arg '{pname}': borrowed C string at {c_ptr_name}"
                )
                plan.pre_lines.append(
                    render_function_macro(
                        "cstring_owned",
                        var_name=f"{pname}_str",
                        ptr_name=c_ptr_name,
                    )
                )
                plan.call_args.append(f"&{pname}_str")
            continue

        if norm_type in SCALAR_TYPES:
            if not spec_entry.raw and u_name not in u_param_map:
                msg = f"scalar arg {pname}: missing in U signature"
                plan.pre_lines.append(f"    // TODO: {msg}")
                plan.call_args.append(f"/* TODO scalar {pname} */")
            else:
                plan.call_args.append(u_name)
            continue

        msg = f"param {pname} of type {raw_type}: unsupported mapping"
        plan.pre_lines.append(f"    // TODO: {msg}")
        plan.call_args.append(f"/* TODO param {pname} */")

    return plan


def _struct_todo_skeleton(struct_name: str, idiomatic_name: str, todos: list[str]) -> str:
    todo_header = "\n".join(
        ["// TODO: Spec exceeds automatic rules. Items to handle manually:"]
        + [f"// TODO: {t}" for t in todos]
    )
    return f"""{todo_header}
unsafe fn {idiomatic_name}_to_C{struct_name}_mut(input: &mut {idiomatic_name}) -> *mut C{struct_name} {{
    // TODO: implement I->U conversion based on above items
    unimplemented!()
}}

unsafe fn C{struct_name}_to_{idiomatic_name}_mut(input: *mut C{struct_name}) -> &'static mut {idiomatic_name} {{
    // TODO: implement U->I conversion based on above items
    unimplemented!()
}}
"""


def _build_function_return_handling(
    ret_spec: Optional[FieldMapping],
    id_ret: Optional[dict],
    c_ret: Optional[dict],
    struct_dep_names: list[str],
    struct_name_alias: Optional[dict[str, str]],
    c_name_for_idiom: dict[str, str],
    u_param_map: dict[str, dict],
    has_ret: bool,
) -> Optional[tuple[list[str], str]]:
    ret_lines: list[str] = []
    ret_return_expr = "__ret"
    alias_map = struct_name_alias or {}

    def c_alias_for(idiom): return c_name_for_idiom.get(idiom, idiom)

    if ret_spec is not None:
        u_desc = ret_spec.u
        i_desc = ret_spec.i
        shape = u_desc.raw_shape
        u_name = u_desc.name
        u_param_info = u_param_map.get(u_name, {})
        u_traits = _type_traits_from_param(u_param_info)

        if isinstance(shape, str) and shape == "scalar":
            if not c_ret:
                if _type_pointer_depth(u_traits) >= 1:
                    ret_lines.append(
                        render_function_macro(
                            "write_scalar_pointer",
                            target_ptr=u_name,
                            value_expr="__ret",
                        )
                    )
                else:
                    return None
        elif isinstance(shape, dict) and "ptr" in shape:
            ptr_meta = shape["ptr"]
            kind = ptr_meta.get("kind")
            c_ret_ty = (
                u_param_info.get("type") if isinstance(
                    u_param_info, dict) else None
            ) or u_desc.type or ""
            struct_ret = _analyze_struct_ptr_conversion(
                c_ret_ty, i_desc.type or "")
            if struct_ret and struct_ret["idiom_ident"] in struct_dep_names:
                idiom_ident = struct_ret["idiom_ident"]
                ret_lines.append(
                    render_function_macro(
                        "write_struct_pointer",
                        target_ptr=u_name,
                        source_expr="__ret",
                        clone_var="__ret_clone",
                        tmp_var="ret_ptr",
                        converter=f"{idiom_ident}_to_C{c_alias_for(idiom_ident)}_mut",
                    )
                )
            elif kind == "ref":
                if _type_pointer_depth(u_traits) >= 1:
                    ret_lines.append(
                        render_function_macro(
                            "write_scalar_pointer",
                            target_ptr=u_name,
                            value_expr="__ret",
                        )
                    )
                else:
                    return None
            elif kind == "cstring":
                if _type_pointer_depth(u_traits) < 2:
                    return None
                ret_lines.append(
                    render_function_macro(
                        "create_cstring_var",
                        var_name="__ret_cstr",
                        source_expr="__ret",
                    )
                )
                ret_lines.append(
                    render_function_macro(
                        "assign_pointer_from_var",
                        target_ptr=u_name,
                        var_name="__ret_cstr",
                    )
                )
            elif kind == "slice":
                len_from = ptr_meta.get("len_from")
                if not len_from:
                    return None
                if _type_pointer_depth(u_traits) < 2:
                    return None
                len_param_info = u_param_map.get(len_from, {})
                len_traits = _type_traits_from_param(len_param_info)
                if _type_pointer_depth(len_traits) < 1:
                    return None
                # Derive the element type for the returned slice.
                pointer_traits = _ensure_traits_dict(u_traits)
                base_candidate = (
                    pointer_traits.get("pointer_base_normalized")
                    or pointer_traits.get("pointer_base_ident")
                    or pointer_traits.get("pointer_base_raw")
                )
                elem_raw = base_candidate if isinstance(
                    base_candidate, str) else ""
                elem = elem_raw or "u8"
                ret_lines.append(
                    render_function_macro(
                        "slice_return_block",
                        target_ptr=u_name,
                        len_ptr=len_from,
                        elem_type=elem,
                        vec_var="__ret_vec",
                    )
                )
            else:
                return None
        else:
            return None

    if has_ret and ret_return_expr == "__ret":
        id_traits = _ensure_traits_dict(id_ret)
        c_traits = _ensure_traits_dict(c_ret)
        id_name = (
            id_traits.get("path_ident")
            or id_traits.get("normalized")
            or id_traits.get("raw")
            or ""
        )
        c_name_full = (
            c_traits.get("path_ident")
            or c_traits.get("normalized")
            or c_traits.get("raw")
            or ""
        )
        id_name_simple = id_name.split("::")[-1] if id_name else ""
        c_name_simple = c_name_full.split("::")[-1] if c_name_full else ""

        if id_name_simple and c_name_simple:
            for struct_name in struct_dep_names:
                idiom_name = alias_map.get(struct_name, struct_name)
                if id_name_simple != idiom_name:
                    continue
                c_base = c_alias_for(idiom_name)
                expected_c = f"C{c_base}"
                alt_expected = f"C{idiom_name}"
                candidates = {
                    expected_c.split("::")[-1],
                    alt_expected.split("::")[-1],
                    c_base.split("::")[-1],
                }
                if c_name_simple not in candidates:
                    continue
                ret_lines.append(
                    render_function_macro(
                        "struct_return_value",
                        converter=f"{idiom_name}_to_{expected_c}_mut",
                        tmp_var="__ret_ptr",
                    )
                )
                ret_return_expr = "__ret_c_value"
                break

    return ret_lines, ret_return_expr


def _c_field(name: str) -> str:
    return f"{_C_STRUCT_BIND}.{name}"


def _is_simple_identifier(text: Optional[str]) -> bool:
    if not isinstance(text, str):
        return False
    candidate = text.strip()
    return bool(candidate) and bool(IDENTIFIER_RE.fullmatch(candidate))


def _render_len_expression(
    expr: str,
    field_types: dict[str, str],
    prefix: str,
    *,
    cast_to_usize: bool = True,
) -> Optional[str]:
    if not isinstance(expr, str):
        return None
    cleaned = expr.strip()
    if not cleaned:
        return None

    unknown: set[str] = set()

    def _replace(match: re.Match[str]) -> str:
        name = match.group(0)
        if name in field_types:
            base = f"{prefix}{name}"
            return f"({base} as usize)" if cast_to_usize else base
        if name in ALLOWED_LEN_WORDS:
            return name
        # Numbers are not matched by this regex, so any other identifier is unknown
        unknown.add(name)
        return name

    rendered = IDENTIFIER_RE.sub(_replace, cleaned)
    if unknown:
        return None
    rendered = re.sub(r"\s+", " ", rendered).strip()
    if not rendered:
        return None
    return f"({rendered})"


def _parse_unidiomatic_struct_field_types(
    struct_name: str,
    code: str,
) -> dict[str, str]:
    """Use the Rust AST parser to recover field types for the unidiomatic struct."""

    candidates: list[Optional[str]] = []
    if struct_name:
        candidates.append(struct_name)
        c_struct = f"C{struct_name}"
        if c_struct != struct_name:
            candidates.append(c_struct)
    candidates.append(None)

    for candidate in candidates:
        try:
            if candidate is None:
                raw = rust_ast_parser.get_struct_field_types(code)
            else:
                raw = rust_ast_parser.get_struct_field_types(code, candidate)
            return {name: canonical_type_string(ty) for name, ty in raw.items()}
        except Exception:
            continue
    return {}


def _get_type_traits(type_str: str) -> dict:
    key = (type_str or "").strip()
    if not key:
        return {}
    cached = _TYPE_TRAITS_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        traits = rust_ast_parser.parse_type_traits(key)
    except Exception:
        traits = {}
    _TYPE_TRAITS_CACHE[key] = traits
    return traits


def _infer_slice_elem_from_ptr_ty(ptr_ty: str) -> str:
    traits = _get_type_traits(ptr_ty)
    candidate = (traits or {}).get("pointer_element")
    if not isinstance(candidate, str) or not candidate.strip():
        inner_traits = _ensure_traits_dict((traits or {}).get("pointer_inner"))
        candidate = inner_traits.get(
            "normalized") or inner_traits.get("path_ident")
    if isinstance(candidate, str):
        stripped = candidate.strip()
        if stripped:
            mapped = LIBC_SCALAR_TO_PRIMITIVE.get(stripped)
            if mapped:
                return mapped
            return stripped
    return "u8"


def _infer_option(ty: str) -> bool:
    traits = _get_type_traits(ty)
    if traits:
        return bool(traits.get('is_option'))
    # fallback
    return (ty or "").replace(" ", "").startswith("Option<")


def _extract_box_inner(i_type: str) -> Optional[str]:
    """Return the inner type if the idiomatic field is Box<T> or Option<Box<T>>."""

    parsed = _get_type_traits(i_type)
    candidate = (parsed or {}).get('box_innermost')
    if isinstance(candidate, str) and candidate.strip():
        return candidate

    # fallback parsing
    normalized = (parsed or {}).get('normalized') or (
        i_type or '').replace(' ', '')
    cleaned = normalized
    if cleaned.startswith("Option<") and cleaned.endswith(">"):
        cleaned = cleaned[len("Option<"):-1]
    if cleaned.startswith("Box<") and cleaned.endswith(">"):
        return cleaned[4:-1]
    return None


def _ensure_traits_dict(traits: Optional[dict]) -> dict:
    return traits if isinstance(traits, dict) else {}


def _classify_string_traits(traits: Optional[dict]) -> str:
    traits = _ensure_traits_dict(traits)
    if not traits:
        return "other"
    if traits.get("is_option"):
        inner_kind = _classify_string_traits(traits.get("option_inner"))
        if inner_kind == "owned":
            return "option_owned"
        if inner_kind == "borrowed":
            return "option_borrowed"
        return "other"
    if traits.get("is_string"):
        return "owned"
    if traits.get("is_str"):
        return "borrowed"
    if traits.get("is_reference"):
        return _classify_string_traits(traits.get("reference_inner"))
    return "other"


def _classify_slice_traits(traits: Optional[dict]) -> tuple[bool, bool, Optional[str], bool]:
    traits = _ensure_traits_dict(traits)
    if not traits:
        return False, False, None, False
    if traits.get("is_option"):
        is_slice, _ignored_optional, elem, is_mut = _classify_slice_traits(
            traits.get("option_inner")
        )
        if is_slice:
            return True, True, elem, is_mut
    if traits.get("is_slice"):
        is_mut = bool(traits.get("is_mut_reference"))
        return True, False, traits.get("slice_elem"), is_mut
    if traits.get("is_reference"):
        inner = _ensure_traits_dict(traits.get("reference_inner"))
        is_slice, is_opt, elem, is_mut = _classify_slice_traits(inner)
        if is_slice and traits.get("is_mut_reference"):
            is_mut = True
        return is_slice, is_opt, elem, is_mut
    return False, False, None, False


def _has_non_unit_return(ret_traits: Optional[dict]) -> bool:
    traits = _ensure_traits_dict(ret_traits)
    if not traits:
        return False
    normalized = traits.get('normalized') or (
        traits.get('raw') or "").replace(" ", "")
    return normalized not in {"", "()"}


def _type_pointer_depth(traits: Optional[dict]) -> int:
    info = _ensure_traits_dict(traits)
    depth = info.get("pointer_depth")
    if isinstance(depth, int):
        return depth
    try:
        return int(depth)
    except (TypeError, ValueError):
        return 0


def _analyze_struct_ptr_conversion(c_ty: str, raw_i_ty: str) -> Optional[dict]:
    """Detect whether a pointer field corresponds to a struct conversion helper.

    Returns a dictionary describing the idiomatic struct name and whether the
    idiomatic side wraps it in Option/Box. The caller can then emit conversions
    using `C{struct}_to_{struct}_mut` / `{struct}_to_C{struct}_mut` helpers.
    """

    c_traits = _get_type_traits(c_ty)
    depth = _type_pointer_depth(c_traits)
    if depth == 0:
        return None
    base_ident = ""
    base_ident_value = (c_traits or {}).get("pointer_base_ident")
    if isinstance(base_ident_value, str) and base_ident_value:
        base_ident = base_ident_value.split("::")[-1]
    if not base_ident:
        base_ident = ((c_traits or {}).get(
            "pointer_base_normalized") or "").split("::")[-1]
    if not base_ident:
        inner_traits = _ensure_traits_dict(
            (c_traits or {}).get("pointer_inner"))
        inner_ident_val = inner_traits.get(
            "path_ident") or inner_traits.get("normalized")
        if isinstance(inner_ident_val, str) and inner_ident_val:
            base_ident = inner_ident_val.split("::")[-1]
    if not base_ident:
        return None

    i_traits = _get_type_traits(raw_i_ty)
    info = _ensure_traits_dict(i_traits)

    is_option = bool(info.get('is_option'))
    inner = _ensure_traits_dict(
        info.get('option_inner') if is_option else info)
    # Strip references
    while inner.get('is_reference'):
        inner = _ensure_traits_dict(inner.get('reference_inner'))

    is_box = bool(inner.get('is_box'))
    if is_box:
        # Existing branch handles Box conversions elsewhere; skip
        return None

    inner_ident = (inner.get('path_ident') or inner.get(
        'normalized') or '').split('::')[-1]
    if not inner_ident:
        return None

    # Accept either exact match or C-prefixed base name.
    c_ident = base_ident
    if c_ident == inner_ident:
        # Already the same name (rare, but preserve for completeness)
        pass
    elif c_ident == f"C{inner_ident}":
        # Matches C-prefixed name, expected
        pass
    else:
        return None

    return {
        "idiom_ident": inner_ident,
        "c_ident": c_ident,
        "is_option": is_option,
    }


def _type_traits_from_param(param: Optional[dict]) -> dict:
    if not isinstance(param, dict):
        return {}
    return _ensure_traits_dict(param.get('traits'))


def _gen_u_to_i_expr(u: dict, i: dict, u_field_types: dict[str, str]) -> Optional[str]:
    """Return an expression converting C field to idiomatic value, for enum payloads.
    Only supports scalar|ptr(cstring|slice|ref). Uses u.shape and u.type; i.type only for Option detection.
    """
    name = u.get("name")
    shape = u.get("shape")
    c_ty = (u.get("type") or u_field_types.get(name, ""))
    i_ty = i.get("type") or ""
    if isinstance(shape, str) and shape == "scalar":
        # Do not force cast; rely on compiler when types match.
        return _c_field(name)
    if not isinstance(shape, dict) or "ptr" not in shape:
        return None
    ptr = shape["ptr"]
    kind = ptr.get("kind")
    c_field_expr = _c_field(name)
    if kind == "cstring":
        is_opt = _infer_option(i_ty)
        if is_opt or ptr.get("null") == "nullable":
            return f"""if !{c_field_expr}.is_null() {{
                Some(unsafe {{ std::ffi::CStr::from_ptr({c_field_expr}) }}.to_string_lossy().into_owned())
            }} else {{
                None
            }}"""
        else:
            return f"""if !{c_field_expr}.is_null() {{
                unsafe {{ std::ffi::CStr::from_ptr({c_field_expr}) }}.to_string_lossy().into_owned()
            }} else {{
                String::new()
            }}"""
    if kind in ("slice", "ref"):
        elem = _infer_slice_elem_from_ptr_ty(c_ty)
        is_opt = _infer_option(i_ty)
        if kind == "ref":
            le = "1usize"
        else:
            if "len_from" in ptr:
                le = f"({_c_field(ptr['len_from'])} as usize)"
            elif "len_const" in ptr:
                le = f"{int(ptr['len_const'])}usize"
            else:
                return None
        base = (
            f"unsafe {{ std::slice::from_raw_parts({c_field_expr} as *const {elem}, {le}) }}.to_vec()"
        )
        if is_opt or ptr.get("null") == "nullable":
            return f"""if !{c_field_expr}.is_null() && {le} > 0 {{
                Some({base})
            }} else {{
                None
            }}"""
        else:
            return f"""if !{c_field_expr}.is_null() && {le} > 0 {{
                {base}
            }} else {{
                Vec::<{elem}>::new()
            }}"""
    return None


def _gen_i_to_c_assign_lines(u: dict, i: dict, i_expr: str, u_field_types: dict[str, str]) -> Optional[list[str]]:
    """Return lines assigning from idiomatic expr (like v0) to C backing fields.
    Produces local temps _<field> (scalar) or _<field>_ptr, and len writeback if slice.
    """
    name = u.get("name")
    shape = u.get("shape")
    c_ty = (u.get("type") or u_field_types.get(name, ""))
    i_ty = i.get("type") or ""
    out: list[str] = []
    if isinstance(shape, str) and shape == "scalar":
        out.append(f"    let _{name} = {i_expr};")
        return out
    if not isinstance(shape, dict) or "ptr" not in shape:
        return None
    ptr = shape["ptr"]
    kind = ptr.get("kind")
    if kind == "cstring":
        is_opt = _infer_option(i_ty)
        if is_opt:
            out.append(
                f"""    let _{name}_ptr: *mut libc::c_char = match {i_expr} {{
        Some(s) => {{
            let s = std::ffi::CString::new(s)
                .unwrap_or_else(|_| std::ffi::CString::new("").unwrap());
            s.into_raw()
        }},
        None => core::ptr::null_mut(),
    }};"""
            )
        else:
            out.append(
                f"""    let _{name}_ptr: *mut libc::c_char = {{
        let s = std::ffi::CString::new({i_expr}.clone())
            .unwrap_or_else(|_| std::ffi::CString::new("").unwrap());
        s.into_raw()
    }};"""
            )
        return out
    if kind in ("slice", "ref"):
        box_inner = _extract_box_inner(i_ty)
        if kind == "ref" and box_inner:
            conv = f"{box_inner}_to_C{box_inner}_mut"
            if _infer_option(i_ty):
                out.append(
                    f"""    let _{name}_ptr: {c_ty} = match {i_expr}.as_mut() {{
        Some(v) => {conv}(v.as_mut()),
        None => core::ptr::null_mut(),
    }};"""
                )
            else:
                out.append(
                    f"    let _{name}_ptr: {c_ty} = {conv}({i_expr}.as_mut());"
                )
            return out
        elem = _infer_slice_elem_from_ptr_ty(c_ty)
        is_opt = _infer_option(i_ty)
        if is_opt:
            out.append(
                f"""    let _{name}_ptr: *mut {elem} = match {i_expr}.as_ref() {{
        Some(v) => if v.is_empty() {{
            core::ptr::null_mut()
        }} else {{
            let mut b = v.clone().into_boxed_slice();
            let p = b.as_mut_ptr();
            core::mem::forget(b);
            p
        }},
        None => core::ptr::null_mut(),
    }};"""
            )
        else:
            out.append(
                f"""    let _{name}_ptr: *mut {elem} = if {i_expr}.is_empty() {{
        core::ptr::null_mut()
    }} else {{
        let mut b = {i_expr}.clone().into_boxed_slice();
        let p = b.as_mut_ptr();
        core::mem::forget(b);
        p
    }};"""
            )
        if kind == "slice" and "len_from" in ptr:
            lf = ptr["len_from"]
            lf_ty = u_field_types.get(lf, None)
            if is_opt:
                if lf_ty is None:
                    out.append(
                        f"    let _{lf} = {i_expr}.as_ref().map(|v| v.len()).unwrap_or(0) as usize;")
                else:
                    out.append(
                        f"    let _{lf}: {lf_ty} = ({i_expr}.as_ref().map(|v| v.len()).unwrap_or(0) as usize) as {lf_ty};")
            else:
                if lf_ty is None:
                    out.append(f"    let _{lf} = {i_expr}.len() as usize;")
                else:
                    out.append(
                        f"    let _{lf}: {lf_ty} = ({i_expr}.len() as usize) as {lf_ty};")
        return out
    return None


def _generate_enum_struct_converters(
    struct_name: str,
    i_type: str,
    fields: list[dict],
    variants: list[dict],
    u_field_types: dict[str, str],
) -> Optional[str]:
    # Basic checks: need tag per variant
    if not variants:
        return None
    # Disallow dotted names for now (handled earlier)
    # Build map u_name -> (u,i)
    fmap: dict[str, tuple[dict, dict]] = {}
    for f in fields:
        u = f.get("u_field", {}) or {}
        i = f.get("i_field", {}) or {}
        nm = u.get("name")
        if not nm:
            return None
        fmap[nm] = (u, i)

    # Identify tag field type from first variant
    first = variants[0]
    tag_name = first.get("when", {}).get("tag")
    if not tag_name:
        return None
    tag_ty = u_field_types.get(tag_name, None)
    # U -> I(Enum): match on c_struct.tag and build i_type::Variant(args)
    arms: list[dict[str, str]] = []
    for v in variants:
        vw = v.get("when", {})
        if vw.get("tag") != tag_name:
            return None
        equals = vw.get("equals")
        vname = v.get("name")
        payload = v.get("payload") or []
        # sort payload by i_field.name numeric (tuple order)

        def idx(p):
            try:
                return int(((p.get("i_field") or {}).get("name") or "0"))
            except Exception:
                return 0
        payload_sorted = sorted(payload, key=idx)
        arg_exprs: list[str] = []
        for pf in payload_sorted:
            u = (pf.get("u_field") or {})
            i = (pf.get("i_field") or {})
            expr = _gen_u_to_i_expr(u, i, u_field_types)
            if expr is None:
                return None
            arg_exprs.append(expr)
        args_join = ", ".join(arg_exprs)
        variant_expr = f"{i_type}::{vname}({args_join})" if arg_exprs else f"{i_type}::{vname}"
        arms.append({"match_value": equals, "expression": variant_expr})

    # I(Enum) -> U: match on idiom_struct and build all fields
    # For inactive fields, zero/null them; write tag to equals
    variant_contexts: list[dict[str, Any]] = []
    for v in variants:
        vname = v.get("name")
        payload = v.get("payload") or []
        # arity from payload count
        arity = len(payload)
        binders = ", ".join([f"v{idx}" for idx in range(arity)])
        pat = f"{i_type}::{vname}" + (f"({binders})" if arity > 0 else "")
        # Build temps
        temps: list[str] = []
        # map u_name -> temp symbol
        u_to_temp: dict[str, str] = {}
        # active ones
        for idx, pf in enumerate(payload):
            u = (pf.get("u_field") or {})
            i = (pf.get("i_field") or {})
            u_name = u.get("name")
            arg = f"v{idx}"
            lines = _gen_i_to_c_assign_lines(u, i, arg, u_field_types)
            if lines is None:
                return None
            temps.extend(lines)
            if isinstance(u.get("shape"), dict) and "ptr" in u.get("shape"):
                u_to_temp[u_name] = f"_{u_name}_ptr"
                # handle slice length fields
                ptr = u["shape"]["ptr"]
                if ptr.get("kind") == "slice" and "len_from" in ptr:
                    u_to_temp[ptr["len_from"]] = f"_{ptr['len_from']}"
            else:
                u_to_temp[u_name] = f"_{u_name}"
        # inactive ones: zero/null
        for u_name, (u_def, _i_def) in fmap.items():
            if u_name in u_to_temp:
                continue
            shape = u_def.get("shape")
            if isinstance(shape, dict) and "ptr" in shape:
                temps.append(f"    let _{u_name}_ptr = core::ptr::null_mut();")
                ptr = shape["ptr"]
                if ptr.get("kind") == "slice" and "len_from" in ptr:
                    lf = ptr["len_from"]
                    lf_ty = u_field_types.get(lf, None)
                    if lf_ty is None:
                        temps.append(f"    let _{lf} = 0usize;")
                    else:
                        temps.append(f"    let _{lf}: {lf_ty} = 0 as {lf_ty};")
                u_to_temp[u_name] = f"_{u_name}_ptr"
            else:
                cty = u_field_types.get(u_name, None)
                if cty is None:
                    temps.append(f"    let _{u_name} = core::mem::zeroed();")
                else:
                    temps.append(
                        f"    let _{u_name}: {cty} = core::mem::zeroed();")
                u_to_temp[u_name] = f"_{u_name}"
        # ensure tag set to equals value
        equals = v.get("when", {}).get("equals")
        if tag_ty is None:
            temps.append(f"    let _{tag_name} = {equals};")
        else:
            temps.append(
                f"    let _{tag_name}: {tag_ty} = ({equals}) as {tag_ty};")
        # Build struct literal
        temps_body = "\n".join(f"            {ln.lstrip()}" if ln.startswith(
            "    ") else f"            {ln}" for ln in temps)
        struct_fields = []
        # fields order from fmap (spec order)
        for f in fields:
            u_name = (f.get("u_field") or {}).get("name")
            if not u_name:
                return None
            shape = (f.get("u_field") or {}).get("shape")
            if isinstance(shape, dict) and "ptr" in shape:
                struct_fields.append(
                    f"                {u_name}: {u_to_temp.get(u_name)},")
                ptr = shape["ptr"]
                if ptr.get("kind") == "slice" and "len_from" in ptr:
                    lf = ptr["len_from"]
                    struct_fields.append(
                        f"                {lf}: {u_to_temp.get(lf)},")
            else:
                struct_fields.append(
                    f"                {u_name}: {u_to_temp.get(u_name)},")

        struct_body = "\n".join(struct_fields)
        variant_contexts.append(
            {
                "pattern": pat,
                "temps": temps_body.split("\n") if temps_body else [],
                "struct_fields": struct_body.split("\n") if struct_body else [],
            }
        )

    uses = [
        "use core::ptr;",
        "use std::ffi;",
    ]
    context = EnumHarnessContext.create(
        uses=uses,
        struct_name=struct_name,
        idiom_type=i_type,
        tag_field=tag_name,
        to_rust_arms=arms,
        variants=variant_contexts,
    )
    return render_enum_struct_converters(context)


def generate_struct_harness_from_spec_file(
    struct_name: str,
    idiomatic_struct_code: str,
    unidiomatic_struct_code_renamed: str,
    spec_path: str,
) -> Optional[str]:
    spec_data = _load_spec_json(spec_path)
    if spec_data is None:
        return None
    struct_spec = StructSpec.from_dict(spec_data)
    preflight = _preflight_struct_spec(
        struct_name, idiomatic_struct_code, struct_spec)
    if preflight.blocking_todos:
        return _struct_todo_skeleton(struct_name, preflight.i_type, preflight.blocking_todos)

    assert preflight.i_kind in {"struct", "enum"}, "unexpected spec kind"

    if preflight.i_kind == "enum":
        u_field_types = _parse_unidiomatic_struct_field_types(
            struct_name, unidiomatic_struct_code_renamed)
        fields_raw = [mapping.raw for mapping in struct_spec.fields]
        return _generate_enum_struct_converters(
            struct_name,
            preflight.i_type,
            fields_raw,
            struct_spec.variants,
            u_field_types,
        )

    u_field_types = _parse_unidiomatic_struct_field_types(
        struct_name, unidiomatic_struct_code_renamed)
    rendered = _render_struct_harness(
        struct_name, preflight.i_type, struct_spec, preflight, u_field_types)
    if rendered is None:
        return None
    return rendered


def _parse_fn_signature(sig: str):
    if not sig:
        return None
    cleaned = sig.strip()
    if cleaned.endswith(';'):
        cleaned = cleaned[:-1]
    try:
        details = rust_ast_parser.parse_function_signature(cleaned)
    except Exception:
        try:
            details = rust_ast_parser.parse_function_signature(
                f"{cleaned} {{}}")
        except Exception:
            return None
    name = details.get("name")
    params = details.get("params", [])
    ret_info = details.get("return")
    return name, params, ret_info


def generate_function_harness_from_spec_file(
    function_name: str,
    idiomatic_signature: str,
    original_signature_renamed: str,
    struct_dep_names: list[str],
    spec_path: str,
    struct_name_alias: Optional[dict[str, str]] = None,
) -> Optional[str]:
    spec_data = _load_spec_json(spec_path)
    if spec_data is None:
        return None
    spec = FunctionSpec.from_dict(spec_data)
    context = FunctionSpecContext.from_spec(spec)

    parsed_id = _parse_fn_signature(idiomatic_signature)
    parsed_c = _parse_fn_signature(original_signature_renamed)
    if not parsed_id or not parsed_c:
        return None
    _, id_params, id_ret = parsed_id
    _, c_params, c_ret = parsed_c

    id_params = list(id_params or [])
    c_params = list(c_params or [])

    # Build lookup for each parameter in the C signature.
    u_param_map = {
        p.get("name"): p
        for p in c_params
        if isinstance(p, dict) and p.get("name")
    }

    # Establish mapping from idiomatic struct names to their C counterparts.
    alias_map = struct_name_alias or {}
    idiom_names = {alias_map.get(name, name) for name in struct_dep_names}
    c_name_for_idiom: dict[str, str] = {}
    for original in struct_dep_names:
        alias = alias_map.get(original, original)
        c_name_for_idiom.setdefault(alias, original)
    for original, alias in alias_map.items():
        if alias:
            c_name_for_idiom.setdefault(alias, original)

    def c_alias_for(idiom: str) -> str:
        return c_name_for_idiom.get(idiom, idiom)

    arg_plan = _prepare_function_arguments(
        id_params, context, idiom_names, c_alias_for, u_param_map)

    ret_spec = context.by_rust.get("ret")
    id_call_name = parsed_id[0]
    call_args_str = ", ".join(arg_plan.call_args)
    has_id_ret = _has_non_unit_return(id_ret)
    has_ret = bool(c_ret)
    if not has_id_ret and ret_spec is None:
        call_line = f"    {id_call_name}({call_args_str});"
    else:
        call_line = f"    let __ret = {id_call_name}({call_args_str});"

    post_lines = _build_mut_struct_post_lines(arg_plan.mut_struct_params)

    ret_result = _build_function_return_handling(
        ret_spec,
        id_ret,
        c_ret,
        struct_dep_names,
        struct_name_alias,
        c_name_for_idiom,
        u_param_map,
        has_ret,
    )
    if ret_result is None:
        return None
    ret_lines, ret_return_expr = ret_result

    use_lines = _build_function_use_lines(c_params, c_ret)

    header = original_signature_renamed.strip()
    if header.endswith(';'):
        header = header[:-1]
    return_line = [f"    return {ret_return_expr};"] if has_ret else None
    context = FunctionHarnessContext.create(
        uses=use_lines,
        signature=header,
        call_line=call_line,
        pre_lines=arg_plan.pre_lines,
        ret_lines=ret_lines,
        post_lines=post_lines,
        return_line=return_line,
    )
    return render_function_harness(context)
