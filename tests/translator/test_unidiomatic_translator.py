import os
import tempfile

import pytest

from sactor.c_parser import CParser
from sactor.translator import UnidiomaticTranslator
from sactor.translator.translator_types import TranslateResult
from tests.azure_llm import azure_llm
from tests.utils import config


def mock_query_impl(prompt, model, original=None, llm_instance=None):
    with open('tests/translator/mocks/course_manage_unidomatic_result') as f:
        return f.read()


@pytest.fixture
def llm():
    yield from azure_llm(mock_query_impl)


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
