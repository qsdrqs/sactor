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
    assert struct_definition == 'struct Foo {\n    a: i32,\n    b: i32,\n}\n'


def test_expose_function_to_c(code):
    exposed_code = rust_ast_parser.expose_function_to_c(code)
    all_function_signatures = rust_ast_parser.get_func_signatures(exposed_code)
    assert exposed_code.count('extern "C"') == len(all_function_signatures)
    assert exposed_code.count('#[no_mangle]') == len(all_function_signatures)

def test_get_union_definition(code):
    union_definition = rust_ast_parser.get_union_definition(code, "Bar")
    assert union_definition == 'union Bar {\n    a: i32,\n    b: i32,\n}\n'

def test_combine_struct_function():
    function_path = 'tests/rust_ast_parser/test_combine/test_function.rs'
    struct_path = 'tests/rust_ast_parser/test_combine/test_struct.rs'
    with open(function_path) as f:
        function_code = f.read()
    with open(struct_path) as f:
        struct_code = f.read()
    combined_code = rust_ast_parser.combine_struct_function(struct_code, function_code)

    combine_path = 'tests/rust_ast_parser/test_combine/test_combine.rs'
    with open(combine_path) as f:
        expected_code = f.read()
    assert combined_code == expected_code

def test_get_uses_code(code):
    uses_code = rust_ast_parser.get_uses_code(code)
    assert uses_code == ['use std :: collections :: HashMap ;', 'use libc :: c_int ;']

def test_rename_function(code):
    new_code = rust_ast_parser.rename_function(code, "fib", "fibonacci")
    assert code.count('fib') == new_code.count('fibonacci')

def test_count_unsafe(code):
    assert rust_ast_parser.count_unsafe_blocks(code) == 1