
from sactor.c_parser import c_parser_utils
from tests import utils as test_utils


def test_function_get_declaration():
    file_path = 'tests/verifier/mutation_test.c'
    with open(file_path, 'r') as f:
        source_code = f.read()
    output = c_parser_utils.remove_function_static_decorator('add', source_code)
    print(output)
    assert test_utils.can_compile(output)
