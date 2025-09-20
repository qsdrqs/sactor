import json
import os
from typing import Optional

from sactor import rust_ast_parser


_TYPE_TRAITS_CACHE: dict[str, dict] = {}


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
                return rust_ast_parser.get_struct_field_types(code)
            return rust_ast_parser.get_struct_field_types(code, candidate)
        except Exception:
            continue
    return {}


def _map_scalar_cast(unidiomatic_ty: str) -> Optional[str]:
    # Map libc c types to Rust primitives for 'as' casting
    m = {
        "libc::c_int": "i32",
        "libc::c_uint": "u32",
        "libc::c_long": "isize",
        "libc::c_ulong": "usize",
        "libc::c_float": "f32",
        "libc::c_double": "f64",
        "i32": "i32",
        "u32": "u32",
        "f32": "f32",
        "f64": "f64",
    }
    return m.get(unidiomatic_ty)


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
    base_traits = {}
    if traits:
        _, base_traits = _pointer_depth_and_base(traits)
        base_traits = _ensure_traits_dict(base_traits)
    if not base_traits:
        base_traits = traits
    base_ident = (base_traits or {}).get('path_ident') or ''
    base_normalized = (base_traits or {}).get('normalized') or (base_traits or {}).get('raw') or ''
    candidate_names = [base_ident, base_normalized]
    expanded = []
    for name in candidate_names:
        if not name:
            continue
        expanded.append(name)
        if '::' in name:
            expanded.append(name.split('::')[-1])
    mapping = {
        "libc::c_char": "u8",
        "libc::c_schar": "i8",
        "libc::c_uchar": "u8",
        "libc::c_float": "f32",
        "libc::c_double": "f64",
        "libc::c_int": "i32",
        "libc::c_uint": "u32",
    }
    for name in expanded:
        if name in mapping:
            return mapping[name]
    for name in expanded:
        if name in {"u8", "i8", "u16", "i16", "u32", "i32", "u64", "i64", "usize", "isize", "f32", "f64"}:
            return name
    if expanded:
        return expanded[0]
    return "u8"


def _infer_option(ty: str) -> bool:
    traits = _get_type_traits(ty)
    if traits:
        return bool(traits.get('is_option'))
    return (ty or "").replace(" ", "").startswith("Option<")


def _extract_box_inner(i_type: str) -> Optional[str]:
    """Return the inner type if the idiomatic field is Box<T> or Option<Box<T>>."""

    def find_box(traits: Optional[dict]) -> Optional[str]:
        info = _ensure_traits_dict(traits)
        if not info:
            return None
        if info.get('is_box'):
            inner = _ensure_traits_dict(info.get('box_inner'))
            raw = inner.get('normalized') or inner.get('raw')
            return raw or None
        if info.get('is_option'):
            return find_box(info.get('option_inner'))
        if info.get('is_reference'):
            return find_box(info.get('reference_inner'))
        return None

    parsed = _get_type_traits(i_type)
    result = find_box(parsed)
    if result:
        return result

    normalized = (parsed or {}).get('normalized') or (i_type or '').replace(' ', '')
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


def _classify_slice_traits(traits: Optional[dict]) -> tuple[bool, bool, Optional[str]]:
    traits = _ensure_traits_dict(traits)
    if not traits:
        return False, False, None
    if traits.get("is_option"):
        is_slice, _ignored_optional, elem = _classify_slice_traits(traits.get("option_inner"))
        if is_slice:
            return True, True, elem
    if traits.get("is_slice"):
        return True, False, traits.get("slice_elem")
    if traits.get("is_reference"):
        return _classify_slice_traits(traits.get("reference_inner"))
    return False, False, None


def _pointer_depth_and_base(traits: Optional[dict]) -> tuple[int, dict]:
    traits_dict = _ensure_traits_dict(traits)
    depth = 0
    current = traits_dict
    while current and current.get("is_pointer"):
        depth += 1
        next_traits = _ensure_traits_dict(current.get("pointer_inner"))
        if not next_traits or next_traits is current:
            return depth, {}
        current = next_traits
    return depth, current


def _has_non_unit_return(ret_traits: Optional[dict]) -> bool:
    traits = _ensure_traits_dict(ret_traits)
    if not traits:
        return False
    normalized = traits.get('normalized') or (traits.get('raw') or "").replace(" ", "")
    return normalized not in {"", "()"}


def _type_pointer_depth(traits: Optional[dict]) -> int:
    depth, _ = _pointer_depth_and_base(traits)
    return depth


def _pointer_base_type(traits: Optional[dict]) -> str:
    _depth, base = _pointer_depth_and_base(traits)
    base_traits = _ensure_traits_dict(base)
    return base_traits.get('normalized') or base_traits.get('path_ident') or base_traits.get('raw') or ''


def _analyze_struct_ptr_conversion(c_ty: str, raw_i_ty: str) -> Optional[dict]:
    """Detect whether a pointer field corresponds to a struct conversion helper.

    Returns a dictionary describing the idiomatic struct name and whether the
    idiomatic side wraps it in Option/Box. The caller can then emit conversions
    using `C{struct}_to_{struct}_mut` / `{struct}_to_C{struct}_mut` helpers.
    """

    c_traits = _get_type_traits(c_ty)
    depth, base_traits = _pointer_depth_and_base(c_traits)
    if depth == 0:
        return None
    base_traits = _ensure_traits_dict(base_traits)
    base_ident = (base_traits.get('path_ident') or base_traits.get('normalized') or '').split('::')[-1]
    if not base_ident:
        return None

    i_traits = _get_type_traits(raw_i_ty)
    info = _ensure_traits_dict(i_traits)

    is_option = bool(info.get('is_option'))
    inner = _ensure_traits_dict(info.get('option_inner') if is_option else info)
    # Strip references
    while inner.get('is_reference'):
        inner = _ensure_traits_dict(inner.get('reference_inner'))

    is_box = bool(inner.get('is_box'))
    if is_box:
        # Existing branch handles Box conversions elsewhere; skip
        return None

    inner_ident = (inner.get('path_ident') or inner.get('normalized') or '').split('::')[-1]
    if not inner_ident:
        return None

    # Accept either exact match or C-prefixed base name.
    c_ident = base_ident
    if c_ident == inner_ident:
        # Already the same name (rare, but preserve for completeness)
        pass
    elif c_ident == f"C{inner_ident}":
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


