#![feature(proc_macro_span)]

use proc_macro2::Span;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use pyo3_stub_gen::derive::gen_stub_pyfunction;
use quote::{quote, ToTokens};
use std::collections::{BTreeSet, HashMap, HashSet};
use std::mem;
use std::sync::OnceLock;
use syn::{
    parse::{Parse, ParseStream},
    parse_quote, parse_str,
    spanned::Spanned,
    token,
    visit::{self, Visit},
    visit_mut::{self, VisitMut},
    Abi, AttrStyle, Attribute, File, GenericArgument, ItemStatic, LitStr, Meta, PatIdent,
    PathArguments, Result, Token, TypePath,
};
static LIBC_SCALAR_MAP_TEXT: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../sactor/_resources/libc_scalar_map.txt"
));

static LIBC_SCALAR_TO_PRIMITIVE: OnceLock<Vec<(&'static str, &'static str)>> = OnceLock::new();

const NUMERIC_PRIMITIVES: &[&str] = &[
    "u8", "i8", "u16", "i16", "u32", "i32", "u64", "i64", "usize", "isize", "f32", "f64",
];

fn get_error_context(source: &str, error: &syn::Error) -> String {
    let lines: Vec<_> = source.lines().collect();
    let span = error.span();
    // pick -1 to +2 lines around the error line
    let start_line = span.start().line.saturating_sub(2);
    let end_line = (span.end().line + 2).min(lines.len());

    let mut context = String::new();
    for (idx, line) in lines[start_line..end_line].iter().enumerate() {
        let line_num = start_line + idx + 1;
        context.push_str(&format!("{:>4} | {}\n", line_num, line));
        if line_num == span.start().line {
            let pad = " ".repeat(span.start().column + 4);
            context.push_str(&format!(" Err:|{pad}^\n"));
        }
    }
    context
}

fn parse_src(source_code: &str) -> PyResult<File> {
    use std::panic;
    // parse_str may panic. We need to convert panic to Err
    let res = panic::catch_unwind(|| {
        parse_str(source_code).map_err(|e| {
            let msg = format!(
                "Error: {:?}\nContext:\n{}",
                e,
                get_error_context(source_code, &e)
            );
            pyo3::exceptions::PySyntaxError::new_err(msg)
        })
    });
    match res {
        Ok(inner_res) => inner_res,
        Err(e) => if let Some(msg) = e.downcast_ref::<&str>() {
            Err(format!("Error when parsing Rust: {}", msg))
        } else if let Some(msg) = e.downcast_ref::<String>() {
            Err(format!("Error when parsing Rust: {}", msg))
        } else {
            Err("Error when parsing Rust.".to_string())
        }
        .map_err(|msg| pyo3::exceptions::PySyntaxError::new_err(msg)),
    }
}

// Expose a function to C
// 1. find `fn`, if it's `unsafe`, change to `pub unsafe extern "C" fn`, else `pub extern "C" fn`
// 2. add `#[no_mangle]` before `pub`
#[gen_stub_pyfunction]
#[pyfunction]
fn expose_function_to_c(source_code: &str, function_name: &str) -> PyResult<String> {
    let mut ast = parse_src(source_code)?;
    for item in ast.items.iter_mut() {
        if let syn::Item::Fn(ref mut f) = item {
            if f.sig.ident != function_name {
                continue;
            }
            f.vis = syn::Visibility::Public(Token![pub](f.span()));
            f.sig.abi = Some(Abi {
                extern_token: Token![extern](f.span()),
                name: Some(LitStr::new("C", f.span())),
            });
            // add `#[no_mangle]` before `pub`
            let mut no_mangle = false;
            for attr in f.attrs.iter() {
                if let syn::Meta::Path(p) = &attr.meta {
                    if p.is_ident("no_mangle") {
                        no_mangle = true;
                        break;
                    }
                }
            }
            if !no_mangle {
                f.attrs.push(parse_quote!(#[no_mangle]));
            }
        }
    }
    // return the modified source code
    Ok(prettyplease::unparse(&ast))
}

fn normalize_stmt_with_semi(stmt: syn::Stmt) -> syn::Stmt {
    match stmt {
        syn::Stmt::Expr(expr, Some(semi)) => syn::Stmt::Expr(expr, Some(semi)),
        syn::Stmt::Expr(expr, None) => syn::Stmt::Expr(expr, Some(Token![;](Span::call_site()))),
        other => other,
    }
}

#[gen_stub_pyfunction]
#[pyfunction]
fn append_stmt_to_function(
    source_code: &str,
    function_name: &str,
    stmt_code: &str,
) -> PyResult<String> {
    let mut ast = parse_src(source_code)?;
    let parsed_stmt: syn::Stmt = parse_str(stmt_code).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!(
            "Failed to parse statement '{}': {}",
            stmt_code, e
        ))
    })?;
    let target_stmt = normalize_stmt_with_semi(parsed_stmt);
    let target_tokens = target_stmt.to_token_stream().to_string();

    for item in ast.items.iter_mut() {
        if let syn::Item::Fn(f) = item {
            if f.sig.ident != function_name {
                continue;
            }

            if f.block
                .stmts
                .iter()
                .any(|existing| existing.to_token_stream().to_string() == target_tokens)
            {
                return Ok(prettyplease::unparse(&ast));
            }

            if let Some(last_idx) = f.block.stmts.len().checked_sub(1) {
                if matches!(f.block.stmts[last_idx], syn::Stmt::Expr(_, None)) {
                    if let syn::Stmt::Expr(expr, _) = f.block.stmts.remove(last_idx) {
                        f.block
                            .stmts
                            .push(syn::Stmt::Expr(expr, Some(Token![;](Span::call_site()))));
                    }
                }
            }

            f.block.stmts.push(target_stmt.clone());
            return Ok(prettyplease::unparse(&ast));
        }
    }

    Err(pyo3::exceptions::PyValueError::new_err(format!(
        "Function '{}' not found",
        function_name
    )))
}

