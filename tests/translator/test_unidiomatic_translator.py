import os
import tempfile
from unittest.mock import patch

import pytest

from sactor.c_parser import CParser
from sactor.llm import AzureOpenAILLM
from sactor.thirdparty.crown import Crown
from sactor.translator import UnidiomaticTranslator
from sactor.translator.translator_types import TranslationResult


def test_unidiomatic_translator():
    file_path = 'tests/c_examples/course_manage.c'
    c2rust_path = 'tests/c_examples/course_manage_c2rust.rs'

    with open(c2rust_path) as f:
        c2rust_content = f.read()

    c_parser = CParser(file_path)

    llm = AzureOpenAILLM()

    # Mock the _query_impl method
    mock_resp_path = 'tests/translator/mocks/course_manage_unidomatic_result'
    with open(mock_resp_path) as f:
        mock_response_content = f.read()
    with patch.object(llm, '_query_impl', return_value=mock_response_content):
        with tempfile.TemporaryDirectory() as tempdir:
            translator = UnidiomaticTranslator(
                llm, c2rust_content, c_parser, ['python', 'tests/c_examples/course_manage_test.py'], result_path=tempdir)

            result = translator.translate_struct(c_parser.structs_unions['Student'])
            assert result == TranslationResult.SUCCESS
            with open('tests/c_examples/result/translated_code_unidiomatic/structs/Student.rs') as f:
                with open(os.path.join(tempdir, 'translated_code_unidiomatic/structs/Student.rs')) as f2:
                    assert f.read() == f2.read()

            result = translator.translate_struct(c_parser.structs_unions['Course'])
            assert result == TranslationResult.SUCCESS

            with open('tests/c_examples/result/translated_code_unidiomatic/structs/Course.rs') as f:
                with open(os.path.join(tempdir, 'translated_code_unidiomatic/structs/Course.rs')) as f2:
                    assert f.read() == f2.read()

            result = translator.translate_function(
                c_parser.functions['updateStudentInfo'])
            assert result == TranslationResult.SUCCESS
            assert os.path.exists(
                os.path.join(tempdir, 'translated_code_unidiomatic/functions/updateStudentInfo.rs'))
            with open('tests/c_examples/result/translated_code_unidiomatic/functions/updateStudentInfo.rs') as f:
                with open(os.path.join(tempdir, 'translated_code_unidiomatic/functions/updateStudentInfo.rs')) as f2:
                    assert f.read() == f2.read()
