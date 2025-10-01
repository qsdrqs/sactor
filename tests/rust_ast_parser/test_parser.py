import pytest

from sactor import rust_ast_parser


def _traits_base(raw: str, normalized: str) -> dict:
    return {
        "raw": raw,
        "normalized": normalized,
        "path_ident": None,
        "is_reference": False,
        "is_mut_reference": False,
        "is_slice": False,
        "slice_elem": None,
        "is_str": False,
        "is_string": False,
        "is_option": False,
        "option_inner": None,
        "reference_inner": None,
        "is_pointer": False,
        "pointer_is_mut": False,
        "pointer_depth": 0,
        "pointer_inner": None,
        "is_box": False,
        "box_inner": None,
    }


def _traits(raw: str, normalized: str, **updates: dict) -> dict:
    base = _traits_base(raw, normalized)
    base.update(updates)
    return base


@pytest.fixture
def code():
    file_path = 'tests/rust_ast_parser/test.rs'
    with open(file_path) as f:
        code = f.read()
    return code


def test_get_func_signatures(code):
    func_signatures = rust_ast_parser.get_func_signatures(code)
    assert func_signatures['add'] == 'fn add (a : i32 , b : i32) -> i32'


def test_get_struct_definition(code):
    struct_definition = rust_ast_parser.get_struct_definition(code, "Foo")
    assert (
        struct_definition
        == 'use std::collections::HashMap;\nuse libc::c_int;\n#[derive(Copy, Clone)]\nstruct Foo {\n    a: i32,\n    b: i32,\n    self_ptr: *const Foo,\n}\n'
    )


def test_get_struct_definition_includes_dependencies():
    code = (
        "use libc::FILE;\n"
        "pub type uint32_t = u32;\n\n"
        "#[repr(C)]\n"
        "pub struct Bar {\n"
        "    pub file: *mut FILE,\n"
        "    pub len: uint32_t,\n"
        "}\n"
    )

    struct_definition = rust_ast_parser.get_struct_definition(code, "Bar")
    assert "use libc::FILE;" in struct_definition
    assert "pub type uint32_t = u32;" in struct_definition
    assert struct_definition.strip().endswith(
        "pub struct Bar {\n    pub file: *mut FILE,\n    pub len: uint32_t,\n}"
    )


def test_get_enum_definition_returns_pretty_source():
    code = """pub enum Color {\n    Red,\n    Green,\n    Blue,\n}\n"""
    expected = """pub enum Color {\n    Red,\n    Green,\n    Blue,\n}\n"""
    assert rust_ast_parser.get_enum_definition(code, "Color") == expected


def test_get_enum_definition_errors_for_missing_enum():
    with pytest.raises(ValueError):
        rust_ast_parser.get_enum_definition("pub enum Foo {}", "Bar")


def test_list_struct_enum_union_collects_nested_items():
    code = """
    pub struct Root;

    mod inner {
        pub enum Kind { A }
        pub union Bits { v: u32 }
    }
    """

    items = rust_ast_parser.list_struct_enum_union(code)
    assert ("Root", "struct") in items
    assert ("Kind", "enum") in items
    assert ("Bits", "union") in items


def test_get_struct_field_types(code):
    expected = {
        "a": "i32",
        "b": "i32",
        "self_ptr": "* const Foo",
    }
    assert rust_ast_parser.get_struct_field_types(code, "Foo") == expected
    assert rust_ast_parser.get_struct_field_types(code) == expected


def test_parse_type_traits_option_mut_slice():
    traits = rust_ast_parser.parse_type_traits("Option<&mut [u8]>")

    slice_traits = _traits("[u8]", "[u8]", is_slice=True, slice_elem="u8")
    mut_slice_reference = _traits(
        "& mut [u8]",
        "&mut[u8]",
        is_reference=True,
        is_mut_reference=True,
        is_slice=True,
        slice_elem="u8",
        reference_inner=slice_traits,
    )

    expected = _traits(
        "Option < & mut [u8] >",
        "Option<&mut[u8]>",
        path_ident="Option",
        is_option=True,
        is_slice=True,
        slice_elem="u8",
        option_inner=mut_slice_reference,
    )

    assert traits == expected