#[gen_stub_pyfunction]
#[pyfunction]
fn get_func_signatures(source_code: &str) -> PyResult<HashMap<String, String>> {
    let ast = parse_src(source_code)?;
    let mut signatures = HashMap::new();
    for item in ast.items.iter() {
        if let syn::Item::Fn(f) = item {
            let mut sig = f.sig.clone();
            if sig.unsafety.is_some() {
                sig.unsafety = None; // remove `unsafe`
            }
            for input in sig.inputs.iter_mut() {
                if let syn::FnArg::Typed(pat) = input {
                    if let syn::Pat::Ident(ident) = &mut *pat.pat {
                        if ident.mutability.is_some() {
                            ident.mutability = None; // remove `mut` in arguments
                        }
                    }
                }
            }
            signatures.insert(sig.ident.to_string(), quote!(#sig).to_string());
        }
    }
    Ok(signatures)
}

#[gen_stub_pyfunction]
#[pyfunction]
fn get_struct_definition(source_code: &str, struct_name: &str) -> PyResult<String> {
    let ast = parse_src(source_code)?;
    let mut prefix_items: Vec<syn::Item> = Vec::new();

    for item in ast.items.iter() {
        if let syn::Item::Struct(s) = item {
            if s.ident == struct_name {
                let mut items = prefix_items;
                items.push(syn::Item::Struct(s.clone()));
                let file = syn::File {
                    shebang: None,
                    attrs: vec![],
                    items,
                };
                return Ok(prettyplease::unparse(&file));
            }
        }

        match item {
            syn::Item::Use(_) | syn::Item::Type(_) | syn::Item::Const(_) => {
                prefix_items.push(item.clone())
            }
            _ => {}
        }
    }

    Err(pyo3::exceptions::PyValueError::new_err(format!(
        "Struct '{}' not found",
        struct_name
    )))
}

#[gen_stub_pyfunction]
#[pyfunction]
fn get_enum_definition(source_code: &str, enum_name: &str) -> PyResult<String> {
    let ast = parse_src(source_code)?;

    for item in ast.items.iter() {
        if let syn::Item::Enum(e) = item {
            if e.ident == enum_name {
                let file = syn::File {
                    shebang: None,
                    attrs: vec![],
                    items: vec![syn::Item::Enum(e.clone())],
                };
                return Ok(prettyplease::unparse(&file));
            }
        }
    }

    Err(pyo3::exceptions::PyValueError::new_err(format!(
        "Enum '{}' not found",
        enum_name
    )))
}

fn collect_struct_enum_union(items: &[syn::Item], acc: &mut Vec<(String, String)>) {
    for item in items {
        match item {
            syn::Item::Struct(s) => acc.push((s.ident.to_string(), "struct".to_string())),
            syn::Item::Enum(e) => acc.push((e.ident.to_string(), "enum".to_string())),
            syn::Item::Union(u) => acc.push((u.ident.to_string(), "union".to_string())),
            syn::Item::Mod(m) => {
                if let Some((_, inner_items)) = &m.content {
                    collect_struct_enum_union(inner_items, acc);
                }
            }
            _ => {}
        }
    }
}

#[gen_stub_pyfunction]
#[pyfunction]
fn dedup_items(source_code: &str) -> PyResult<String> {
    let ast = parse_src(source_code)?;
    Ok(dedup_ast(ast))
}

fn dedup_ast(ast: syn::File) -> String {
    let mut seen_use: HashSet<String> = HashSet::new();
    let mut seen_type: HashSet<String> = HashSet::new();
    let mut seen_const: HashSet<String> = HashSet::new();
    let mut seen_static: HashSet<String> = HashSet::new();
    let mut seen_struct: HashSet<String> = HashSet::new();
    let mut seen_enum: HashSet<String> = HashSet::new();
    let mut seen_union: HashSet<String> = HashSet::new();

    let mut use_idents: HashSet<String> = HashSet::new();
    for item in ast.items.iter() {
        if let syn::Item::Use(u) = item {
            collect_use_idents(&u.tree, &mut use_idents);
        }
    }

    let mut new_items = Vec::with_capacity(ast.items.len());

    for item in ast.items.into_iter() {
        let keep = match &item {
            syn::Item::Use(u) => {
                let key = quote!(#u).to_string();
                seen_use.insert(key)
            }
            syn::Item::Type(t) => {
                let key = t.ident.to_string();
                if use_idents.contains(&key) && expected_stdint_target(&key).is_some() {
                    false
                } else {
                    seen_type.insert(key)
                }
            }
            syn::Item::Const(c) => {
                let key = c.ident.to_string();
                seen_const.insert(key)
            }
            syn::Item::Static(s) => {
                let key = s.ident.to_string();
                seen_static.insert(key)
            }
            syn::Item::Struct(s) => {
                let key = s.ident.to_string();
                seen_struct.insert(key)
            }
            syn::Item::Enum(e) => {
                let key = e.ident.to_string();
                seen_enum.insert(key)
            }
            syn::Item::Union(u) => {
                let key = u.ident.to_string();
                seen_union.insert(key)
            }
            _ => true,
        };

        if keep {
            new_items.push(item);
        }
    }

    let deduped = syn::File {
        shebang: ast.shebang,
        attrs: ast.attrs,
        items: new_items,
    };

    prettyplease::unparse(&deduped)
}

fn collect_use_idents(tree: &syn::UseTree, acc: &mut HashSet<String>) {
    match tree {
        syn::UseTree::Name(name) => {
            acc.insert(name.ident.to_string());
        }
        syn::UseTree::Rename(rename) => {
            acc.insert(rename.rename.to_string());
        }
        syn::UseTree::Glob(_) => {}
        syn::UseTree::Path(path) => {
            collect_use_idents(&path.tree, acc);
        }
        syn::UseTree::Group(group) => {
            for item in group.items.iter() {
                collect_use_idents(item, acc);
            }
        }
    }
}

#[gen_stub_pyfunction]
#[pyfunction]
fn strip_to_struct_items(source_code: &str) -> PyResult<String> {
    let ast = parse_src(source_code)?;
    let mut filtered: Vec<syn::Item> = Vec::new();
    for item in ast.items.into_iter() {
        match item {
            syn::Item::Struct(_) | syn::Item::Union(_) => filtered.push(item),
            _ => {}
        }
    }

    let file = syn::File {
        shebang: None,
        attrs: Vec::new(),
        items: filtered,
    };

    Ok(prettyplease::unparse(&file))
}

#[gen_stub_pyfunction]
#[pyfunction]
fn list_struct_enum_union(source_code: &str) -> PyResult<Vec<(String, String)>> {
    let ast = parse_src(source_code)?;
    let mut items = Vec::new();
    collect_struct_enum_union(&ast.items, &mut items);
    Ok(items)
}

#[gen_stub_pyfunction]
#[pyfunction(signature = (source_code, struct_name=None))]
fn get_struct_field_types(
    source_code: &str,
    struct_name: Option<&str>,
) -> PyResult<HashMap<String, String>> {
    let ast = parse_src(source_code)?;

    for item in ast.items.iter() {
        if let syn::Item::Struct(s) = item {
            if let Some(name) = struct_name {
                if s.ident != name {
                    continue;
                }
            }

            match &s.fields {
                syn::Fields::Named(named) => {
                    let mut fields = HashMap::new();
                    for field in named.named.iter() {
                        if let Some(ident) = &field.ident {
                            let ty = field.ty.to_token_stream().to_string();
                            fields.insert(ident.to_string(), ty);
                        }
                    }
                    return Ok(fields);
                }
                _ => {
                    return Err(pyo3::exceptions::PyValueError::new_err(
                        "Struct does not have named fields",
                    ));
                }
            }
        }
    }

    if let Some(name) = struct_name {
        Err(pyo3::exceptions::PyValueError::new_err(format!(
            "Struct '{}' not found",
            name
        )))
    } else {
        Err(pyo3::exceptions::PyValueError::new_err(
            "No struct found in source",
        ))
    }
}

fn normalize_token_string(input: &str) -> String {
    let mut tokens = input.split_whitespace();
    let Some(first) = tokens.next() else {
        return String::new();
    };

    let mut result = String::from(first);
    for token in tokens {
        result.push(' ');
        result.push_str(token);
    }

    // Normalize common Rust type punctuation spacing.
    result = result
        .replace(" :: ", "::")
        .replace(" ::", "::")
        .replace(":: ", "::")
        .replace(" <", "<")
        .replace("< ", "<")
        .replace(" >", ">")
        .replace("* mut", "*mut")
        .replace("* const", "*const")
        .replace("& mut", "&mut")
        .replace("& '", "&'");

    if result.contains(',') {
        let segments: Vec<_> = result
            .split(',')
            .map(|segment| segment.trim())
            .filter(|segment| !segment.is_empty())
            .collect();
        result = segments.join(", ");
    }

    result
}

fn libc_scalar_pairs() -> &'static [(&'static str, &'static str)] {
    LIBC_SCALAR_TO_PRIMITIVE
        .get_or_init(|| {
            let mut pairs: Vec<(&'static str, &'static str)> = Vec::new();
            for (idx, raw_line) in LIBC_SCALAR_MAP_TEXT.lines().enumerate() {
                let line = raw_line.trim();
                if line.is_empty() || line.starts_with('#') {
                    continue;
                }
                let (lhs, rhs) = line.split_once('=').unwrap_or_else(|| {
                    panic!("Invalid entry in libc_scalar_map.txt on line {}", idx + 1)
                });
                let src = lhs.trim();
                let dst = rhs.trim();
                if src.is_empty() || dst.is_empty() {
                    panic!("Invalid entry in libc_scalar_map.txt on line {}", idx + 1);
                }
                pairs.push((src, dst));
            }
            pairs
        })
        .as_slice()
}

fn map_libc_scalar(name: &str) -> Option<&'static str> {
    for (src, dst) in libc_scalar_pairs().iter() {
        if *src == name {
            return Some(*dst);
        }
        if let Some(tail) = src.split("::").last() {
            if tail == name {
                return Some(*dst);
            }
        }
    }
    None
}

fn is_numeric_primitive(name: &str) -> bool {
    NUMERIC_PRIMITIVES.iter().any(|item| *item == name)
}

fn push_unique(vec: &mut Vec<String>, value: String) {
    if !value.is_empty() && !vec.iter().any(|existing| existing == &value) {
        vec.push(value);
    }
}

fn pointer_base<'a>(traits: &'a TypeTraits) -> Option<&'a TypeTraits> {
    if !traits.is_pointer {
        return None;
    }
    let mut current = traits.pointer_inner.as_deref()?;
    loop {
        if !current.is_pointer {
            return Some(current);
        }
        match current.pointer_inner.as_deref() {
            Some(next) => current = next,
            None => return None,
        }
    }
}

struct PointerMetadata {
    base_ident: Option<String>,
    base_normalized: Option<String>,
    base_raw: Option<String>,
    element: String,
}

