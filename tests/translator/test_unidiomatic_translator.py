import os
import tempfile
from unittest.mock import patch

import pytest

from sactor.c_parser import CParser
from sactor.llm import AzureOpenAILLM
from sactor.thirdparty.crown import Crown
from sactor.translator import UnidiomaticTranslator
from sactor.translator.translator_types import TranslationResult
from tests.translator.azure_llm import azure_llm


def mock_query_impl(prompt, model, original=None, llm_instance=None):
    with open('tests/translator/mocks/course_manage_unidomatic_result') as f:
        return f.read()


@pytest.fixture
def llm():
    yield from azure_llm(mock_query_impl)


def test_unidiomatic_translator(llm):
    file_path = 'tests/c_examples/course_manage.c'
    c2rust_path = 'tests/c_examples/course_manage_c2rust.rs'

    with open(c2rust_path) as f:
        c2rust_content = f.read()

    c_parser = CParser(file_path)

    with tempfile.TemporaryDirectory() as tempdir:
        translator = UnidiomaticTranslator(
            llm, c2rust_content, c_parser, ['python', 'tests/c_examples/course_manage_test.py'], result_path=tempdir)

        result = translator.translate_struct(
            c_parser.get_struct_info('Student'))
        assert result == TranslationResult.SUCCESS
        with open('tests/c_examples/result/translated_code_unidiomatic/structs/Student.rs') as f:
            with open(os.path.join(tempdir, 'translated_code_unidiomatic/structs/Student.rs')) as f2:
                assert f.read() == f2.read()

        result = translator.translate_struct(
            c_parser.get_struct_info('Course'))
        assert result == TranslationResult.SUCCESS

        with open('tests/c_examples/result/translated_code_unidiomatic/structs/Course.rs') as f:
            with open(os.path.join(tempdir, 'translated_code_unidiomatic/structs/Course.rs')) as f2:
                assert f.read() == f2.read()

        result = translator.translate_function(
            c_parser.get_function_info('updateStudentInfo'))
        assert result == TranslationResult.SUCCESS
        assert os.path.exists(
            os.path.join(tempdir, 'translated_code_unidiomatic/functions/updateStudentInfo.rs'))
        with open('tests/c_examples/result/translated_code_unidiomatic/functions/updateStudentInfo.rs') as f:
            with open(os.path.join(tempdir, 'translated_code_unidiomatic/functions/updateStudentInfo.rs')) as f2:
                assert f.read() == f2.read()