def test_parse_function_signature_full_traits():
    signature = (
        "fn process(a: &mut i32, data: Option<&[u8]>, handle: *mut *const u8) "
        "-> Option<Box<Vec<u8>>>"
    )
    result = rust_ast_parser.parse_function_signature(signature)

    i32_traits = _traits("i32", "i32", path_ident="i32")
    param_a_traits = _traits(
        "& mut i32",
        "&muti32",
        is_reference=True,
        is_mut_reference=True,
        reference_inner=i32_traits,
    )

    slice_traits = _traits("[u8]", "[u8]", is_slice=True, slice_elem="u8")
    slice_ref_traits = _traits(
        "& [u8]",
        "&[u8]",
        is_reference=True,
        is_slice=True,
        slice_elem="u8",
        reference_inner=slice_traits,
    )
    option_data_traits = _traits(
        "Option < & [u8] >",
        "Option<&[u8]>",
        path_ident="Option",
        is_option=True,
        is_slice=True,
        slice_elem="u8",
        option_inner=slice_ref_traits,
    )

    u8_traits = _traits("u8", "u8", path_ident="u8")
    const_ptr_traits = _traits(
        "* const u8",
        "*constu8",
        is_pointer=True,
        pointer_is_mut=False,
        pointer_depth=1,
        pointer_inner=u8_traits,
    )
    handle_traits = _traits(
        "* mut * const u8",
        "*mut*constu8",
        is_pointer=True,
        pointer_is_mut=True,
        pointer_depth=2,
        pointer_inner=const_ptr_traits,
    )

    vec_traits = _traits("Vec < u8 >", "Vec<u8>", path_ident="Vec")
    box_traits = _traits(
        "Box < Vec < u8 > >",
        "Box<Vec<u8>>",
        path_ident="Box",
        is_box=True,
        box_inner=vec_traits,
    )
    return_traits = _traits(
        "Option < Box < Vec < u8 > > >",
        "Option<Box<Vec<u8>>>",
        path_ident="Option",
        is_option=True,
        is_box=True,
        option_inner=box_traits,
        box_inner=vec_traits,
    )

    expected = {
        "name": "process",
        "params": [
            {"name": "a", "type": "& mut i32", "traits": param_a_traits},
            {
                "name": "data",
                "type": "Option < & [u8] >",
                "traits": option_data_traits,
            },
            {
                "name": "handle",
                "type": "* mut * const u8",
                "traits": handle_traits,
            },
        ],
        "return": return_traits,
    }

    assert result == expected


def test_expose_function_to_c(code):
    exposed_code = rust_ast_parser.expose_function_to_c(code, "add")
    assert exposed_code.count('extern "C"') == 1
    assert exposed_code.count('#[no_mangle]') == 1


def test_get_function_definition_returns_pretty_source(code):
    expected = """pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n"""
    assert rust_ast_parser.get_function_definition(code, "add") == expected


def test_get_function_definition_errors_for_missing_function(code):
    with pytest.raises(ValueError):
        rust_ast_parser.get_function_definition(code, "missing")

def test_get_union_definition(code):
    union_definition = rust_ast_parser.get_union_definition(code, "Bar")
    assert (
        union_definition
        == 'use std::collections::HashMap;\nuse libc::c_int;\nunion Bar {\n    a: i32,\n    b: i32,\n}\n'
    )

def test_get_uses_code(code):
    uses_code = rust_ast_parser.get_uses_code(code)
    assert uses_code == ['use std :: collections :: HashMap ;', 'use libc :: c_int ;']

def test_rename_function(code):
    new_code = rust_ast_parser.rename_function(code, "fib", "fibonacci")
    assert code.count('fib') == new_code.count('fibonacci')

def test_rename_struct(code):
    new_code = rust_ast_parser.rename_struct_union(code, "Foo", "FooBar")
    assert code.count('Foo') == new_code.count('FooBar')

def test_rename_function_signature():
    signature = 'fn add (a : i32 , b : i32) -> i32 {}'
    new_signature = rust_ast_parser.rename_function(signature, "add", "addition")
    assert signature.count('add') == new_signature.count('addition')