fn compute_pointer_metadata(traits: &TypeTraits) -> PointerMetadata {
    if let Some(base) = pointer_base(traits) {
        let mut candidates: Vec<String> = Vec::new();
        if let Some(ident) = &base.path_ident {
            push_unique(&mut candidates, ident.clone());
        }
        let normalized = normalize_token_string(&base.normalized);
        if !normalized.is_empty() {
            push_unique(&mut candidates, normalized.clone());
        }
        let raw = normalize_token_string(&base.raw);
        if !raw.is_empty() {
            push_unique(&mut candidates, raw.clone());
        }
        let mut expanded = candidates.clone();
        for candidate in candidates {
            if let Some(tail) = candidate.split("::").last() {
                if tail != candidate {
                    push_unique(&mut expanded, tail.to_string());
                }
            }
        }

        for candidate in &expanded {
            if let Some(mapped) = map_libc_scalar(candidate) {
                return PointerMetadata {
                    base_ident: base.path_ident.clone(),
                    base_normalized: if normalized.is_empty() {
                        None
                    } else {
                        Some(normalized.clone())
                    },
                    base_raw: if raw.is_empty() {
                        None
                    } else {
                        Some(raw.clone())
                    },
                    element: mapped.to_string(),
                };
            }
        }
        for candidate in &expanded {
            if is_numeric_primitive(candidate) {
                return PointerMetadata {
                    base_ident: base.path_ident.clone(),
                    base_normalized: if normalized.is_empty() {
                        None
                    } else {
                        Some(normalized.clone())
                    },
                    base_raw: if raw.is_empty() {
                        None
                    } else {
                        Some(raw.clone())
                    },
                    element: candidate.clone(),
                };
            }
        }

        let element = expanded
            .into_iter()
            .find(|candidate| !candidate.is_empty())
            .unwrap_or_else(|| "u8".to_string());

        PointerMetadata {
            base_ident: base.path_ident.clone(),
            base_normalized: if normalized.is_empty() {
                None
            } else {
                Some(normalized)
            },
            base_raw: if raw.is_empty() { None } else { Some(raw) },
            element,
        }
    } else {
        PointerMetadata {
            base_ident: None,
            base_normalized: None,
            base_raw: None,
            element: "u8".to_string(),
        }
    }
}

fn compute_box_innermost(traits: &TypeTraits) -> Option<String> {
    if traits.is_box {
        if let Some(inner) = traits.box_inner.as_deref() {
            if let Some(nested) = compute_box_innermost(inner) {
                return Some(nested);
            }
            let normalized = normalize_token_string(&inner.normalized);
            if !normalized.is_empty() {
                return Some(normalized);
            }
            let raw = normalize_token_string(&inner.raw);
            if !raw.is_empty() {
                return Some(raw);
            }
        }
        return None;
    }
    if traits.is_option {
        if let Some(inner) = traits.option_inner.as_deref() {
            return compute_box_innermost(inner);
        }
    }
    if traits.is_reference {
        if let Some(inner) = traits.reference_inner.as_deref() {
            return compute_box_innermost(inner);
        }
    }
    None
}

#[derive(Clone)]
struct TypeTraits {
    raw: String,
    normalized: String,
    path_ident: Option<String>,
    is_reference: bool,
    is_mut_reference: bool,
    is_slice: bool,
    slice_elem: Option<String>,
    is_str: bool,
    is_string: bool,
    is_option: bool,
    option_inner: Option<Box<TypeTraits>>,
    reference_inner: Option<Box<TypeTraits>>,
    is_pointer: bool,
    pointer_is_mut: bool,
    pointer_depth: usize,
    pointer_inner: Option<Box<TypeTraits>>,
    is_box: bool,
    box_inner: Option<Box<TypeTraits>>,
    pointer_base_ident: Option<String>,
    pointer_base_normalized: Option<String>,
    pointer_base_raw: Option<String>,
    pointer_element: Option<String>,
    box_innermost: Option<String>,
}

impl TypeTraits {
    fn new(raw: String, normalized: String) -> Self {
        Self {
            raw,
            normalized,
            path_ident: None,
            is_reference: false,
            is_mut_reference: false,
            is_slice: false,
            slice_elem: None,
            is_str: false,
            is_string: false,
            is_option: false,
            option_inner: None,
            reference_inner: None,
            is_pointer: false,
            pointer_is_mut: false,
            pointer_depth: 0,
            pointer_inner: None,
            is_box: false,
            box_inner: None,
            pointer_base_ident: None,
            pointer_base_normalized: None,
            pointer_base_raw: None,
            pointer_element: None,
            box_innermost: None,
        }
    }

    fn into_py(self, py: Python<'_>) -> PyResult<PyObject> {
        let dict = PyDict::new(py);
        dict.set_item("raw", self.raw)?;
        dict.set_item("normalized", self.normalized)?;
        dict.set_item("path_ident", self.path_ident.clone())?;
        dict.set_item("is_reference", self.is_reference)?;
        dict.set_item("is_mut_reference", self.is_mut_reference)?;
        dict.set_item("is_slice", self.is_slice)?;
        dict.set_item("slice_elem", self.slice_elem)?;
        dict.set_item("is_str", self.is_str)?;
        dict.set_item("is_string", self.is_string)?;
        dict.set_item("is_option", self.is_option)?;
        if let Some(inner) = self.option_inner {
            dict.set_item("option_inner", inner.into_py(py)?)?;
        } else {
            dict.set_item("option_inner", py.None())?;
        }
        if let Some(inner) = self.reference_inner {
            dict.set_item("reference_inner", inner.into_py(py)?)?;
        } else {
            dict.set_item("reference_inner", py.None())?;
        }
        dict.set_item("is_pointer", self.is_pointer)?;
        dict.set_item("pointer_is_mut", self.pointer_is_mut)?;
        dict.set_item("pointer_depth", self.pointer_depth)?;
        if let Some(inner) = self.pointer_inner {
            dict.set_item("pointer_inner", inner.into_py(py)?)?;
        } else {
            dict.set_item("pointer_inner", py.None())?;
        }
        dict.set_item("is_box", self.is_box)?;
        if let Some(inner) = self.box_inner {
            dict.set_item("box_inner", inner.into_py(py)?)?;
        } else {
            dict.set_item("box_inner", py.None())?;
        }
        dict.set_item("pointer_base_ident", self.pointer_base_ident.clone())?;
        dict.set_item(
            "pointer_base_normalized",
            self.pointer_base_normalized.clone(),
        )?;
        dict.set_item("pointer_base_raw", self.pointer_base_raw.clone())?;
        dict.set_item("pointer_element", self.pointer_element.clone())?;
        dict.set_item("box_innermost", self.box_innermost.clone())?;
        Ok(dict.into())
    }

    fn finalize_metadata(&mut self) {
        if self.is_pointer {
            let meta = compute_pointer_metadata(self);
            self.pointer_base_ident = meta.base_ident;
            self.pointer_base_normalized = meta.base_normalized;
            self.pointer_base_raw = meta.base_raw;
            self.pointer_element = Some(meta.element);
        } else {
            self.pointer_base_ident = None;
            self.pointer_base_normalized = None;
            self.pointer_base_raw = None;
            self.pointer_element = None;
        }
        self.box_innermost = compute_box_innermost(self);
    }
}

