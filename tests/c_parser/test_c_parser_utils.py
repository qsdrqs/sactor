import os
import tempfile
import textwrap
import shutil
import pytest
import glob
from types import SimpleNamespace

from clang import cindex

from sactor.c_parser import c_parser_utils
from sactor.c_parser.c_parser import CParser, _discover_intrinsic_aliases
from sactor.utils import read_file
from sactor import utils as sactor_utils
from tests import utils as test_utils


def test_function_get_declaration():
    file_path = 'tests/verifier/mutation_test.c'
    source_code = read_file(file_path)
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
        content = read_file(out_path)

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


def test_intrinsic_aliases_cached(monkeypatch):
    _discover_intrinsic_aliases.cache_clear()

    calls = {
        "count": 0,
    }

    def fake_run_command(cmd, check=True):
        calls["count"] += 1
        assert cmd[:4] == ["clang", "-E", "-P", "-v"]
        return SimpleNamespace(stdout="#define __SIZE_TYPE__ long unsigned int\n")

    monkeypatch.setattr("sactor.utils.run_command", fake_run_command)

    aliases = _discover_intrinsic_aliases()
    assert aliases == {"size_t": "long unsigned int"}
    assert calls["count"] == 1

    aliases_again = _discover_intrinsic_aliases()
    assert aliases_again == aliases
    assert calls["count"] == 1

    _discover_intrinsic_aliases.cache_clear()


def test_remove_inline_specifiers(tmp_path):
    source = textwrap.dedent(
        '''
        static inline int sum(int a, int b) {
            return a + b;
        }

        inline
        int difference(int a, int b);

        inline
        int difference(int a, int b) {
            return a - b;
        }

        int main(void) {
            return sum(1, difference(2, 1));
        }

        // inline comment should remain inline
        '''
    ).lstrip()

    c_file = tmp_path / "inline_example.c"
    c_file.write_text(source)

    out_path = c_parser_utils.remove_inline_specifiers(str(c_file))
    assert out_path == str(c_file)

    updated_content = c_file.read_text()
    assert "static inline" not in updated_content
    assert "\ninline\nint difference" not in updated_content
    assert "// inline comment should remain inline" in updated_content

    parser = CParser(str(c_file), omit_error=True)
    for function in parser.get_functions():
        has_inline_keyword = any(
            token.kind == cindex.TokenKind.KEYWORD and token.spelling == 'inline'
            for token in sactor_utils.cursor_get_tokens(function.node)
        )
        assert not has_inline_keyword

    assert test_utils.can_compile(updated_content)

cases = sorted(glob.glob("tests/c_parser/unfold_typedefs/*_original.c"))

@pytest.mark.parametrize("original_file", cases)
def test_unfold_typedefs(original_file):
    expected_file = original_file.replace("_original.c", "_expected.c")
    tmpdir = tempfile.mkdtemp()
    try:
        test_file = os.path.join(tmpdir, "test.c")
        shutil.copy(original_file, test_file)
        out_path = c_parser_utils.unfold_typedefs(test_file);
        actual_content = read_file(out_path)
        print(actual_content)
        expected_content = read_file(expected_file)
        assert actual_content == expected_content, "The unfolded code does not match the expected code."
    finally:
        shutil.rmtree(tmpdir)