def test_count_unsafe():
    code1 = '''
use std::collections::HashMap;
use libc::c_int;
fn use_foo(foo: Foo) -> i32 {
    unsafe {
        foo.a + foo.b
    }
}
'''
    assert rust_ast_parser.count_unsafe_tokens(code1) == (8, 7)
    code2 = '''
fn use_foo(foo: Foo) -> i32 {
    foo.a + foo.b
}
'''
    assert rust_ast_parser.count_unsafe_tokens(code2) == (7, 0)
    code3 = '''
unsafe fn use_foo(foo: Foo) -> i32 {
    foo.a + foo.b
}
'''
    assert rust_ast_parser.count_unsafe_tokens(code3) == (7, 7)


def test_get_standalone_uses_code_paths():
    code = '''
use a::b::c;
use a::b::{self, d, e};
use a::b::f;
use a::g::*;
'''
    paths = rust_ast_parser.get_standalone_uses_code_paths(code)
    print(paths)
    set_paths = set(map(tuple, paths))
    expected_set_paths = {
        ('a', 'b'),
        ('a', 'b', 'c'),
        ('a', 'b', 'd'),
        ('a', 'b', 'e'),
        ('a', 'b', 'f'),
        ('a', 'g', '*'),
    }
    assert set_paths == expected_set_paths

def test_expand_use_aliases():
    code = '''
use std::collections::HashMap as Map;
use std::collections::BTreeMap as Tree;
use std::vec::Vec as Vector;

fn create_map() -> Map<String, i32> {
    Map::new()
}

fn create_tree() -> Tree<String, i32> {
    Tree::new()
}

fn create_vector() -> Vector<i32> {
    Vector::new()
}

fn complex_usage() {
    let m: Map<String, Tree<i32, Vector<u8>>> = Map::new();
    let v = Vector::from([1, 2, 3]);
}
'''

    expanded_code = rust_ast_parser.expand_use_aliases(code)
    print("Original:")
    print(code)
    print("Expanded:")
    print(expanded_code)

    # Check that aliases are removed from use statements
    assert 'as Map' not in expanded_code
    assert 'as Tree' not in expanded_code
    assert 'as Vector' not in expanded_code

    # Check that aliases are expanded in code
    assert 'std::collections::HashMap::new()' in expanded_code
    assert 'std::collections::BTreeMap::new()' in expanded_code
    assert 'std::vec::Vec::new()' in expanded_code

    # Check that aliases are expanded in type annotations
    assert 'std::collections::HashMap<String, i32>' in expanded_code
    assert 'std::collections::BTreeMap<String, i32>' in expanded_code
    assert 'std::vec::Vec<i32>' in expanded_code

    # Check that complex nested types are handled (formatted across multiple lines)
    # The type should be expanded correctly regardless of formatting
    assert 'std::collections::HashMap<' in expanded_code
    assert 'std::collections::BTreeMap<i32, std::vec::Vec<u8>>' in expanded_code
    assert 'std::vec::Vec::from([1, 2, 3])' in expanded_code

    # Verify that the expanded code can be parsed correctly by get_standalone_uses_code_paths
    paths = rust_ast_parser.get_standalone_uses_code_paths(expanded_code)
    expected_paths = {
        ('std', 'collections', 'HashMap'),
        ('std', 'collections', 'BTreeMap'),
        ('std', 'vec', 'Vec'),
    }
    actual_paths = set(tuple(path) for path in paths)
    assert actual_paths == expected_paths

def test_expand_use_aliases_with_groups():
    code = '''
use std::collections::{HashMap as Map, BTreeMap as Tree};
use std::{vec::Vec as Vector, string::String as Str};

fn test() -> Map<Str, Vector<Tree<i32, i32>>> {
    Map::new()
}
'''

    expanded_code = rust_ast_parser.expand_use_aliases(code)
    print("Group aliases expanded:")
    print(expanded_code)

    # Check that all aliases are expanded (formatted across multiple lines)
    # The type should be expanded correctly regardless of formatting
    assert 'std::collections::HashMap<' in expanded_code
    assert 'std::string::String,' in expanded_code
    assert 'std::vec::Vec<std::collections::BTreeMap<i32, i32>>' in expanded_code
    assert 'std::collections::HashMap::new()' in expanded_code

def test_expand_use_aliases_dummy():
    code = '''
use std::collections::HashMap;
use std::vec::Vec;
fn test() -> HashMap<String, Vec<i32>> {
    HashMap::new()
}
'''
    expanded_code = rust_ast_parser.expand_use_aliases(code)
    assert expanded_code.strip() == code.strip(), 'Code without aliases should remain unchanged.'


