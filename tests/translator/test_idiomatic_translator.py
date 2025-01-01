from functools import partial
from unittest.mock import MagicMock, patch

import pytest

from sactor.c_parser import CParser
from sactor.thirdparty.crown import Crown
from sactor.translator import IdiomaticTranslator, TranslateResult
from tests.azure_llm import azure_llm


def mock_query_impl(prompt, model, original=None, llm_instance=None):
    if prompt.find('Translate the following unidiomatic Rust function into idiomatic Rust.') != -1 and prompt.find('unsafe fn updateStudentInfo') != -1:
        with open('tests/translator/mocks/course_manage_idomatic_function') as f:
            return f.read()
    if prompt.find('''Translate the following Rust struct to idiomatic Rust. Try to avoid using raw pointers in the translation of the struct.
```rust
#[derive(Copy, Clone)]
#[repr(C)]
pub struct Student {''') != -1:
        with open('tests/translator/mocks/course_manage_idomatic_student') as f:
            return f.read()
    if prompt.find('''Translate the following Rust struct to idiomatic Rust. Try to avoid using raw pointers in the translation of the struct.
```rust
#[derive(Copy, Clone)]
#[repr(C)]
pub struct Course {''') != -1:
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


@pytest.fixture
def llm():
    yield from azure_llm(mock_query_impl)


@pytest.mark.skip(reason='Not implemented')
def test_idiomatic_translator(llm):
    file_path = 'tests/c_examples/course_manage.c'
    c2rust_path = 'tests/c_examples/course_manage_c2rust.rs'

    with open(c2rust_path) as f:
        c2rust_content = f.read()

    crown = Crown()
    crown.analyze(c2rust_content)
    c_parser = CParser(file_path)
    max_attempts = 6

    translator = IdiomaticTranslator(
        llm,
        c2rust_content,
        crown,
        c_parser,
        'tests/c_examples/course_manage_test.json',
        max_attempts=max_attempts,
        result_path='tests/c_examples/result',
        unidiomatic_result_path='tests/c_examples/result'
    )

    for struct in c_parser.get_function_info('updateStudentInfo').struct_dependencies:
        result = translator.translate_struct(struct)
        assert result == TranslateResult.SUCCESS
    result = translator.translate_function(
        c_parser.get_function_info('updateStudentInfo'))
    assert result == TranslateResult.SUCCESS
