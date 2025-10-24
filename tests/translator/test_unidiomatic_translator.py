import os
import tempfile

import pytest
from functools import partial
from unittest.mock import patch
from sactor.c_parser import CParser
from sactor.translator import UnidiomaticTranslator
from sactor.translator.translator_types import TranslateResult
from sactor.llm import LLM, llm_factory
from tests.utils import config
from tests.mock_llm import llm_with_mock


def mock_query_impl(prompt, model, original=None, llm_instance=None):
    with open('tests/translator/mocks/course_manage_unidomatic_result') as f:
        return f.read()


@pytest.fixture
def llm():
    # Use shared helper to create a patched LLM
    yield from llm_with_mock(mock_query_impl)


def test_unidiomatic_translator(llm, config):
    file_path = 'tests/c_examples/course_manage/course_manage.c'
    c2rust_path = 'tests/c_examples/course_manage/course_manage_c2rust.rs'

    with open(c2rust_path) as f:
        c2rust_content = f.read()

    c_parser = CParser(file_path)

    with tempfile.TemporaryDirectory() as tempdir:
        translator = UnidiomaticTranslator(
            llm=llm,
            c2rust_translation=c2rust_content,
            config=config,
            c_parser=c_parser,
            test_cmd_path='tests/c_examples/course_manage/course_manage_test.json',
            result_path=tempdir
        )

        result = translator.translate_struct(
            c_parser.get_struct_info('Student'))
        assert result == TranslateResult.SUCCESS
        assert os.path.exists(
            os.path.join(tempdir, 'translated_code_unidiomatic/structs/Student.rs'))

        result = translator.translate_struct(
            c_parser.get_struct_info('Course'))
        assert result == TranslateResult.SUCCESS
        assert os.path.exists(
            os.path.join(tempdir, 'translated_code_unidiomatic/structs/Course.rs'))

        result = translator.translate_function(
            c_parser.get_function_info('updateStudentInfo'))
        assert result == TranslateResult.SUCCESS
        assert os.path.exists(
            os.path.join(tempdir, 'translated_code_unidiomatic/functions/updateStudentInfo.rs'))


def test_c2rust_fallback_main_appends_exit(monkeypatch, tmp_path, config, llm):
    config['general']['unidiomatic_fallback_c2rust'] = True
    config['general']['max_translation_attempts'] = 1

    def fail_query(*args, **kwargs):
        raise AssertionError("LLM should not be called in fallback path")

    monkeypatch.setattr(llm, "query", fail_query)

    c_file = tmp_path / "main_only.c"
    c_file.write_text(
        "#include <stdio.h>\n\nint main(void) {\n    puts(\"hi\");\n    return 0;\n}\n"
    )
    c_parser = CParser(str(c_file))
    test_cmd_path = tmp_path / "test_commands.json"
    test_cmd_path.write_text("[]")
    result_path = tmp_path / "result"
    build_path = tmp_path / "build"
    translator = UnidiomaticTranslator(
        llm=llm,
        c2rust_translation='fn main() {\n    println!("hi");\n}\n',
        c_parser=c_parser,
        config=config,
        test_cmd_path=str(test_cmd_path),
        result_path=str(result_path),
        build_path=str(build_path),
    )

    function_info = c_parser.get_function_info('main')
    result = translator._translate_function_impl(function_info, attempts=1)

    assert result == TranslateResult.SUCCESS

    output_path = result_path / 'translated_code_unidiomatic' / 'functions' / 'main.rs'
    saved = output_path.read_text()
    expected = '''pub fn main() {
    println!("hi");
}
'''
    assert saved == expected


def test_llm_main_translation_appends_exit(monkeypatch, tmp_path, config, llm):
    config['general']['unidiomatic_fallback_c2rust'] = False
    config['general']['max_translation_attempts'] = 1

    response = '''----FUNCTION----
```rust
pub fn main() {
    println!("hi");
}
```
----END FUNCTION----
'''

    monkeypatch.setattr(llm, "query", lambda *args, **kwargs: response)


    c_file = tmp_path / "main_only.c"
    c_file.write_text("int main(void) {\n    return 0;\n}\n")
    c_parser = CParser(str(c_file))

    test_cmd_path = tmp_path / "test_commands.json"
    test_cmd_path.write_text("[]")
    result_path = tmp_path / "result"
    build_path = tmp_path / "build"

    translator = UnidiomaticTranslator(
        llm=llm,
        c2rust_translation="",
        c_parser=c_parser,
        config=config,
        test_cmd_path=str(test_cmd_path),
        result_path=str(result_path),
        build_path=str(build_path),
    )

    result = translator.translate_function(c_parser.get_function_info('main'))
    assert result == TranslateResult.SUCCESS

    saved = (result_path / 'translated_code_unidiomatic' / 'functions' / 'main.rs').read_text()
    expected = '''pub fn main() {
    println!("hi");
}
'''
    assert saved == expected