fn analyze_type(ty: &syn::Type) -> TypeTraits {
    let tokens = ty.to_token_stream();
    let raw = tokens.to_string();
    let normalized = normalize_token_string(&raw);
    match ty {
        syn::Type::Paren(paren) => {
            let mut inner = analyze_type(&paren.elem);
            inner.raw = raw;
            inner.normalized = normalized;
            inner
        }
        syn::Type::Group(group) => {
            let mut inner = analyze_type(&group.elem);
            inner.raw = raw;
            inner.normalized = normalized;
            inner
        }
        _ => {
            let mut traits = TypeTraits::new(raw.clone(), normalized.clone());
            match ty {
                syn::Type::Reference(reference) => {
                    traits.is_reference = true;
                    traits.is_mut_reference = reference.mutability.is_some();
                    let inner = analyze_type(&reference.elem);
                    if inner.is_slice {
                        traits.is_slice = true;
                        traits.slice_elem = inner.slice_elem.clone();
                    }
                    if inner.is_str {
                        traits.is_str = true;
                    }
                    if inner.is_string {
                        traits.is_string = true;
                    }
                    traits.reference_inner = Some(Box::new(inner));
                }
                syn::Type::Slice(slice) => {
                    traits.is_slice = true;
                    traits.slice_elem = Some(slice.elem.to_token_stream().to_string());
                }
                syn::Type::Path(path) => {
                    if let Some(last) = path.path.segments.last() {
                        let ident = last.ident.to_string();
                        traits.path_ident = Some(ident.clone());
                        match ident.as_str() {
                            "String" => traits.is_string = true,
                            "str" => traits.is_str = true,
                            "Option" => {
                                traits.is_option = true;
                                if let PathArguments::AngleBracketed(args) = &last.arguments {
                                    for arg in args.args.iter() {
                                        if let GenericArgument::Type(inner_ty) = arg {
                                            let inner = analyze_type(inner_ty);
                                            if inner.is_slice {
                                                traits.is_slice = true;
                                                traits.slice_elem = inner.slice_elem.clone();
                                            }
                                            if inner.is_str {
                                                traits.is_str = true;
                                            }
                                            if inner.is_string {
                                                traits.is_string = true;
                                            }
                                            if inner.is_box && !traits.is_box {
                                                traits.is_box = true;
                                                traits.box_inner = inner.box_inner.clone();
                                            }
                                            traits.option_inner = Some(Box::new(inner));
                                            break;
                                        }
                                    }
                                }
                            }
                            "Box" => {
                                traits.is_box = true;
                                if let PathArguments::AngleBracketed(args) = &last.arguments {
                                    for arg in args.args.iter() {
                                        if let GenericArgument::Type(inner_ty) = arg {
                                            let inner = analyze_type(inner_ty);
                                            if inner.is_slice {
                                                traits.is_slice = true;
                                                traits.slice_elem = inner.slice_elem.clone();
                                            }
                                            if inner.is_str {
                                                traits.is_str = true;
                                            }
                                            if inner.is_string {
                                                traits.is_string = true;
                                            }
                                            traits.box_inner = Some(Box::new(inner));
                                            break;
                                        }
                                    }
                                }
                            }
                            _ => {}
                        }
                    }
                }
                syn::Type::Ptr(ptr) => {
                    traits.is_pointer = true;
                    traits.pointer_is_mut = ptr.mutability.is_some();
                    let inner = analyze_type(&ptr.elem);
                    traits.pointer_depth = inner.pointer_depth + 1;
                    if traits.slice_elem.is_none() && inner.is_slice {
                        traits.is_slice = true;
                        traits.slice_elem = inner.slice_elem.clone();
                    }
                    if inner.is_str {
                        traits.is_str = true;
                    }
                    if inner.is_string {
                        traits.is_string = true;
                    }
                    traits.pointer_inner = Some(Box::new(inner));
                }
                syn::Type::Tuple(_) | syn::Type::Array(_) | syn::Type::BareFn(_) => {}
                syn::Type::ImplTrait(_)
                | syn::Type::Infer(_)
                | syn::Type::Macro(_)
                | syn::Type::Never(_)
                | syn::Type::TraitObject(_)
                | syn::Type::Verbatim(_) => {}
                _ => {}
            }

            // For references and options we may want to propagate reference_inner slice info downwards
            if traits.is_reference {
                if let Some(inner) = &traits.reference_inner {
                    if traits.slice_elem.is_none() && inner.is_slice {
                        traits.slice_elem = inner.slice_elem.clone();
                        traits.is_slice = true;
                    }
                    if inner.is_str {
                        traits.is_str = true;
                    }
                    if inner.is_string {
                        traits.is_string = true;
                    }
                }
            }

            if traits.is_option {
                if let Some(inner) = &traits.option_inner {
                    if traits.slice_elem.is_none() && inner.is_slice {
                        traits.slice_elem = inner.slice_elem.clone();
                        traits.is_slice = true;
                    }
                    if inner.is_str {
                        traits.is_str = true;
                    }
                    if inner.is_string {
                        traits.is_string = true;
                    }
                }
            }

            traits.finalize_metadata();
            traits
        }
    }
}

#[gen_stub_pyfunction]
#[pyfunction]
fn parse_function_signature(py: Python<'_>, signature: &str) -> PyResult<PyObject> {
    let trimmed = signature.trim();
    if trimmed.is_empty() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "Function signature cannot be empty",
        ));
    }

    let cleaned = trimmed.trim_end_matches(';');
    let snippet = if cleaned.contains('{') {
        cleaned.to_string()
    } else {
        format!("{cleaned} {{}}")
    };

    let item: syn::ItemFn = syn::parse_str(&snippet).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!(
            "Failed to parse function signature: {:?}",
            e
        ))
    })?;

    let result = PyDict::new(py);
    result.set_item("name", item.sig.ident.to_string())?;

    let params = PyList::empty(py);
    for input in item.sig.inputs.iter() {
        match input {
            syn::FnArg::Receiver(_) => continue,
            syn::FnArg::Typed(pat_type) => {
                let name = match &*pat_type.pat {
                    syn::Pat::Ident(ident) => ident.ident.to_string(),
                    other => quote!(#other).to_string(),
                };
                let traits = analyze_type(&pat_type.ty);
                let ty_raw = traits.raw.clone();
                let param_dict = PyDict::new(py);
                param_dict.set_item("name", name)?;
                param_dict.set_item("type", ty_raw)?;
                param_dict.set_item("traits", traits.into_py(py)?)?;
                params.append(param_dict)?;
            }
        }
    }
    result.set_item("params", params)?;

    match &item.sig.output {
        syn::ReturnType::Default => result.set_item("return", py.None())?,
        syn::ReturnType::Type(_, ty) => {
            let traits = analyze_type(ty);
            result.set_item("return", traits.into_py(py)?)?;
        }
    }

    Ok(result.into())
}

#[gen_stub_pyfunction]
#[pyfunction]
fn parse_type_traits(py: Python<'_>, ty: &str) -> PyResult<PyObject> {
    let trimmed = ty.trim();
    if trimmed.is_empty() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "Type string cannot be empty",
        ));
    }
    let parsed_type: syn::Type = syn::parse_str(trimmed).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("Failed to parse type: {:?}", e))
    })?;
    let traits = analyze_type(&parsed_type);
    traits.into_py(py)
}

#[gen_stub_pyfunction]
#[pyfunction]
fn get_function_definition(source_code: &str, function_name: &str) -> PyResult<String> {
    let ast = parse_src(source_code)?;

    for item in ast.items.iter() {
        if let syn::Item::Fn(f) = item {
            if f.sig.ident == function_name {
                let file = syn::File {
                    shebang: None,
                    attrs: vec![],
                    items: vec![syn::Item::Fn(f.clone())],
                };
                return Ok(prettyplease::unparse(&file));
            }
        }
    }

    Err(pyo3::exceptions::PyValueError::new_err(format!(
        "Function '{}' not found",
        function_name
    )))
}

#[gen_stub_pyfunction]
#[pyfunction]
fn get_static_item_definition(source_code: &str, item_name: &str) -> PyResult<String> {
    let ast = parse_src(source_code)?;

    for item in ast.items.iter() {
        if let syn::Item::Static(s) = item {
            if s.ident == item_name {
                let file = syn::File {
                    shebang: None,
                    attrs: vec![],
                    items: vec![syn::Item::Static(s.clone())],
                };
                return Ok(prettyplease::unparse(&file));
            }
        }
    }

    Err(pyo3::exceptions::PyValueError::new_err(format!(
        "Static item '{}' not found",
        item_name
    )))
}

#[gen_stub_pyfunction]
#[pyfunction]
fn get_union_definition(source_code: &str, union_name: &str) -> PyResult<String> {
    let ast = parse_src(source_code)?;
    let mut prefix_items: Vec<syn::Item> = Vec::new();

    for item in ast.items.iter() {
        if let syn::Item::Union(s) = item {
            if s.ident == union_name {
                let mut items = prefix_items;
                items.push(syn::Item::Union(s.clone()));
                let file = syn::File {
                    shebang: None,
                    attrs: vec![],
                    items,
                };
                return Ok(prettyplease::unparse(&file));
            }
        }

        match item {
            syn::Item::Use(_) | syn::Item::Type(_) | syn::Item::Const(_) => {
                prefix_items.push(item.clone())
            }
            _ => {}
        }
    }

    Err(pyo3::exceptions::PyValueError::new_err(format!(
        "Union '{}' not found",
        union_name
    )))
}

