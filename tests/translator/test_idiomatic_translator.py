from unittest.mock import Mock, patch
import tempfile

import pytest

from sactor.c_parser import CParser
from sactor.llm import AzureOpenAILLM
from sactor.thirdparty.crown import Crown
from sactor.translator import IdiomaticTranslator
from sactor.translator import TranslationResult


def test_idiomatic_translator():
    file_path = 'tests/c_examples/course_manage.c'
    c2rust_path = 'tests/c_examples/course_manage_c2rust.rs'

    with open(c2rust_path) as f:
        c2rust_content = f.read()

    crown = Crown()
    crown.analyze(c2rust_content)
    c_parser = CParser(file_path)

    llm = AzureOpenAILLM()

    translator = IdiomaticTranslator(
        llm,
        c2rust_content,
        crown,
        c_parser,
        'ls',
        result_path='tests/c_examples/result',
        unidiomatic_result_path='tests/c_examples/result'
    )

    for struct in c_parser.functions['updateStudentInfo'].struct_dependencies:
        result = translator.translate_struct(struct)
        assert result == TranslationResult.SUCCESS
    translator.translate_function(c_parser.functions['updateStudentInfo'])
