import tempfile
from functools import partial
from unittest.mock import patch

import pytest

from sactor import utils
from sactor.c_parser import CParser
from sactor.llm import LLM, llm_factory
from sactor.thirdparty.crown import Crown
from sactor.translator import IdiomaticTranslator, TranslateResult
from sactor.verifier.verifier_types import VerifyResult
from tests.mock_llm import llm_with_mock
from tests.utils import config

pytestmark = pytest.mark.filterwarnings(
    "ignore:Pydantic serializer warnings:UserWarning"
)


def mock_query_impl(prompt, model, original=None, llm_instance=None):
    if "The following test harness failed to compile." in prompt:
        if "struct Student" in prompt:
            with open('tests/verifier/mock_results/mock_student_harness') as f:
                return f.read()
        if "struct Course" in prompt:
            with open('tests/verifier/mock_results/mock_course_harness') as f:
                return f.read()
    if "The following struct converters failed to compile." in prompt:
        if "pub struct Student" in prompt:
            with open('tests/verifier/mock_results/mock_student_harness') as f:
                return f.read()
        if "pub struct Course" in prompt:
            with open('tests/verifier/mock_results/mock_course_harness') as f:
                return f.read()
    if prompt.find('Translate the following unidiomatic Rust function into idiomatic Rust.') != -1 and prompt.find('unsafe fn updateStudentInfo') != -1:
        with open('tests/translator/mocks/course_manage_idomatic_function') as f:
            return f.read()
    if prompt.find('''Translate the following Rust struct to idiomatic Rust. Try to avoid using raw pointers in the translation of the struct.
If the struct is designed as a cloneable struct, try to add/implement the `Clone` trait for the struct.
```rust
#[derive(Copy, Clone, Debug)]
#[repr(C)]
pub struct Student {''') != -1:
        with open('tests/translator/mocks/course_manage_idomatic_student') as f:
            return f.read()
    if prompt.find('''Translate the following Rust struct to idiomatic Rust. Try to avoid using raw pointers in the translation of the struct.
If the struct is designed as a cloneable struct, try to add/implement the `Clone` trait for the struct.
```rust
#[derive(Copy, Clone, Debug)]
#[repr(C)]
pub struct Course {''') != -1:
        with open('tests/translator/mocks/course_manage_idomatic_course') as f:
            return f.read()
    if 'You are assisting with automated Rust roundtrip tests.' in prompt:
        return '----FILL----\n// populate sample data\n----END FILL----'
    if prompt.find('Generate the harness for the function updateStudentInfo_idiomatic') != -1:
        with open('tests/translator/mocks/course_manage_idomatic_function_harness') as f:
            return f.read()
    if prompt.find('There are two structs: Student and CStudent') != -1:
        with open('tests/verifier/mock_results/mock_student_harness') as f:
            return f.read()
    if prompt.find('There are two structs: Course and CCourse') != -1:
        with open('tests/verifier/mock_results/mock_course_harness') as f:
            return f.read()
    else:
        if llm_instance is not None and original is not None:
            return original(llm_instance, prompt, model)
        raise Exception('No llm_instance provided')


@pytest.fixture
def llm():
    # Use shared helper to create a patched LLM
    yield from llm_with_mock(mock_query_impl)


def test_idiomatic_translator(llm, config):
    file_path = 'tests/c_examples/course_manage/course_manage.c'
    c2rust_path = 'tests/c_examples/course_manage/course_manage_c2rust.rs'

    with open(c2rust_path) as f:
        c2rust_content = f.read()

    crown = Crown()
    crown.analyze(c2rust_content)
    c_parser = CParser(file_path)
    max_attempts = 6

    with tempfile.TemporaryDirectory() as tempdir:
        translator = IdiomaticTranslator(
            llm,
            c2rust_content,
            crown,
            c_parser,
            'tests/c_examples/course_manage/course_manage_test.json',
            config=config,
            result_path=tempdir,
            unidiomatic_result_path='tests/c_examples/course_manage/result'
        )

        course = c_parser.get_struct_info('Course')
        result = translator.translate_struct(course)
        assert result == TranslateResult.SUCCESS

        student = c_parser.get_struct_info('Student')
        result = translator.translate_struct(student)
        assert result == TranslateResult.SUCCESS

        result = translator.translate_function(
            c_parser.get_function_info('updateStudentInfo'))
        assert result == TranslateResult.SUCCESS
