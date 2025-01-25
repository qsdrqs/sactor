#![feature(proc_macro_span)]

use pyo3::prelude::*;
use pyo3_stub_gen::derive::gen_stub_pyfunction;
use quote::{quote, ToTokens};
use std::collections::HashMap;
use syn::{
    parse::{Parse, ParseStream},
    parse_quote, parse_str,
    spanned::Spanned,
    token,
    visit_mut::VisitMut,
    Abi, AttrStyle, Attribute, File, LitStr, Meta, Result, Token,
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
       let msg = format!("Error: {:?}\nContext:\n{}",
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

#[pymodule]
fn rust_ast_parser(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(expose_function_to_c, m)?)?;
    m.add_function(wrap_pyfunction!(get_func_signatures, m)?)?;
    m.add_function(wrap_pyfunction!(get_struct_definition, m)?)?;
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
