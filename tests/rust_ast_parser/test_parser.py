import pytest

from sactor import rust_ast_parser


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
    assert struct_definition == '#[derive(Copy, Clone)]\nstruct Foo {\n    a: i32,\n    b: i32,\n    self_ptr: *const Foo,\n}\n'


def test_expose_function_to_c(code):
    exposed_code = rust_ast_parser.expose_function_to_c(code, "add")
    assert exposed_code.count('extern "C"') == 1
    assert exposed_code.count('#[no_mangle]') == 1

def test_get_union_definition(code):
    union_definition = rust_ast_parser.get_union_definition(code, "Bar")
    assert union_definition == 'union Bar {\n    a: i32,\n    b: i32,\n}\n'

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