#[gen_stub_pyfunction]
#[pyfunction]
fn get_uses_code(code: &str) -> PyResult<Vec<String>> {
    let ast = parse_src(code)?;
    let mut uses = vec![];
    for item in ast.items.iter() {
        if let syn::Item::Use(u) = item {
            uses.push(quote!(#u).to_string());
        }
    }

    Ok(uses)
}

#[gen_stub_pyfunction]
#[pyfunction]
fn get_code_other_than_uses(code: &str) -> PyResult<String> {
    let ast = parse_src(code)?;
    let mut code_other_than_uses = String::new();
    for item in ast.items.iter() {
        if let syn::Item::Use(_) = item {
            continue;
        }
        code_other_than_uses.push_str(&quote!(#item).to_string());
    }

    Ok(code_other_than_uses)
}

fn collect_paths(
    tree: &syn::UseTree,
    current_path: &mut Vec<String>,
    all_paths: &mut Vec<Vec<String>>,
) -> PyResult<()> {
    match tree {
        syn::UseTree::Path(path) => {
            current_path.push(path.ident.to_string());
            collect_paths(&path.tree, current_path, all_paths)?;
            current_path.pop();
        }
        syn::UseTree::Name(name) => {
            if name.ident != "self" {
                current_path.push(name.ident.to_string());
                all_paths.push(current_path.clone());
                current_path.pop();
            } else {
                // For self, add the current path without pushing 'self'
                all_paths.push(current_path.clone());
            }
        }
        syn::UseTree::Rename(_) => {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "Use statements with 'as' are not supported",
            ));
        }
        syn::UseTree::Glob(_) => {
            // Handle glob imports
            current_path.push("*".to_string());
            all_paths.push(current_path.clone());
            current_path.pop();
        }
        syn::UseTree::Group(group) => {
            // Handle nested groups like a::{b, c}
            for tree in &group.items {
                collect_paths(tree, current_path, all_paths)?;
            }
        }
    }
    Ok(())
}

struct UseAliasExpander {
    aliases: std::collections::HashMap<String, syn::Path>,
}

impl UseAliasExpander {
    fn new() -> Self {
        Self {
            aliases: std::collections::HashMap::new(),
        }
    }

    fn collect_aliases(&mut self, file: &syn::File) {
        for item in &file.items {
            if let syn::Item::Use(use_item) = item {
                self.collect_use_tree_aliases(&use_item.tree, &mut Vec::new());
            }
        }
    }

    fn collect_use_tree_aliases(&mut self, tree: &syn::UseTree, current_path: &mut Vec<String>) {
        match tree {
            syn::UseTree::Path(path) => {
                current_path.push(path.ident.to_string());
                self.collect_use_tree_aliases(&path.tree, current_path);
                current_path.pop();
            }
            syn::UseTree::Rename(rename) => {
                // Handle self aliases specially
                if rename.ident == "self" {
                    // E.g. for `self as collections`, map `collections` to the current path
                    let full_path = syn::Path {
                        leading_colon: None,
                        segments: current_path
                            .iter()
                            .map(|s| syn::PathSegment {
                                ident: syn::Ident::new(s, proc_macro2::Span::call_site()),
                                arguments: syn::PathArguments::None,
                            })
                            .collect(),
                    };
                    self.aliases.insert(rename.rename.to_string(), full_path);
                } else {
                    current_path.push(rename.ident.to_string());

                    // Create the full path
                    let full_path = syn::Path {
                        leading_colon: None,
                        segments: current_path
                            .iter()
                            .map(|s| syn::PathSegment {
                                ident: syn::Ident::new(s, proc_macro2::Span::call_site()),
                                arguments: syn::PathArguments::None,
                            })
                            .collect(),
                    };

                    // Store the alias mapping
                    self.aliases.insert(rename.rename.to_string(), full_path);
                    current_path.pop();
                }
            }
            syn::UseTree::Group(group) => {
                for tree in &group.items {
                    self.collect_use_tree_aliases(tree, current_path);
                }
            }
            _ => {} // Handle other cases as needed
        }
    }
}

impl syn::visit_mut::VisitMut for UseAliasExpander {
    fn visit_path_mut(&mut self, path: &mut syn::Path) {
        if let Some(first_segment) = path.segments.first() {
            let first_ident = first_segment.ident.to_string();
            if let Some(expanded_path) = self.aliases.get(&first_ident) {
                // Create new segments starting with the expanded path
                let mut new_segments = expanded_path.segments.clone();

                // Preserve generic arguments from the original first segment
                if !first_segment.arguments.is_empty() {
                    if let Some(last_segment) = new_segments.last_mut() {
                        last_segment.arguments = first_segment.arguments.clone();
                    }
                }

                // If there are remaining segments after the alias, append them
                if path.segments.len() > 1 {
                    let remaining_segments: Vec<_> =
                        path.segments.iter().skip(1).cloned().collect();
                    new_segments.extend(remaining_segments);
                }

                path.segments = new_segments;
            }
        }

        // Continue visiting nested paths
        syn::visit_mut::visit_path_mut(self, path);
    }

    fn visit_use_tree_mut(&mut self, tree: &mut syn::UseTree) {
        // Remove alias use statements and convert them to regular use statements
        if let syn::UseTree::Rename(rename) = tree {
            // Replace rename with regular name
            *tree = syn::UseTree::Name(syn::UseName {
                ident: rename.ident.clone(),
            });
        }

        // Continue visiting
        syn::visit_mut::visit_use_tree_mut(self, tree);
    }
}

#[gen_stub_pyfunction]
#[pyfunction]
fn expand_use_aliases(code: &str) -> PyResult<String> {
    use std::panic;
    let res = panic::catch_unwind(|| {
        let mut ast: File = parse_src(code)?;
        let mut expander = UseAliasExpander::new();
        // First pass: collect all aliases
        expander.collect_aliases(&ast);

        // Second pass: expand all usages
        expander.visit_file_mut(&mut ast);

        Ok(prettyplease::unparse(&ast))
    });
    match res {
        Ok(inner_res) => inner_res,
        Err(e) => if let Some(msg) = e.downcast_ref::<&str>() {
            Err(format!("Error when expand_use_aliases: {}", msg))
        } else if let Some(msg) = e.downcast_ref::<String>() {
            Err(format!("Error when expand_use_aliases: {}", msg))
        } else {
            Err("Error when expand_use_aliases.".to_string())
        }
        .map_err(|msg| pyo3::exceptions::PySyntaxError::new_err(msg)),
    }
}

#[gen_stub_pyfunction]
#[pyfunction]
fn get_standalone_uses_code_paths(code: &str) -> PyResult<Vec<Vec<String>>> {
    let ast = parse_src(code)?;
    let mut all_paths = Vec::new();

    for item in ast.items.iter() {
        if let syn::Item::Use(use_item) = item {
            collect_paths(&use_item.tree, &mut Vec::new(), &mut all_paths)?;
        }
    }

    Ok(all_paths)
}

enum RenameModifier {
    Function,
    StructUnion,
}

struct RenameVisitor {
    old_name: String,
    new_name: String,
    modifer: RenameModifier,
}

impl syn::visit_mut::VisitMut for RenameVisitor {
    fn visit_item_fn_mut(&mut self, item_fn: &mut syn::ItemFn) {
        if let RenameModifier::Function = self.modifer {
            // rename definition
            if item_fn.sig.ident == self.old_name {
                item_fn.sig.ident = syn::Ident::new(&self.new_name, item_fn.sig.ident.span());
            }
        }
        syn::visit_mut::visit_item_fn_mut(self, item_fn);
    }

    fn visit_item_struct_mut(&mut self, item_struct: &mut syn::ItemStruct) {
        if let RenameModifier::StructUnion = self.modifer {
            // rename definition
            if item_struct.ident == self.old_name {
                item_struct.ident = syn::Ident::new(&self.new_name, item_struct.ident.span());
            }
        }

        syn::visit_mut::visit_item_struct_mut(self, item_struct);
    }

    fn visit_item_union_mut(&mut self, item_union: &mut syn::ItemUnion) {
        if let RenameModifier::StructUnion = self.modifer {
            // rename definition
            if item_union.ident == self.old_name {
                item_union.ident = syn::Ident::new(&self.new_name, item_union.ident.span());
            }
        }

        syn::visit_mut::visit_item_union_mut(self, item_union);
    }

    fn visit_path_mut(&mut self, path: &mut syn::Path) {
        if let Some(ident) = path.get_ident() {
            if ident == self.old_name.as_str() {
                path.segments.last_mut().unwrap().ident =
                    syn::Ident::new(&self.new_name, ident.span());
            }
        }

        syn::visit_mut::visit_path_mut(self, path);
    }
}

// Need to rename both function definition and function calls
#[gen_stub_pyfunction]
#[pyfunction]
fn rename_function(code: &str, old_name: &str, new_name: &str) -> PyResult<String> {
    let mut ast = parse_src(code)?;
    // Create and run our visitor
    let mut visitor = RenameVisitor {
        old_name: old_name.to_string(),
        new_name: new_name.to_string(),
        modifer: RenameModifier::Function,
    };
    visitor.visit_file_mut(&mut ast);

    // Return the modified source code
    Ok(prettyplease::unparse(&ast))
}
//
// Need to rename both function definition and function calls
#[gen_stub_pyfunction]
#[pyfunction]
fn rename_struct_union(code: &str, old_name: &str, new_name: &str) -> PyResult<String> {
    let mut ast = parse_src(code)?;
    // Create and run our visitor
    let mut visitor = RenameVisitor {
        old_name: old_name.to_string(),
        new_name: new_name.to_string(),
        modifer: RenameModifier::StructUnion,
    };
    visitor.visit_file_mut(&mut ast);

    // Return the modified source code
    Ok(prettyplease::unparse(&ast))
}

struct TokenCounter {
    total_tokens: usize,
    unsafe_tokens: usize,
}

fn count_tokens(tokens: proc_macro2::TokenStream) -> usize {
    let mut total = 0;
    for token in tokens.into_iter() {
        match &token {
            proc_macro2::TokenTree::Group(group) => {
                total += count_tokens(group.stream());
            }
            _ => {
                total += 1;
            }
        }
    }
    total
}

impl syn::visit_mut::VisitMut for TokenCounter {
    fn visit_item_fn_mut(&mut self, func: &mut syn::ItemFn) {
        if func.sig.unsafety.is_some() {
            let unsafe_tokens = count_tokens(func.block.to_token_stream());
            self.unsafe_tokens += unsafe_tokens;
            self.total_tokens += unsafe_tokens;
        } else {
            self.total_tokens += count_tokens(func.block.to_token_stream());
            syn::visit_mut::visit_item_fn_mut(self, func);
        }
    }

    fn visit_expr_mut(&mut self, expr: &mut syn::Expr) {
        if let syn::Expr::Unsafe(unsafe_expr) = expr {
            let unsafe_tokens = count_tokens(unsafe_expr.block.to_token_stream());
            self.unsafe_tokens += unsafe_tokens;
        } else {
            syn::visit_mut::visit_expr_mut(self, expr);
        }
    }
}

#[gen_stub_pyfunction]
#[pyfunction]
fn count_unsafe_tokens(code: &str) -> PyResult<(usize, usize)> {
    let mut ast = parse_src(code)?;
    let mut counter = TokenCounter {
        total_tokens: 0,
        unsafe_tokens: 0,
    };
    counter.visit_file_mut(&mut ast);
    Ok((counter.total_tokens, counter.unsafe_tokens))
}

pub struct ParsedAttribute(pub Attribute);

impl Parse for ParsedAttribute {
    fn parse(input: ParseStream) -> Result<Self> {
        let pound_token: token::Pound = input.parse()?;

        // Determine the style of the attribute (Outer or Inner)
        let style = if input.peek(token::Bracket) {
            AttrStyle::Outer
        } else if input.peek(Token![!]) {
            input.parse::<Token![!]>()?;
            AttrStyle::Inner(Token![!](input.span()))
        } else {
            return Err(input.error("Expected attribute brackets"));
        };

        // Parse the bracketed contents
        let content;
        let bracket_token = syn::bracketed!(content in input);
        let meta: Meta = content.parse()?;

        let attribute = Attribute {
            pound_token,
            style,
            bracket_token,
            meta,
        };

        Ok(ParsedAttribute(attribute))
    }
}

#[gen_stub_pyfunction]
#[pyfunction]
fn add_attr_to_function(code: &str, function_name: &str, attr: &str) -> PyResult<String> {
    let mut ast = parse_src(code)?;
    for item in ast.items.iter_mut() {
        if let syn::Item::Fn(f) = item {
            if f.sig.ident == function_name {
                let parsed = parse_str::<ParsedAttribute>(attr).map_err(|e| {
                    pyo3::exceptions::PySyntaxError::new_err(format!(
                        "Parse error: {}\n source code: {}",
                        e, attr
                    ))
                })?;
                let attr = parsed.0;
                // check if the attribute is already present
                for existing_attr in f.attrs.iter() {
                    if existing_attr.to_token_stream().to_string()
                        == attr.to_token_stream().to_string()
                    {
                        return Ok(prettyplease::unparse(&ast));
                    }
                }

                f.attrs.push(attr);
            }
        }
    }
    Ok(prettyplease::unparse(&ast))
}

#[gen_stub_pyfunction]
#[pyfunction]
fn add_attr_to_struct_union(code: &str, struct_union_name: &str, attr: &str) -> PyResult<String> {
    let mut ast = parse_src(code)?;

    fn add_attribute(attrs: &mut Vec<syn::Attribute>, attr: &str) -> PyResult<()> {
        let parsed = parse_str::<ParsedAttribute>(attr).map_err(|e| {
            pyo3::exceptions::PySyntaxError::new_err(format!(
                "Parse error: {}\n source code: {}",
                e, attr
            ))
        })?;
        let attr = parsed.0;

        // Check if the attribute is already present
        if attrs.iter().any(|existing| {
            existing.to_token_stream().to_string() == attr.to_token_stream().to_string()
        }) {
            return Ok(());
        }

        attrs.push(attr);
        Ok(())
    }

    for item in ast.items.iter_mut() {
        if let syn::Item::Struct(s) = item {
            if s.ident == struct_union_name {
                add_attribute(&mut s.attrs, attr)?;
            }
        } else if let syn::Item::Union(u) = item {
            if u.ident == struct_union_name {
                add_attribute(&mut u.attrs, attr)?;
            }
        }
    }

    Ok(prettyplease::unparse(&ast))
}

#[gen_stub_pyfunction]
#[pyfunction]
fn add_derive_to_struct_union(
    code: &str,
    struct_union_name: &str,
    derive: &str,
) -> PyResult<String> {
    let mut ast = parse_src(code)?;

    fn add_derive(
        attrs: &mut Vec<syn::Attribute>,
        derive: &str,
        span: proc_macro2::Span,
    ) -> PyResult<()> {
        let mut existing_derive = None;

        // Check for existing derive attribute
        for attr in attrs.iter_mut() {
            if let syn::Meta::List(list) = &mut attr.meta {
                if list.path.is_ident("derive") {
                    existing_derive = Some(list);
                    break;
                }
            }
        }

        if let Some(existing_derive) = existing_derive {
            // Check if derive is already present
            let mut found = false;
            existing_derive
                .parse_nested_meta(|meta| {
                    if meta.path.is_ident(derive) {
                        found = true;
                    }
                    Ok(())
                })
                .map_err(|e| {
                    pyo3::exceptions::PySyntaxError::new_err(format!(
                        "Parse error: {}\n source code: {}",
                        e, derive
                    ))
                })?;

            if !found {
                let current_derive_tokens = existing_derive.tokens.clone();
                let ident = syn::Ident::new(derive, span);
                existing_derive.tokens = quote! { #current_derive_tokens, #ident };
            }
        } else {
            // Add new derive attribute
            let ident = syn::Ident::new(derive, span);
            attrs.push(parse_quote!(#[derive(#ident)]));
        }

        Ok(())
    }

    for item in ast.items.iter_mut() {
        match item {
            syn::Item::Struct(s) if s.ident == struct_union_name => {
                let span = s.span();
                add_derive(&mut s.attrs, derive, span)?;
            }
            syn::Item::Union(u) if u.ident == struct_union_name => {
                let span = u.span();
                add_derive(&mut u.attrs, derive, span)?;
            }
            _ => {}
        }
    }

    Ok(prettyplease::unparse(&ast))
}

/// A visitor that traverses the AST and replaces libc scalar types with Rust primitives.
struct LibcTypeVisitor;

impl VisitMut for LibcTypeVisitor {
    /// This method is called for every type path in the source code.
    fn visit_type_path_mut(&mut self, type_path: &mut TypePath) {
        // We are looking for paths with exactly two segments, like `libc::c_int`.
        if type_path.qself.is_none() && type_path.path.segments.len() == 2 {
            let first_segment = &type_path.path.segments[0];

            // Check if the first segment is `libc`.
            if first_segment.ident == "libc" && first_segment.arguments.is_none() {
                let second_segment = &type_path.path.segments[1];
                let libc_type_name = second_segment.ident.to_string();

                // If the second segment is a libc type we can replace...
                if let Some(rust_type_str) = map_libc_scalar(&libc_type_name) {
                    // Create a new identifier for the Rust type.
                    let new_rust_type_ident =
                        syn::Ident::new(rust_type_str, second_segment.ident.span());

                    // Create a new path from this single identifier.
                    let new_path: syn::Path = new_rust_type_ident.into();

                    // Replace the old path (`libc::c_int`) with the new one (`i32`).
                    type_path.path = new_path;
                }
            }
        }

        // Continue traversing the rest of the AST to find other types.
        syn::visit_mut::visit_type_path_mut(self, type_path);
    }
}

#[gen_stub_pyfunction]
#[pyfunction]
fn replace_libc_numeric_types_to_rust_primitive_types(code: &str) -> PyResult<String> {
    let mut ast = parse_src(code)?;
    let mut visitor = LibcTypeVisitor;
    visitor.visit_file_mut(&mut ast);

    // Convert the modified syntax tree back into formatted code.
    let transformed_code = prettyplease::unparse(&ast);
    Ok(transformed_code)
}

#[gen_stub_pyfunction]
#[pyfunction]
fn unidiomatic_function_cleanup(code: &str) -> PyResult<String> {
    let mut ast = parse_src(code)?;

    for item in ast.items.iter_mut() {
        if let syn::Item::Fn(f) = item {
            // remove `extern "C"``
            f.sig.abi = None;
            // add `pub` before `fn`
            f.vis = syn::Visibility::Public(Token![pub](f.span()));
        }
        if let syn::Item::ExternCrate(_) = item {
            // remove `extern crate`
            *item = syn::Item::Verbatim(Default::default());
        }
    }

    normalize_stdint_aliases(&mut ast);

    Ok(prettyplease::unparse(&ast))
}

#[gen_stub_pyfunction]
#[pyfunction]
fn unidiomatic_types_cleanup(code: &str) -> PyResult<String> {
    let mut ast = parse_src(code)?;

    for item in ast.items.iter_mut() {
        if let syn::Item::ExternCrate(_) = item {
            // remove `extern crate`
            *item = syn::Item::Verbatim(Default::default());
        }
    }

    normalize_stdint_aliases(&mut ast);

    Ok(prettyplease::unparse(&ast))
}

const STDINT_ALIAS_TARGETS: &[(&str, &str)] = &[
    ("int8_t", "i8"),
    ("int16_t", "i16"),
    ("int32_t", "i32"),
    ("int64_t", "i64"),
    ("uint8_t", "u8"),
    ("uint16_t", "u16"),
    ("uint32_t", "u32"),
    ("uint64_t", "u64"),
];

fn expected_stdint_target(name: &str) -> Option<&'static str> {
    STDINT_ALIAS_TARGETS
        .iter()
        .find(|(alias, _)| alias == &name)
        .map(|(_, target)| *target)
}

fn should_strip_stdint_alias(item: &syn::ItemType) -> Option<String> {
    let name = item.ident.to_string();
    let expected = expected_stdint_target(&name)?;

    if let syn::Type::Path(type_path) = item.ty.as_ref() {
        if type_path.qself.is_none()
            && type_path.path.segments.len() == 1
            && type_path.path.segments[0].ident == expected
            && type_path.path.segments[0].arguments.is_empty()
        {
            return Some(name);
        }
    }

    None
}

fn normalize_stdint_aliases(ast: &mut syn::File) {
    let mut removed_aliases: Vec<String> = Vec::new();
    let original_items = mem::take(&mut ast.items);
    let mut new_items = Vec::with_capacity(original_items.len());

    for item in original_items {
        if let syn::Item::Type(type_item) = &item {
            if let Some(name) = should_strip_stdint_alias(type_item) {
                removed_aliases.push(name);
                continue;
            }
        }
        new_items.push(item);
    }

    removed_aliases.sort();
    removed_aliases.dedup();

    let mut needed: BTreeSet<String> = removed_aliases.into_iter().collect();
    let usages = collect_stdint_names(&new_items);
    needed.extend(usages);

    if needed.is_empty() {
        ast.items = new_items;
        return;
    }

    let needed_vec: Vec<String> = needed.into_iter().collect();
    ensure_libc_imports(&mut new_items, &needed_vec);

    ast.items = new_items;
}

fn ensure_libc_imports(items: &mut Vec<syn::Item>, aliases: &[String]) {
    if aliases.is_empty() {
        return;
    }

    let mut needed: BTreeSet<String> = aliases.iter().cloned().collect();

    for item in items.iter_mut() {
        if let syn::Item::Use(item_use) = item {
            ensure_aliases_in_use_tree(&mut item_use.tree, &mut needed, false);
            if needed.is_empty() {
                break;
            }
        }
    }

    if needed.is_empty() {
        return;
    }

    let group_items: Vec<syn::UseTree> = needed
        .iter()
        .map(|name| {
            syn::UseTree::Name(syn::UseName {
                ident: syn::Ident::new(name, proc_macro2::Span::call_site()),
            })
        })
        .collect();

    let new_use = syn::Item::Use(syn::ItemUse {
        attrs: Vec::new(),
        vis: syn::Visibility::Inherited,
        use_token: Token![use](proc_macro2::Span::call_site()),
        leading_colon: None,
        tree: syn::UseTree::Path(syn::UsePath {
            ident: syn::Ident::new("libc", proc_macro2::Span::call_site()),
            colon2_token: Token![::](proc_macro2::Span::call_site()),
            tree: Box::new(syn::UseTree::Group(syn::UseGroup {
                brace_token: syn::token::Brace::default(),
                items: vec_to_punctuated(group_items),
            })),
        }),
        semi_token: Token![;](proc_macro2::Span::call_site()),
    });

    // Insert the new use after the last existing use declaration to keep code tidy.
    let insertion_index = items
        .iter()
        .enumerate()
        .filter_map(|(idx, item)| match item {
            syn::Item::Use(_) => Some(idx + 1),
            _ => None,
        })
        .last()
        .unwrap_or(0);

    items.insert(insertion_index, new_use);
    needed.clear();
}

fn collect_stdint_names(items: &[syn::Item]) -> BTreeSet<String> {
    let mut collector = StdintUsageCollector {
        names: BTreeSet::new(),
    };

    for item in items {
        collector.visit_item(item);
    }

    collector.names
}

struct StdintUsageCollector {
    names: BTreeSet<String>,
}

impl<'ast> Visit<'ast> for StdintUsageCollector {
    fn visit_path(&mut self, path: &'ast syn::Path) {
        if path.leading_colon.is_none() && path.segments.len() == 1 {
            let ident = &path.segments[0].ident;
            let ident_str = ident.to_string();
            if expected_stdint_target(&ident_str).is_some() {
                self.names.insert(ident_str);
            }
        }

        visit::visit_path(self, path);
    }
}

fn ensure_aliases_in_use_tree(
    tree: &mut syn::UseTree,
    needed: &mut BTreeSet<String>,
    in_libc: bool,
) {
    match tree {
        syn::UseTree::Path(path) => {
            let next_in_libc = in_libc || path.ident == "libc";
            ensure_aliases_in_use_tree(&mut path.tree, needed, next_in_libc);
        }
        syn::UseTree::Group(group) => {
            if in_libc {
                ensure_aliases_in_libc_group(group, needed);
            } else {
                for item in group.items.iter_mut() {
                    ensure_aliases_in_use_tree(item, needed, false);
                    if needed.is_empty() {
                        break;
                    }
                }
            }
        }
        syn::UseTree::Name(name) => {
            if !in_libc {
                return;
            }

            let ident_str = name.ident.to_string();
            needed.remove(&ident_str);

            if needed.is_empty() {
                return;
            }

            let mut items_vec = Vec::with_capacity(1 + needed.len());
            items_vec.push(syn::UseTree::Name(name.clone()));

            let extras: Vec<String> = needed.iter().cloned().collect();
            for alias in extras.iter() {
                let ident = syn::Ident::new(alias, proc_macro2::Span::call_site());
                items_vec.push(syn::UseTree::Name(syn::UseName { ident }));
                needed.remove(alias);
            }

            *tree = syn::UseTree::Group(syn::UseGroup {
                brace_token: syn::token::Brace::default(),
                items: vec_to_punctuated(items_vec),
            });
        }
        syn::UseTree::Rename(rename) => {
            if in_libc {
                needed.remove(&rename.ident.to_string());
            }
        }
        syn::UseTree::Glob(_) => {
            if in_libc {
                needed.clear();
            }
        }
    }
}

fn ensure_aliases_in_libc_group(group: &mut syn::UseGroup, needed: &mut BTreeSet<String>) {
    let mut existing: BTreeSet<String> = BTreeSet::new();

    let mut has_glob = false;
    for item in group.items.iter() {
        collect_libc_names(item, true, &mut existing, &mut has_glob);
        if has_glob {
            needed.clear();
            return;
        }
    }

    let additions: Vec<String> = needed
        .iter()
        .filter(|alias| !existing.contains(*alias))
        .cloned()
        .collect();

    if additions.is_empty() {
        return;
    }

    for alias in additions.iter() {
        let ident = syn::Ident::new(alias, proc_macro2::Span::call_site());
        group.items.push(syn::UseTree::Name(syn::UseName { ident }));
        needed.remove(alias);
    }
}

fn collect_libc_names(
    tree: &syn::UseTree,
    in_libc: bool,
    acc: &mut BTreeSet<String>,
    has_glob: &mut bool,
) {
    match tree {
        syn::UseTree::Path(path) => {
            let next_in_libc = in_libc || path.ident == "libc";
            collect_libc_names(&path.tree, next_in_libc, acc, has_glob);
        }
        syn::UseTree::Group(group) => {
            for item in group.items.iter() {
                collect_libc_names(item, in_libc, acc, has_glob);
                if *has_glob {
                    break;
                }
            }
        }
        syn::UseTree::Name(name) => {
            if in_libc {
                acc.insert(name.ident.to_string());
            }
        }
        syn::UseTree::Rename(rename) => {
            if in_libc {
                acc.insert(rename.ident.to_string());
            }
        }
        syn::UseTree::Glob(_) => {
            if in_libc {
                *has_glob = true;
            }
        }
    }
}

fn vec_to_punctuated(
    trees: Vec<syn::UseTree>,
) -> syn::punctuated::Punctuated<syn::UseTree, syn::token::Comma> {
    let mut punctuated = syn::punctuated::Punctuated::new();
    for (idx, tree) in trees.into_iter().enumerate() {
        if idx > 0 {
            punctuated.push_punct(Token![,](proc_macro2::Span::call_site()));
        }
        punctuated.push(tree);
    }
    punctuated
}
/// The mut-remover: walks the AST and clears `mut` when the bound ident matches `name`.
struct RemoveMut {
    name: String,
}

impl RemoveMut {
    fn new(name: impl Into<String>) -> Self {
        Self { name: name.into() }
    }
}

impl VisitMut for RemoveMut {
    fn visit_pat_ident_mut(&mut self, node: &mut PatIdent) {
        // If this pattern is a direct identifier binding with the target name, remove `mut`.
        if node.ident == self.name {
            node.mutability = None;
        }
        // Recurse into subpatterns if any (usually none for simple PatIdent).
        visit_mut::visit_pat_ident_mut(self, node);
    }

    fn visit_item_static_mut(&mut self, node: &mut ItemStatic) {
        if node.ident == self.name {
            node.mutability = syn::StaticMutability::None; // removes the `mut`
        }
        visit_mut::visit_item_static_mut(self, node);
    }
}

#[gen_stub_pyfunction]
#[pyfunction]
fn remove_mut_from_type_specifiers(code: &str, var_name: &str) -> PyResult<String> {
    let mut file: File = parse_src(code)?;
    let mut remover = RemoveMut::new(var_name);
    visit_mut::visit_file_mut(&mut remover, &mut file);

    // Pretty-print. Use prettyplease for nicer formatting; otherwise use tokens.
    let formatted = prettyplease::unparse(&file);
    Ok(formatted)
}

#[gen_stub_pyfunction]
#[pyfunction]
fn get_value_type_name(code: &str, value: &str) -> PyResult<String> {
    let ast = parse_src(code)?;

    for item in ast.items.iter() {
        match item {
            // Handle static variables
            syn::Item::Static(s) if s.ident == value => {
                let static_without_value = syn::ItemStatic {
                    attrs: vec![],                   // No attributes
                    vis: syn::Visibility::Inherited, // No visibility modifier
                    static_token: s.static_token,
                    mutability: s.mutability.clone(),
                    ident: s.ident.clone(),
                    colon_token: s.colon_token,
                    ty: s.ty.clone(),
                    eq_token: s.eq_token,
                    expr: Box::new(syn::Expr::Verbatim(Default::default())), // Empty expression
                    semi_token: s.semi_token,
                };

                let static_item = syn::Item::Static(static_without_value);
                let file = syn::File {
                    shebang: None,
                    attrs: vec![],
                    items: vec![static_item],
                };

                let code_str = prettyplease::unparse(&file);

                // Extract just the static declaration line (remove empty expression)
                let lines: Vec<&str> = code_str.lines().collect();
                for line in lines {
                    let trimmed = line.trim();
                    if trimmed.starts_with("static") && trimmed.ends_with("= ;") {
                        // Remove the "= " part to get just the type declaration
                        return Ok(trimmed.replace("= ", ""));
                    }
                }

                return Ok(code_str.trim().to_string());
            }

            // Handle const variables
            syn::Item::Const(c) if c.ident == value => {
                let const_without_value = syn::ItemConst {
                    attrs: vec![],                   // No attributes
                    vis: syn::Visibility::Inherited, // No visibility modifier
                    const_token: c.const_token,
                    ident: c.ident.clone(),
                    generics: c.generics.clone(),
                    colon_token: c.colon_token,
                    ty: c.ty.clone(),
                    eq_token: c.eq_token,
                    expr: Box::new(syn::Expr::Verbatim(Default::default())), // Empty expression
                    semi_token: c.semi_token,
                };

                let const_item = syn::Item::Const(const_without_value);
                let file = syn::File {
                    shebang: None,
                    attrs: vec![],
                    items: vec![const_item],
                };

                let code_str = prettyplease::unparse(&file);

                // Extract just the const declaration line (remove empty expression)
                let lines: Vec<&str> = code_str.lines().collect();
                for line in lines {
                    let trimmed = line.trim();
                    if trimmed.starts_with("const") && trimmed.ends_with("= ;") {
                        // Remove the "= " part to get just the type declaration
                        return Ok(trimmed.replace("= ", ""));
                    }
                }

                return Ok(code_str.trim().to_string());
            }

            _ => continue,
        }
    }

    Err(pyo3::exceptions::PyValueError::new_err(format!(
        "Item '{}' not found",
        value
    )))
}

#[pymodule]
fn rust_ast_parser(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(expose_function_to_c, m)?)?;
    m.add_function(wrap_pyfunction!(append_stmt_to_function, m)?)?;
    m.add_function(wrap_pyfunction!(get_func_signatures, m)?)?;
    m.add_function(wrap_pyfunction!(get_struct_definition, m)?)?;
    m.add_function(wrap_pyfunction!(get_enum_definition, m)?)?;
    m.add_function(wrap_pyfunction!(list_struct_enum_union, m)?)?;
    m.add_function(wrap_pyfunction!(get_struct_field_types, m)?)?;
    m.add_function(wrap_pyfunction!(parse_type_traits, m)?)?;
    m.add_function(wrap_pyfunction!(parse_function_signature, m)?)?;
    m.add_function(wrap_pyfunction!(get_union_definition, m)?)?;
    m.add_function(wrap_pyfunction!(get_uses_code, m)?)?;
    m.add_function(wrap_pyfunction!(get_code_other_than_uses, m)?)?;
    m.add_function(wrap_pyfunction!(rename_function, m)?)?;
    m.add_function(wrap_pyfunction!(rename_struct_union, m)?)?;
    m.add_function(wrap_pyfunction!(get_standalone_uses_code_paths, m)?)?;
    m.add_function(wrap_pyfunction!(add_attr_to_function, m)?)?;
    m.add_function(wrap_pyfunction!(add_attr_to_struct_union, m)?)?;
    m.add_function(wrap_pyfunction!(add_derive_to_struct_union, m)?)?;
    m.add_function(wrap_pyfunction!(unidiomatic_function_cleanup, m)?)?;
    m.add_function(wrap_pyfunction!(unidiomatic_types_cleanup, m)?)?;
    m.add_function(wrap_pyfunction!(get_function_definition, m)?)?;
    m.add_function(wrap_pyfunction!(get_static_item_definition, m)?)?;
    m.add_function(wrap_pyfunction!(expand_use_aliases, m)?)?;
    m.add_function(wrap_pyfunction!(dedup_items, m)?)?;
    m.add_function(wrap_pyfunction!(strip_to_struct_items, m)?)?;
    m.add_function(wrap_pyfunction!(get_value_type_name, m)?)?;
    m.add_function(wrap_pyfunction!(
        replace_libc_numeric_types_to_rust_primitive_types,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(remove_mut_from_type_specifiers, m)?)?;
    #[allow(clippy::unsafe_removed_from_name)]
    m.add_function(wrap_pyfunction!(count_unsafe_tokens, m)?)?;
    Ok(())
}

#[doc = r" Auto-generated function to gather information to generate stub files"]
pub fn stub_info() -> pyo3_stub_gen::Result<pyo3_stub_gen::StubInfo> {
    let manifest_path = std::process::Command::new(env!("CARGO"))
        .arg("locate-project")
        .arg("--workspace")
        .arg("--message-format=plain")
        .output()
        .unwrap()
        .stdout;
    let manifest_path = std::path::Path::new(std::str::from_utf8(&manifest_path).unwrap().trim());
    let manifest_dir = manifest_path.parent().unwrap();
    pyo3_stub_gen::StubInfo::from_pyproject_toml(manifest_dir.join("pyproject.toml"))
}
