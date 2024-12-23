#![feature(proc_macro_span)]

use pyo3::prelude::*;
use pyo3_stub_gen::{define_stub_info_gatherer, derive::gen_stub_pyfunction};
use quote::quote;
use std::collections::HashMap;
use syn::{parse_quote, parse_str, spanned::Spanned, Abi, File, LitStr, Token};

fn parse_src(source_code: &str) -> PyResult<File> {
    parse_str(source_code).map_err(|e| {
        pyo3::exceptions::PySyntaxError::new_err(format!(
            "Parse error: {}\n source code: {}",
            e, source_code
        ))
    })
}

// Expose a function to C
// 1. find `fn`, if it's `unsafe`, change to `pub unsafe extern "C" fn`, else `pub extern "C" fn`
// 2. add `#[no_mangle]` before `pub`
#[gen_stub_pyfunction]
#[pyfunction]
fn expose_function_to_c(source_code: &str) -> PyResult<String> {
    let mut ast = parse_src(source_code)?;
    for item in ast.items.iter_mut() {
        if let syn::Item::Fn(ref mut f) = item {
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

#[pymodule]
fn rust_ast_parser(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(expose_function_to_c, m)?)?;
    m.add_function(wrap_pyfunction!(get_func_signatures, m)?)?;
    m.add_function(wrap_pyfunction!(get_struct_definition, m)?)?;
    m.add_function(wrap_pyfunction!(get_union_definition, m)?)?;
    Ok(())
}

define_stub_info_gatherer!(stub_info);
