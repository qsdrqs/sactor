import pytest

import rust_ast_parser


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
    assert exposed_code.count('extern "C"') == 2
    assert exposed_code.count('#[no_mangle]') == 2

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
