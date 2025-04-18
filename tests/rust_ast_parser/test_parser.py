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
