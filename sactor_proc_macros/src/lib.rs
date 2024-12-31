use proc_macro::TokenStream;
use quote::quote;
use syn::{parse_macro_input, FnArg, ItemFn, PatIdent, PatType};

#[proc_macro_attribute]
pub fn trace_fn(_attr: TokenStream, item: TokenStream) -> TokenStream {
    let input = parse_macro_input!(item as ItemFn);
    let fn_attrs = &input.attrs;
    let fn_vis = &input.vis;
    let fn_signature = &input.sig;
    let fn_name = &input.sig.ident;
    let fn_inputs = &input.sig.inputs;
    let fn_output = &input.sig.output;
    let fn_block = &input.block;

    // Input arguments for the function
    let inputs_print = fn_inputs.iter().map(|arg| match arg {
        FnArg::Typed(PatType { pat, .. }) => {
            if let syn::Pat::Ident(PatIdent { ident, .. }) = &**pat {
                quote! {
                    println!("Argument {} = {:?}", stringify!(#ident), #ident);
                }
            } else {
                quote! {}
            }
        }
        _ => quote! {},
    });

    // Mutable input arguments for the function
    let outputs_print = fn_inputs.iter().map(|arg| match arg {
        FnArg::Typed(PatType { pat, ty, .. }) => {
            if let syn::Type::Reference(ty_ref) = &**ty {
                if ty_ref.mutability.is_some() {
                    if let syn::Pat::Ident(PatIdent { ident, .. }) = &**pat {
                        return quote! {
                            println!("Mutable variable {} = {:?}", stringify!(#ident), #ident);
                        };
                    }
                }
            }
            quote! {}
        }
        _ => quote! {},
    });

    // return value
    let return_print = if matches!(fn_output, syn::ReturnType::Default) {
        quote! {}
    } else {
        quote! {
            println!("Return value = {:?}", result);
        }
    };

    let fn_name_len = fn_name.to_string().len();
    let expanded = quote! {
        #(#fn_attrs)*
        #fn_vis #fn_signature {
            println!("--------Entering function: {}-------", stringify!(#fn_name));
            #(#inputs_print)*
            let result = (|| {
                #fn_block
            })();
            println!("--------Exiting function: {}--------", stringify!(#fn_name));
            #return_print
            #(#outputs_print)*
            println!("{}", "-".repeat(#fn_name_len + 34));
            result
        }
    };

    TokenStream::from(expanded)
}
