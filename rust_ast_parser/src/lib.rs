#![feature(proc_macro_span)]

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use pyo3_stub_gen::derive::gen_stub_pyfunction;
use quote::{quote, ToTokens};
use std::collections::HashMap;
use syn::{
    parse::{Parse, ParseStream},
    parse_quote, parse_str,
    spanned::Spanned,
    token,
    visit_mut::VisitMut,
    Abi, AttrStyle, Attribute, File, GenericArgument, LitStr, Meta, PathArguments, Result, Token,
};

fn get_error_context(source: &str, error: &syn::Error) -> String {
    let lines: Vec<_> = source.lines().collect();
    let span = error.span();
    // pick -1 to +2
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
    parse_str(source_code).map_err(|e| {
        let msg = format!(
            "Error: {:?}\nContext:\n{}",
            e,
            get_error_context(source_code, &e)
        );
        pyo3::exceptions::PySyntaxError::new_err(msg)
    })
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

    for item in ast.items.iter() {
        if let syn::Item::Struct(s) = item {
            if s.ident == struct_name {
                let file = syn::File {
                    shebang: None,
                    attrs: vec![],
                    items: vec![syn::Item::Struct(s.clone())],
                };
                return Ok(prettyplease::unparse(&file));
            }
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
        Ok(dict.into())
    }
}

fn analyze_type(ty: &syn::Type) -> TypeTraits {
    let tokens = ty.to_token_stream();
    let raw = tokens.to_string();
    let normalized = raw.split_whitespace().collect::<String>();
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

    for item in ast.items.iter() {
        if let syn::Item::Union(s) = item {
            if s.ident == union_name {
                let file = syn::File {
                    shebang: None,
                    attrs: vec![],
                    items: vec![syn::Item::Union(s.clone())],
                };
                return Ok(prettyplease::unparse(&file));
            }
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
    let mut ast = parse_src(code)?;
    let mut expander = UseAliasExpander::new();

    // First pass: collect all aliases
    expander.collect_aliases(&ast);

    // Second pass: expand all usages
    expander.visit_file_mut(&mut ast);

    Ok(prettyplease::unparse(&ast))
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

    Ok(prettyplease::unparse(&ast))
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
    m.add_function(wrap_pyfunction!(get_func_signatures, m)?)?;
    m.add_function(wrap_pyfunction!(get_struct_definition, m)?)?;
    m.add_function(wrap_pyfunction!(get_enum_definition, m)?)?;
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
    m.add_function(wrap_pyfunction!(get_value_type_name, m)?)?;

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
