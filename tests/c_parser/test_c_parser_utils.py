import os
import tempfile
import textwrap
import shutil
import pytest
import glob

from sactor.c_parser import c_parser_utils
from tests import utils as test_utils


def test_function_get_declaration():
    file_path = 'tests/verifier/mutation_test.c'
    with open(file_path, 'r') as f:
        source_code = f.read()
    output = c_parser_utils.remove_function_static_decorator(
        'add', source_code)
    print(output)
    assert test_utils.can_compile(output)


def test_function_get_declaration_with_comment():
    source_code = textwrap.dedent('''
/*comment here*/static int add(int a, int b) { // comment here
// comment here
/* comment here */    return a + b;
}
int main() {}''')

    output = c_parser_utils.remove_function_static_decorator(
        'add', source_code)
    print(output)
    assert test_utils.can_compile(output)

def test_expand_macro():
    c_code = textwrap.dedent("""
        #include <stdio.h>
        #define ADD(x, y) ((x) + (y))
        #define MSG "hello"

        #ifdef __cplusplus
        extern "C" {
        #endif

        int main() {
            int sum = ADD(2, 3);
            printf("%s\\n", MSG);
            return sum;
        }

        #ifdef __cplusplus
        }
        #endif
    """)

    tmpdir = tempfile.mkdtemp()
    try:
        test_file = os.path.join(tmpdir, "test.c")
        with open(test_file, "w") as f:
            f.write(c_code)

        out_path = c_parser_utils.expand_all_macros(test_file)
        with open(out_path) as f:
            content = f.read()

        # Assertions
        assert "#include <stdio.h>" in content, "Should restore includes"
        assert "ADD" not in content, "Macro should be expanded"
        assert "((2) + (3))" in content, "ADD macro should expand to ((2) + (3))"
        assert "MSG" not in content, "MSG macro should be expanded"
        assert 'printf("%s\\n", "hello");' in content, "MSG macro should expand to string in printf"
        assert "__cplusplus" not in content, "C++ guards should be removed"
        assert 'extern "C"' not in content, "extern \"C\" should be removed"

    finally:
        shutil.rmtree(tmpdir)

cases = sorted(glob.glob("tests/c_parser/unfold_typedefs/*_original.c"))

@pytest.mark.parametrize("original_file", cases)
def test_unfold_typedefs(original_file):
    expected_file = original_file.replace("_original.c", "_expected.c")
    tmpdir = tempfile.mkdtemp()
    try:
        test_file = os.path.join(tmpdir, "test.c")
        shutil.copy(original_file, test_file)
        out_path = c_parser_utils.unfold_typedefs(test_file);
        with open(out_path) as f:
            actual_content = f.read()
            print(actual_content)
        with open(expected_file) as f:
            expected_content = f.read()
        assert actual_content == expected_content, "The unfolded code does not match the expected code."
    finally:
        shutil.rmtree(tmpdir)