def _struct_todo_skeleton(struct_name: str, todos: list[str]) -> str:
    todo_header = "\n".join(
        ["// TODO: Spec exceeds automatic rules. Items to handle manually:"]
        + [f"// TODO: {t}" for t in todos]
    )
    return f"""{todo_header}
unsafe fn {struct_name}_to_C{struct_name}_mut(input: &mut {struct_name}) -> *mut C{struct_name} {{
    // TODO: implement I->U conversion based on above items
    unimplemented!()
}}

unsafe fn C{struct_name}_to_{struct_name}_mut(input: *mut C{struct_name}) -> &'static mut {struct_name} {{
    // TODO: implement U->I conversion based on above items
    unimplemented!()
}}
"""


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
        return f"c.{name}"
    if not isinstance(shape, dict) or "ptr" not in shape:
        return None
    ptr = shape["ptr"]
    kind = ptr.get("kind")
    if kind == "cstring":
        is_opt = _infer_option(i_ty)
        if is_opt or ptr.get("null") == "nullable":
            return f"""if !c.{name}.is_null() {{
                Some(unsafe {{ std::ffi::CStr::from_ptr(c.{name}) }}.to_string_lossy().into_owned())
            }} else {{
                None
            }}"""
        else:
            return f"""if !c.{name}.is_null() {{
                unsafe {{ std::ffi::CStr::from_ptr(c.{name}) }}.to_string_lossy().into_owned()
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
                le = f"(c.{ptr['len_from']} as usize)"
            elif "len_const" in ptr:
                le = f"{int(ptr['len_const'])}usize"
            else:
                return None
        base = f"unsafe {{ std::slice::from_raw_parts(c.{name} as *const {elem}, {le}) }}.to_vec()"
        if is_opt or ptr.get("null") == "nullable":
            return f"""if !c.{name}.is_null() && {le} > 0 {{
                Some({base})
            }} else {{
                None
            }}"""
        else:
            return f"""if !c.{name}.is_null() && {le} > 0 {{
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
                    out.append(f"    let _{lf} = {i_expr}.as_ref().map(|v| v.len()).unwrap_or(0) as usize;")
                else:
                    out.append(f"    let _{lf}: {lf_ty} = ({i_expr}.as_ref().map(|v| v.len()).unwrap_or(0) as usize) as {lf_ty};")
            else:
                if lf_ty is None:
                    out.append(f"    let _{lf} = {i_expr}.len() as usize;")
                else:
                    out.append(f"    let _{lf}: {lf_ty} = ({i_expr}.len() as usize) as {lf_ty};")
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
    # U -> I(Enum): match on c.tag and build i_type::Variant(args)
    arms: list[str] = []
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
        arms.append(f"        {equals} => {variant_expr},")

    match_arms = "\n".join(arms)
    enum_to_rust = f"""unsafe fn C{struct_name}_to_{i_type}_mut(input: *mut C{struct_name}) -> &'static mut {i_type} {{
    assert!(!input.is_null());
    let c = &*input;
    let r = match c.{tag_name} {{
{match_arms}
        _ => panic!(\"unsupported tag value\"),
    }};
    Box::leak(Box::new(r))
}}"""

    # I(Enum) -> U: match on r and build all fields
    # For inactive fields, zero/null them; write tag to equals
    variant_blocks: list[str] = []
    for v in variants:
        vname = v.get("name")
        payload = v.get("payload") or []
        # arity from payload count
        arity = len(payload)
        binders = ", ".join([f"v{idx}" for idx in range(arity)])
        pat = f"{i_type}::{vname}" + (f"({binders})" if arity > 0 else "")
        to_c.append(f"        {pat} => {{")
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
                    temps.append(f"    let _{u_name}: {cty} = core::mem::zeroed();")
                u_to_temp[u_name] = f"_{u_name}"
        # ensure tag set to equals value
        equals = v.get("when", {}).get("equals")
        if tag_ty is None:
            temps.append(f"    let _{tag_name} = {equals};")
        else:
            temps.append(f"    let _{tag_name}: {tag_ty} = ({equals}) as {tag_ty};")
        # Build struct literal
        temps_body = "\n".join(f"            {ln.lstrip()}" if ln.startswith("    ") else f"            {ln}" for ln in temps)
        struct_fields = []
        # fields order from fmap (spec order)
        for f in fields:
            u_name = (f.get("u_field") or {}).get("name")
            if not u_name:
                return None
            shape = (f.get("u_field") or {}).get("shape")
            if isinstance(shape, dict) and "ptr" in shape:
                struct_fields.append(f"                {u_name}: {u_to_temp.get(u_name)},")
                ptr = shape["ptr"]
                if ptr.get("kind") == "slice" and "len_from" in ptr:
                    lf = ptr["len_from"]
                    struct_fields.append(f"                {lf}: {u_to_temp.get(lf)},")
            else:
                struct_fields.append(f"                {u_name}: {u_to_temp.get(u_name)},")

        struct_body = "\n".join(struct_fields)
        block_lines = [f"        {pat} => {{"]
        if temps_body:
            block_lines.append(temps_body)
        block_lines.append(f"            C{struct_name} {{")
        block_lines.append(struct_body)
        block_lines.append("            }")
        block_lines.append("        },")
        variant_blocks.append("\n".join(block_lines))

    variant_block_text = "\n".join(variant_blocks)
    enum_to_c = f"""unsafe fn {i_type}_to_C{struct_name}_mut(r: &mut {i_type}) -> *mut C{struct_name} {{
    let c = match r {{
{variant_block_text}
        _ => panic!(\"unsupported variant\"),
    }};
    Box::into_raw(Box::new(c))
}}"""

    uses = [
        "use core::ptr;",
        "use std::ffi;",
    ]
    return "\n".join(uses + [enum_to_rust, enum_to_c])


def generate_struct_harness_from_spec_file(
    struct_name: str,
    idiomatic_struct_code: str,
    unidiomatic_struct_code_renamed: str,
    spec_path: str,
) -> Optional[str]:
    if not os.path.exists(spec_path):
        return None
    try:
        with open(spec_path, "r") as f:
            spec = json.load(f)
    except Exception:
        return None
    fields = spec.get("fields", [])
    i_kind = (spec.get("i_kind") or "struct").lower()
    i_type = spec.get("i_type") or struct_name
    blocking_todos: list[str] = []
    derived_len_i_fields: set[str] = set()
    derived_len_c_fields: set[str] = set()

    if i_kind == "enum":
        # Only support flat field names for now
        for f in fields:
            u = f.get("u_field", {}) or {}
            if "." in (u.get("name") or ""):
                blocking_todos.append(f"enum: nested field path not supported: {u.get('name')}")
        u_field_types = _parse_unidiomatic_struct_field_types(struct_name, unidiomatic_struct_code_renamed)
        if blocking_todos:
            return _struct_todo_skeleton(struct_name, blocking_todos)
        return _generate_enum_struct_converters(struct_name, i_type, fields, spec.get("variants") or [], u_field_types)
    # Only support flat i_field (no dot) in this first cut
    for f in fields:
        u = f.get("u_field", {})
        i = f.get("i_field", {})
        c_name = (u.get("name") or "")
        i_name = (i.get("name") or "")
        if "." in c_name:
            blocking_todos.append(f"nested field path not supported: u={c_name} i={i_name}")
            continue
        if "." in i_name:
            base, _, suffix = i_name.partition(".")
            if suffix == "len" and base:
                derived_len_i_fields.add(i_name)
                if c_name:
                    derived_len_c_fields.add(c_name)
                continue
            blocking_todos.append(f"nested field path not supported: u={c_name} i={i_name}")

    u_field_types = _parse_unidiomatic_struct_field_types(struct_name, unidiomatic_struct_code_renamed)

    if blocking_todos:
        return _struct_todo_skeleton(struct_name, blocking_todos)

    # Build U->I initializers
    init_lines: list[str] = []
    field_comment_indent = " " * 12
    for f in fields:
        u = f.get("u_field", {})
        i = f.get("i_field", {})
        c_field = u.get("name")
        rust_path = i.get("name")
        shape = u.get("shape")
        # Prefer the post-renamed type recovered from the actual unidiomatic code.
        # Specs may still mention the pre-rename name (e.g. `*mut Course`),
        # which would cause type mismatches once the struct is renamed to `C{Course}`.
        c_ty = u_field_types.get(c_field, u.get("type") or "")

        if not c_field or not rust_path:
            msg = f"missing field mapping: u={c_field} i={rust_path}"
            init_lines.append(f"{field_comment_indent}// TODO: {msg}")
            continue

        init_lines.append(
            f"{field_comment_indent}// Field '{c_field}' -> '{rust_path}' (C -> idiomatic)"
        )

        if rust_path in derived_len_i_fields:
            init_lines.append(
                f"{field_comment_indent}// Derived field '{rust_path}' computed via slice metadata"
            )
            continue

        if isinstance(shape, str) and shape == "scalar":
            cast_ty = _map_scalar_cast(c_ty)
            if cast_ty:
                init_lines.append(f"            {rust_path}: c.{c_field} as {cast_ty},")
            else:
                init_lines.append(f"            {rust_path}: c.{c_field},")
            continue

        if not isinstance(shape, dict) or "ptr" not in shape:
            msg = f"unsupported shape for field {c_field}"
            init_lines.append(f"{field_comment_indent}// TODO: {msg}")
            continue

        ptr_meta = shape["ptr"]
        kind = ptr_meta.get("kind")
        raw_i_ty = i.get("type") or ""
        i_ty = raw_i_ty.replace(" ", "")
        struct_ptr = None
        if kind == "ref":
            struct_ptr = _analyze_struct_ptr_conversion(c_ty, raw_i_ty)

        if struct_ptr:
            conv_name = f"C{struct_ptr['idiom_ident']}_to_{struct_ptr['idiom_ident']}_mut"
            ptr_expr = f"c.{c_field} as *mut C{struct_ptr['idiom_ident']}"
            if struct_ptr['is_option']:
                init_lines.append(
                    f"""            {rust_path}: if !c.{c_field}.is_null() {{
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
            null_mode = ptr_meta.get("null", "empty")
            if is_opt or null_mode == "none":
                init_lines.append(
                    f"""            {rust_path}: if !c.{c_field}.is_null() {{
                Some(unsafe {{ std::ffi::CStr::from_ptr(c.{c_field}) }}.to_string_lossy().into_owned())
            }} else {{
                None
            }},""".rstrip()
                )
            else:
                init_lines.append(
                    f"""            {rust_path}: if !c.{c_field}.is_null() {{
                unsafe {{ std::ffi::CStr::from_ptr(c.{c_field}) }}.to_string_lossy().into_owned()
            }} else {{
                String::new()
            }},""".rstrip()
                )
            continue

        if kind in ("slice", "ref"):
            len_expr = None
            if kind == "ref":
                len_expr = "1usize"
            else:
                if "len_from" in ptr_meta:
                    len_expr = f"(c.{ptr_meta['len_from']} as usize)"
                elif "len_const" in ptr_meta:
                    len_expr = f"{int(ptr_meta['len_const'])}usize"
            elem = _infer_slice_elem_from_ptr_ty(c_ty)
            is_opt = i_ty.startswith("Option<")
            box_inner = _extract_box_inner(raw_i_ty)
            if kind == "ref" and box_inner:
                conv_name = f"C{box_inner}_to_{box_inner}_mut"
                if is_opt:
                    init_lines.append(
                        f"""            {rust_path}: if !c.{c_field}.is_null() {{
                Some(Box::new(unsafe {{ {conv_name}(c.{c_field}) }}.clone()))
            }} else {{
                None
            }},""".rstrip()
                    )
                else:
                    init_lines.append(
                        f"""            {rust_path}: {{
                let tmp = unsafe {{ {conv_name}(c.{c_field}) }};
                Box::new((*tmp).clone())
            }},""".rstrip()
                    )
                continue

            null_mode = ptr_meta.get("null", "empty")
            le_render = len_expr or "0usize"
            if is_opt or null_mode == "none":
                init_lines.append(
                    f"""            {rust_path}: if !c.{c_field}.is_null() && {le_render} > 0 {{
                Some(unsafe {{ std::slice::from_raw_parts(c.{c_field} as *const {elem}, {le_render}) }}.to_vec())
            }} else {{
                None
            }},""".rstrip()
                )
            else:
                init_lines.append(
                    f"""            {rust_path}: if !c.{c_field}.is_null() && {le_render} > 0 {{
                unsafe {{ std::slice::from_raw_parts(c.{c_field} as *const {elem}, {le_render}) }}.to_vec()
            }} else {{
                Vec::<{elem}>::new()
            }},""".rstrip()
                )
            continue

        msg = f"unsupported ptr kind for field {c_field}"
        init_lines.append(f"{field_comment_indent}// TODO: {msg}")

    # Even if no conversions are required, we still emit a harness body.

    # Build I->U assignments (new allocation per spec by design)
    back_lines: list[str] = []
    for f in fields:
        u = f.get("u_field", {})
        i = f.get("i_field", {})
        c_field = u.get("name")
        rust_path = i.get("name")
        shape = u.get("shape")
        c_ty = u_field_types.get(c_field, u.get("type") or "")

        if (rust_path in derived_len_i_fields) or (c_field in derived_len_c_fields):
            continue

        if not c_field or not rust_path:
            msg = f"missing field mapping: u={c_field} i={rust_path}"
            back_lines.append(f"    // TODO: {msg}")
            continue

        back_lines.append(
            f"    // Field '{rust_path}' -> '{c_field}' (idiomatic -> C)"
        )

        if isinstance(shape, str) and shape == "scalar":
            back_lines.append(f"    let _{c_field} = r.{rust_path};")
            continue

        if not isinstance(shape, dict) or "ptr" not in shape:
            msg = f"unsupported shape for field {c_field}"
            back_lines.append(f"    // TODO: {msg}")
            continue

        ptr_meta = shape["ptr"]
        kind = ptr_meta.get("kind")
        raw_i_ty = i.get("type") or ""
        i_ty = raw_i_ty.replace(" ", "")
        struct_ptr = None
        if kind == "ref":
            struct_ptr = _analyze_struct_ptr_conversion(c_ty, raw_i_ty)

        if struct_ptr:
            conv_back = f"{struct_ptr['idiom_ident']}_to_C{struct_ptr['idiom_ident']}_mut"
            if struct_ptr['is_option']:
                back_lines.append(
                    f"""    let _{c_field}_ptr: {c_ty} = match r.{rust_path}.as_mut() {{
        Some(v) => unsafe {{ {conv_back}(v) }},
        None => core::ptr::null_mut(),
    }};""".rstrip()
                )
            else:
                back_lines.append(
                    f"""    let _{c_field}_ptr: {c_ty} = unsafe {{ {conv_back}(&mut r.{rust_path}) }};""".rstrip()
                )
            continue

        if kind == "cstring":
            is_opt = i_ty.startswith("Option<")
            if is_opt:
                back_lines.append(
                    f"""    let _{c_field}_ptr: *mut libc::c_char = match r.{rust_path}.clone() {{
        Some(s) => {{
            let s = std::ffi::CString::new(s)
                .unwrap_or_else(|_| std::ffi::CString::new("").unwrap());
            s.into_raw()
        }},
        None => core::ptr::null_mut(),
    }};""".rstrip()
                )
            else:
                back_lines.append(
                    f"""    let _{c_field}_ptr: *mut libc::c_char = {{
        let s = std::ffi::CString::new(r.{rust_path}.clone())
            .unwrap_or_else(|_| std::ffi::CString::new("").unwrap());
        s.into_raw()
    }};""".rstrip()
                )
            continue

        raw_i_ty = i.get("type") or ""
        i_ty = raw_i_ty.replace(" ", "")
        if kind == "ref" and (box_inner := _extract_box_inner(raw_i_ty)):
            conv = f"{box_inner}_to_C{box_inner}_mut"
            if _infer_option(i_ty):
                back_lines.append(
                    f"""    let _{c_field}_ptr: {c_ty} = match r.{rust_path}.as_mut() {{
        Some(v) => {conv}(v.as_mut()),
        None => core::ptr::null_mut(),
    }};""".rstrip()
                )
            else:
                back_lines.append(
                    f"""    let _{c_field}_ptr: {c_ty} = {conv}(r.{rust_path}.as_mut());""".rstrip()
                )
            continue

        elem = _infer_slice_elem_from_ptr_ty(c_ty)
        is_opt = i_ty.startswith("Option<")
        if kind in ("slice", "ref"):
            if is_opt:
                back_lines.append(
                    f"""    let _{c_field}_ptr: *mut {elem} = match r.{rust_path}.as_ref() {{
        Some(v) => if v.is_empty() {{
            core::ptr::null_mut()
        }} else {{
            let mut boxed = v.clone().into_boxed_slice();
            let ptr = boxed.as_mut_ptr();
            core::mem::forget(boxed);
            ptr
        }},
        None => core::ptr::null_mut(),
    }};""".rstrip()
                )
            else:
                back_lines.append(
                    f"""    let _{c_field}_ptr: *mut {elem} = if r.{rust_path}.is_empty() {{
        core::ptr::null_mut()
    }} else {{
        let mut boxed = r.{rust_path}.clone().into_boxed_slice();
        let ptr = boxed.as_mut_ptr();
        core::mem::forget(boxed);
        ptr
    }};""".rstrip()
                )

            if kind == "slice" and "len_from" in ptr_meta:
                lf = ptr_meta['len_from']
                lf_ty = u_field_types.get(lf, None)
                if is_opt:
                    if lf_ty is None:
                        back_lines.append(f"    let _{lf} = r.{rust_path}.as_ref().map(|v| v.len()).unwrap_or(0) as usize;")
                    else:
                        back_lines.append(f"    let _{lf}: {lf_ty} = (r.{rust_path}.as_ref().map(|v| v.len()).unwrap_or(0) as usize) as {lf_ty};")
                else:
                    if lf_ty is None:
                        back_lines.append(f"    let _{lf} = r.{rust_path}.len() as usize;")
                    else:
                        back_lines.append(f"    let _{lf}: {lf_ty} = (r.{rust_path}.len() as usize) as {lf_ty};")
            continue

        msg = f"unsupported ptr kind for field {c_field}"
        back_lines.append(f"    // TODO: {msg}")

    # Compose functions
    to_rust = [
        f"unsafe fn C{struct_name}_to_{struct_name}_mut(input: *mut C{struct_name}) -> &'static mut {struct_name} {{",
        "    assert!(!input.is_null());",
        "    let c = &*input;",
    ]
    # Add per-field asserts for forbidden NULL pointers
    for f in fields:
        u = f.get("u_field", {})
        shape = u.get("shape")
        c_field = u.get("name")
        if isinstance(shape, dict) and shape.get("ptr", {}).get("null") == "forbidden":
            to_rust.append(f"    assert!(!c.{c_field}.is_null());")

    to_rust.append(f"    let r = {struct_name} {{")
    to_rust.extend(init_lines)
    to_rust.append("    };")
    to_rust.append("    Box::leak(Box::new(r))")
    to_rust.append("}")

    # Build U struct literal
    c_fields_init = []
    for f in fields:
        u = f.get("u_field", {})
        c_field = u.get("name")
        shape = u.get("shape")
        i_field_info = f.get("i_field") or {}
        i_name = i_field_info.get("name")
        if i_name in derived_len_i_fields or c_field in derived_len_c_fields:
            continue
        if isinstance(shape, str) and shape == "scalar":
            c_fields_init.append(f"        {c_field}: _{c_field},")
        elif isinstance(shape, dict) and "ptr" in shape:
            kind = shape["ptr"].get("kind")
            if kind == "cstring":
                c_fields_init.append(f"        {c_field}: _{c_field}_ptr,")
            elif kind in ("slice", "ref"):
                c_fields_init.append(f"        {c_field}: _{c_field}_ptr,")
                ptr = shape["ptr"]
                if kind == "slice" and "len_from" in ptr:
                    c_fields_init.append(f"        {ptr['len_from']}: _{ptr['len_from']},")
            else:
                return None
        else:
            return None
    back_block = "\n".join(back_lines)
    if back_block:
        back_block = f"{back_block}\n"
    struct_literal = "\n".join(c_fields_init)
    to_c_code = f"""unsafe fn {struct_name}_to_C{struct_name}_mut(r: &mut {struct_name}) -> *mut C{struct_name} {{
{back_block}    let c = C{struct_name} {{
{struct_literal}
    }};
    Box::into_raw(Box::new(c))
}}"""
    to_c = [to_c_code]

    uses = [
        "use core::ptr;",
        "use std::ffi;",
    ]

    return "\n".join(uses + to_rust + to_c)


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
            details = rust_ast_parser.parse_function_signature(f"{cleaned} {{}}")
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
) -> Optional[str]:
    if not os.path.exists(spec_path):
        return None
    try:
        with open(spec_path, 'r') as f:
            spec = json.load(f)
    except Exception:
        return None
    fields = spec.get("fields", [])
    # Build lookup by idiomatic arg name and unidiomatic name
    by_rust: dict[str, dict] = {}
    by_u: dict[str, dict] = {}
    for f in fields:
        i = f.get('i_field', {}) or {}
        u = f.get('u_field', {}) or {}
        by_rust[i.get('name', '')] = f
        by_u[u.get('name', '')] = f

    parsed_id = _parse_fn_signature(idiomatic_signature)
    parsed_c = _parse_fn_signature(original_signature_renamed)
    if not parsed_id or not parsed_c:
        return None
    _, id_params, id_ret = parsed_id
    c_name, c_params, c_ret = parsed_c

    id_params = list(id_params or [])
    c_params = list(c_params or [])

    # helper maps for unidiomatic (U) params
    u_param_map = {
        p.get('name'): p
        for p in c_params
        if isinstance(p, dict) and p.get('name')
    }

    scalar_types = {"i32", "u32", "i64", "u64", "f32", "f64", "usize", "isize"}

    # Generate builders for idiomatic args
    pre_lines: list[str] = []
    call_args: list[str] = []
    mut_struct_params: list[dict[str, str]] = []

    for param in id_params:
        pname = (param or {}).get('name')
        if not pname:
            pre_lines.append("    // TODO: parameter without name in idiomatic signature")
            call_args.append("/* TODO unnamed param */")
            continue

        traits = _ensure_traits_dict((param or {}).get('traits'))
        raw_type = (param or {}).get('type') or traits.get('raw') or ""
        norm_type = traits.get('normalized') or raw_type.replace(' ', '')

        spec_entry = by_rust.get(pname) or {}
        u_field = spec_entry.get('u_field', {}) or {}
        u_name = u_field.get('name') or pname
        u_shape = u_field.get('shape')
        u_param_info = u_param_map.get(u_name, {})

        c_type_for_param = (
            u_param_info.get('type') if isinstance(u_param_info, dict) else None
        ) or u_field.get('type') or ""

        if norm_type in struct_dep_names and not traits.get('is_reference'):
            struct_ptr = _analyze_struct_ptr_conversion(c_type_for_param, raw_type)
            if struct_ptr and struct_ptr['idiom_ident'] == norm_type:
                pre_lines.append(
                    f"    // Arg '{pname}': convert {c_type_for_param or '*mut _'} to {norm_type}"
                )
                pre_lines.append(f"    assert!(!{u_name}.is_null());")
                pre_lines.append(
                    f"    let mut {pname}_ref: &'static mut {norm_type} = unsafe {{ C{norm_type}_to_{norm_type}_mut({u_name}) }};"
                )
                pre_lines.append(
                    f"    let {pname}_val: {norm_type} = {pname}_ref.clone();"
                )
                call_args.append(f"{pname}_val")
                continue
            else:
                msg = f"param {pname}: unsupported struct conversion"
                pre_lines.append(f"    // TODO: {msg}")
                call_args.append(f"/* TODO {pname} */")
                continue

        # &mut struct parameters
        if traits.get('is_option'):
            option_inner = _ensure_traits_dict(traits.get('option_inner'))
            if option_inner.get('is_reference') and option_inner.get('is_mut_reference'):
                inner = _ensure_traits_dict(option_inner.get('reference_inner'))
                inner_name = inner.get('path_ident') or inner.get('normalized') or inner.get('raw') or ''
                if inner_name in struct_dep_names:
                    pre_lines.append(
                        f"""    // Arg '{pname}': optional *mut {inner_name} to Option<&mut {inner_name}>
    let mut {pname}_storage: Option<&'static mut {inner_name}> = if !{u_name}.is_null() {{
        Some(unsafe {{ C{inner_name}_to_{inner_name}_mut({u_name}) }})
    }} else {{
        None
    }};"""
                    )
                    call_args.append(f"{pname}_storage.as_deref_mut()")
                    mut_struct_params.append(
                        {
                            "mode": "option_mut_struct",
                            "storage_var": f"{pname}_storage",
                            "struct_name": inner_name,
                            "u_name": u_name,
                            "param_name": pname,
                        }
                    )
                    continue

        if traits.get('is_reference') and traits.get('is_mut_reference'):
            inner = _ensure_traits_dict(traits.get('reference_inner'))
            inner_name = inner.get('path_ident') or inner.get('normalized') or inner.get('raw') or ''
            if inner_name in struct_dep_names:
                if u_name not in u_param_map:
                    msg = f"&mut {inner_name}: cannot find matching U param"
                    pre_lines.append(f"    // TODO: {msg}")
                    call_args.append(f"/* TODO &mut {inner_name} */")
                else:
                    pre_lines.append(
                        f"""    // Arg '{pname}': convert *mut {inner_name} to &mut {inner_name}
    let mut {pname}: &'static mut {inner_name} = unsafe {{ C{inner_name}_to_{inner_name}_mut({u_name}) }};
    // will copy back after call for {pname}"""
                    )
                    call_args.append(pname)
                    mut_struct_params.append(
                        {
                            "mode": "direct_mut_struct",
                            "param_name": pname,
                            "struct_name": inner_name,
                            "u_name": u_name,
                        }
                    )
                continue

            ptr_meta = (u_shape or {}).get('ptr', {}) or {}
            if ptr_meta.get('kind') == 'ref':
                inner_ty = inner.get('normalized') or inner.get('path_ident') or inner.get('raw') or raw_type.replace('&mut', '').strip()
                if ptr_meta.get('null') == 'forbidden':
                    pre_lines.append(
                        f"    // Arg '{pname}': convert *mut {inner_ty} to &mut {inner_ty}"
                    )
                    pre_lines.append(f"    assert!(!{u_name}.is_null());")
                    pre_lines.append(
                        f"    let {pname}_ref: &'static mut {inner_ty} = unsafe {{ &mut *{u_name} }};"
                    )
                    call_args.append(f"{pname}_ref")
                    continue
                else:
                    msg = f"param {pname}: nullable mutable pointer conversion unsupported"
                    pre_lines.append(f"    // TODO: {msg}")
                    call_args.append(f"/* TODO {pname} */")
                    continue

        # slice parameters (&[T], Option<&[T]>)
        is_slice, is_slice_optional, slice_elem = _classify_slice_traits(traits)
        if is_slice:
            if not isinstance(u_shape, dict):
                msg = f"slice arg {pname}: missing spec mapping"
                pre_lines.append(f"    // TODO: {msg}")
                call_args.append(f"/* TODO slice {pname} */")
                continue
            ptr_meta = (u_shape or {}).get('ptr', {}) or {}
            if ptr_meta.get('kind') != 'slice':
                msg = f"slice arg {pname}: spec.kind is not slice"
                pre_lines.append(f"    // TODO: {msg}")
                call_args.append(f"/* TODO slice {pname} */")
                continue
            c_ptr_name = u_name
            len_from = ptr_meta.get('len_from')
            if len_from and len_from in u_param_map:
                len_expr = f"{len_from} as usize"
            elif 'len_const' in ptr_meta:
                len_expr = f"{int(ptr_meta['len_const'])}usize"
            else:
                msg = f"slice arg {pname}: need len_from or len_const"
                pre_lines.append(f"    // TODO: {msg}")
                call_args.append(f"/* TODO slice {pname} */")
                continue
            elem = (slice_elem or '').replace(' ', '') or _infer_slice_elem_from_ptr_ty(u_field.get('type') or "")
            if is_slice_optional:
                pre_lines.append(
                    f"    // Arg '{pname}': optional slice from {c_ptr_name} with len {len_expr}"
                )
                pre_lines.append(
                    f"""    let {pname}_opt: Option<&[{elem}]> = if !{c_ptr_name}.is_null() && {len_expr} > 0 {{
        Some(unsafe {{ std::slice::from_raw_parts({c_ptr_name} as *const {elem}, {len_expr}) }})
    }} else {{
        None
    }};""".rstrip()
                )
                call_args.append(f"{pname}_opt")
            else:
                pre_lines.append(
                    f"    // Arg '{pname}': slice from {c_ptr_name} with len {len_expr}"
                )
                pre_lines.append(
                    f"""    let {pname}: &[{elem}] = unsafe {{ std::slice::from_raw_parts({c_ptr_name} as *const {elem}, {len_expr}) }};""".rstrip()
                )
                call_args.append(pname)
            continue

        # string-like parameters
        string_kind = _classify_string_traits(traits)
        if string_kind in {"owned", "borrowed", "option_owned", "option_borrowed"}:
            if not isinstance(u_shape, dict):
                msg = f"string arg {pname}: missing spec mapping"
                pre_lines.append(f"    // TODO: {msg}")
                call_args.append(f"/* TODO string {pname} */")
                continue
            ptr_meta = (u_shape or {}).get('ptr', {}) or {}
            if ptr_meta.get('kind') != 'cstring':
                msg = f"string arg {pname}: spec.kind is not cstring"
                pre_lines.append(f"    // TODO: {msg}")
                call_args.append(f"/* TODO string {pname} */")
                continue
            c_ptr_name = u_name
            if string_kind in {"option_owned", "option_borrowed"}:
                pre_lines.append(
                    f"    // Arg '{pname}': optional C string at {c_ptr_name}"
                )
                pre_lines.append(
                    f"""    let {pname}_opt = if !{c_ptr_name}.is_null() {{
        Some(unsafe {{ std::ffi::CStr::from_ptr({c_ptr_name}) }}.to_string_lossy().into_owned())
    }} else {{
        None
    }};""".rstrip()
                )
                if string_kind == 'option_borrowed':
                    call_args.append(f"{pname}_opt.as_deref()")
                else:
                    call_args.append(f"{pname}_opt")
            elif string_kind == 'owned':
                pre_lines.append(
                    f"    // Arg '{pname}': C string at {c_ptr_name}"
                )
                pre_lines.append(
                    f"""    let {pname}_str = if !{c_ptr_name}.is_null() {{
        unsafe {{ std::ffi::CStr::from_ptr({c_ptr_name}) }}.to_string_lossy().into_owned()
    }} else {{
        String::new()
    }};""".rstrip()
                )
                call_args.append(f"{pname}_str")
            else:  # borrowed
                pre_lines.append(
                    f"    // Arg '{pname}': borrowed C string at {c_ptr_name}"
                )
                pre_lines.append(
                    f"""    let {pname}_str = if !{c_ptr_name}.is_null() {{
        unsafe {{ std::ffi::CStr::from_ptr({c_ptr_name}) }}.to_string_lossy().into_owned()
    }} else {{
        String::new()
    }};""".rstrip()
                )
                call_args.append(f"&{pname}_str")
            continue

        # scalar parameters
        if norm_type in scalar_types:
            if not spec_entry and u_name not in u_param_map:
                msg = f"scalar arg {pname}: missing in U signature"
                pre_lines.append(f"    // TODO: {msg}")
                call_args.append(f"/* TODO scalar {pname} */")
            else:
                call_args.append(u_name)
            continue

        # unsupported param type
        msg = f"param {pname} of type {raw_type}: unsupported mapping"
        pre_lines.append(f"    // TODO: {msg}")
        call_args.append(f"/* TODO param {pname} */")

    # Build call
    ret_spec = by_rust.get('ret')
    id_call_name = parsed_id[0]
    call_args_str = ", ".join(call_args)
    has_id_ret = _has_non_unit_return(id_ret)
    if not has_id_ret and not ret_spec:
        call_line = f"    {id_call_name}({call_args_str});"
    else:
        call_line = f"    let __ret = {id_call_name}({call_args_str});"

    # Copy back for &mut struct params
    post_lines: list[str] = []
    for entry in mut_struct_params:
        mode = entry.get('mode')
        struct_name = entry.get('struct_name')
        u_name = entry.get('u_name')
        param_name = entry.get('param_name')
        tmp_var = f"__c_{param_name}"
        if mode == 'direct_mut_struct':
            post_lines.append(
                f"""    if !{u_name}.is_null() {{
        let {tmp_var} = unsafe {{ {struct_name}_to_C{struct_name}_mut({param_name}) }};
        unsafe {{ *{u_name} = *{tmp_var}; }}
        unsafe {{ let _ = Box::from_raw({tmp_var}); }}
    }}"""
            )
        elif mode == 'option_mut_struct':
            storage_var = entry.get('storage_var')
            post_lines.append(
                f"""    if !{u_name}.is_null() {{
        if let Some(inner) = {storage_var}.as_deref_mut() {{
            let {tmp_var} = unsafe {{ {struct_name}_to_C{struct_name}_mut(inner) }};
            unsafe {{ *{u_name} = *{tmp_var}; }}
            unsafe {{ let _ = Box::from_raw({tmp_var}); }}
        }}
    }}"""
            )
        else:
            post_lines.append(f"    // TODO: unsupported post-call conversion for {param_name}")

    # Handle idiomatic return mapping to unidiomatic outputs via spec (i_field.name == 'ret')
    ret_spec = by_rust.get('ret')
    ret_lines: list[str] = []
    if ret_spec:
        u = ret_spec.get('u_field', {}) or {}
        i = ret_spec.get('i_field', {}) or {}
        shape = u.get('shape')
        u_name = u.get('name')
        u_param_info = u_param_map.get(u_name, {})
        u_traits = _type_traits_from_param(u_param_info)
        if isinstance(shape, str) and shape == 'scalar':
            # If original expects a return, we just passthrough below; if void and scalar out is requested, we require *mut T param to write into
            if not c_ret:
                if _type_pointer_depth(u_traits) >= 1:
                    ret_lines.append(
                        f"""    if !{u_name}.is_null() {{
        unsafe {{ *{u_name} = __ret; }}
    }};"""
                    )
                else:
                    return None
        elif isinstance(shape, dict) and 'ptr' in shape:
            kind = shape['ptr'].get('kind')
            c_ret_ty = (
                u_param_info.get('type') if isinstance(u_param_info, dict) else None
            ) or u.get('type') or ''
            struct_ret = _analyze_struct_ptr_conversion(c_ret_ty, i.get('type') or '')
            if struct_ret and struct_ret['idiom_ident'] in struct_dep_names:
                ret_lines.append(
                    f"""    if !{u_name}.is_null() {{
        let mut __ret_clone = __ret.clone();
        let ret_ptr = unsafe {{ {struct_ret['idiom_ident']}_to_C{struct_ret['idiom_ident']}_mut(&mut __ret_clone) }};
        unsafe {{ *{u_name} = *ret_ptr; }}
        unsafe {{ let _ = Box::from_raw(ret_ptr); }}
    }};""".rstrip()
                )
            elif kind == 'ref':
                if _type_pointer_depth(u_traits) >= 1:
                    ret_lines.append(
                        f"""    if !{u_name}.is_null() {{
        unsafe {{ *{u_name} = __ret; }}
    }};"""
                    )
                else:
                    return None
            elif kind == 'cstring':
                if _type_pointer_depth(u_traits) < 2:
                    return None
                ret_lines.append(
                    """    let __ret_cstr: *mut libc::c_char = {
        let s = std::ffi::CString::new(__ret)
            .unwrap_or_else(|_| std::ffi::CString::new("").unwrap());
        s.into_raw()
    };""".rstrip()
                )
                ret_lines.append(
                    f"""    if !{u_name}.is_null() {{
        unsafe {{ *{u_name} = __ret_cstr; }}
    }};"""
                )
            elif kind == 'slice':
                ptr_meta = shape['ptr']
                len_from = ptr_meta.get('len_from')
                if not len_from:
                    return None
                if _type_pointer_depth(u_traits) < 2:
                    return None
                len_param_info = u_param_map.get(len_from, {})
                len_traits = _type_traits_from_param(len_param_info)
                if _type_pointer_depth(len_traits) < 1:
                    return None
                elem_raw = _pointer_base_type(u_traits) or 'u8'
                elem = elem_raw or 'u8'
                ret_lines.append(
                    f"""    let __ret_vec = __ret;
    let __ret_ptr: *mut {elem} = if __ret_vec.is_empty() {{
        core::ptr::null_mut()
    }} else {{
        let mut boxed = __ret_vec.clone().into_boxed_slice();
        let ptr = boxed.as_mut_ptr();
        core::mem::forget(boxed);
        ptr
    }};

    if !{u_name}.is_null() {{
        unsafe {{ *{u_name} = __ret_ptr; }}
    }};

    if !{len_from}.is_null() {{
        unsafe {{ *{len_from} = (__ret_vec.len() as usize) as _; }}
    }};""".rstrip()
                )
            else:
                return None

    # Return handling (simple): if original has return, return __ret; else omit
    has_ret = bool(c_ret)

    body = []
    body.append("{")

    body.extend(pre_lines)
    body.append(call_line)
    # If we synthesized ret->out assignments and original had no return, prefer the out assignments
    if ret_lines and not has_ret:
        body.extend(ret_lines)
    body.extend(post_lines)
    if has_ret:
        body.append("    return __ret;")
    body.append("}")

    # Compose full function
    # Ensure signature ends with no semicolon
    header = original_signature_renamed.strip()
    if header.endswith(';'):
        header = header[:-1]
    return "\n".join([header] + body)