def test_expand_use_aliases_with_self():
    code = '''
use std::collections::{self as collections, HashMap as Map};
use std::vec::{self as vec_mod, Vec};

fn test() {
    let map = Map::new();
    let other_map = collections::BTreeMap::new();
    let vec1 = Vec::new();
    let vec2 = vec_mod::Vec::new();
}
'''

    expanded_code = rust_ast_parser.expand_use_aliases(code)
    print("Self aliases expanded:")
    print(expanded_code)

    # Check that self aliases are expanded
    assert 'std::collections::BTreeMap::new()' in expanded_code
    assert 'std::vec::Vec::new()' in expanded_code
    assert 'std::collections::HashMap::new()' in expanded_code

    # Check that 'as collections' and 'as vec_mod' are removed
    assert 'as collections' not in expanded_code
    assert 'as vec_mod' not in expanded_code
    assert 'as Map' not in expanded_code

def test_add_attribute_to_function(code):
    new_code = rust_ast_parser.add_attr_to_function(code, "add", "#[inline]")
    print(new_code)
    assert new_code.count('#[inline]') == 1
    assert code.count('#[inline]') == 0

def test_add_attribute_to_struct(code):
    new_code = rust_ast_parser.add_attr_to_struct_union(code, "Foo", "#[derive(Debug)]")
    print(new_code)
    assert new_code.count('#[derive(Debug)]') == 1
    assert code.count('#[derive(Debug)]') == 0

    new_code = rust_ast_parser.add_attr_to_struct_union(code, "Foo", "#[derive(Copy, Clone)]")
    print(new_code)
    assert new_code.count('#[derive(Copy, Clone)]') == 1 # should not add duplicate
    assert code.count('#[derive(Copy, Clone)]') == 1

def test_add_derive_to_struct(code):
    # add derive on other structs
    new_code = rust_ast_parser.add_derive_to_struct_union(code, "Foo", "Debug")
    print(new_code)
    assert new_code.count('#[derive(Copy, Clone, Debug)]') == 1
    assert code.count('#[derive(Copy, Clone)]') == 1

    # add existing derive
    new_code = rust_ast_parser.add_derive_to_struct_union(code, "Foo", "Copy")
    print(new_code)
    assert new_code.count('#[derive(Copy, Clone)]') == 1
    assert new_code.count('#[derive(Copy)]') == 0
    assert code.count('#[derive(Copy, Clone)]') == 1

    # add derive on union
    new_code = rust_ast_parser.add_derive_to_struct_union(code, "Bar", "Debug")
    print(new_code)
    assert new_code.count('#[derive(Debug)]') == 1
    assert code.count('#[derive(Debug)]') == 0

def test_unidiomatic_function_cleanup():
    path = 'tests/rust_ast_parser/unidiomatic.rs'
    with open(path) as f:
        code = f.read()
    new_code = rust_ast_parser.unidiomatic_function_cleanup(code)
    print(new_code)
    assert new_code.find('extern "C"') == -1
    assert new_code.find('extern crate libc') == -1

def test_get_value_type_name():
    # Test static variables
    code = '''
static A: &str = "=2";
static mut B: i32 = 42;
static C: [u8; 3] = [1, 2, 3];
const PI: f64 = 3.14159;
const MAX_SIZE: usize = 100;
'''
    # Test basic static variable
    result = rust_ast_parser.get_value_type_name(code, "A")
    assert result == "static A: &str ;"

    # Test mutable static variable
    result = rust_ast_parser.get_value_type_name(code, "B")
    assert result == "static mut B: i32 ;"

    # Test array static variable
    result = rust_ast_parser.get_value_type_name(code, "C")
    assert result == "static C: [u8; 3] ;"

    # Test const variable
    result = rust_ast_parser.get_value_type_name(code, "PI")
    assert result == "const PI: f64 ;"

    # Test const variable with complex type
    result = rust_ast_parser.get_value_type_name(code, "MAX_SIZE")
    assert result == "const MAX_SIZE: usize ;"

    # Test non-existent variable
    try:
        rust_ast_parser.get_value_type_name(code, "D")
        assert False, "Should have raised an exception"
    except Exception as e:
        assert "Item 'D' not found" in str(e)
