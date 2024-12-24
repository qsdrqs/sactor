from unittest.mock import Mock, patch
import tempfile
from functools import partial

import pytest

from sactor.c_parser import CParser
from sactor.llm import AzureOpenAILLM
from sactor.thirdparty.crown import Crown
from sactor.translator import IdiomaticTranslator
from sactor.translator import TranslationResult


def mock_query_impl(prompt, model, original=None, llm_instance=None):
    if prompt.find('unsafe fn updateStudentInfo') != -1:
        with open('tests/translator/mocks/course_manage_idomatic_function') as f:
            return f.read()
    if prompt.find('Translate the following Rust struct to idiomatic Rust') != -1 and prompt.find('struct Student') != -1:
        with open('tests/translator/mocks/course_manage_idomatic_student') as f:
            return f.read()
    if prompt.find('Translate the following Rust struct to idiomatic Rust') != -1 and prompt.find('struct Course') != -1:
        with open('tests/translator/mocks/course_manage_idomatic_course') as f:
            return f.read()
    if prompt.find('Generate the harness for the function updateStudentInfo_idiomatic') != -1:
        with open('tests/translator/mocks/course_manage_idomatic_function_harness') as f:
            return f.read()
    else:
        if llm_instance is not None and original is not None:
            return original(llm_instance, prompt, model)
        else:
            raise Exception('No llm_instance provided')


def test_idiomatic_translator():
    file_path = 'tests/c_examples/course_manage.c'
    c2rust_path = 'tests/c_examples/course_manage_c2rust.rs'

    with open(c2rust_path) as f:
        c2rust_content = f.read()

    crown = Crown()
    crown.analyze(c2rust_content)
    c_parser = CParser(file_path)

    llm = AzureOpenAILLM()

    # Mocking the _query_impl method
    original_query = AzureOpenAILLM._query_impl
    mock_with_original = partial(mock_query_impl, original=original_query, llm_instance=llm)

    with patch('sactor.llm.AzureOpenAILLM._query_impl', side_effect=mock_with_original):
        translator = IdiomaticTranslator(
            llm,
            c2rust_content,
            crown,
            c_parser,
            ['python', 'tests/c_examples/course_manage_test.py'],
            result_path='tests/c_examples/result',
            unidiomatic_result_path='tests/c_examples/result'
        )

        for struct in c_parser.functions['updateStudentInfo'].struct_dependencies:
            result = translator.translate_struct(struct)
            assert result == TranslationResult.SUCCESS
        translator.translate_function(c_parser.functions['updateStudentInfo'])
