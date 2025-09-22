import json
import tempfile

import pytest
from functools import partial
from unittest.mock import patch

from sactor import utils
from sactor.utils import read_file
from sactor.test_generator import ExecutableTestGenerator
from sactor.llm import LLM, llm_factory
from tests.mock_llm import llm_with_mock
from tests.utils import c_file_executable


@pytest.fixture
def test_samples():
    return [
        "1 2",
        "3 4",
    ]


def mock_query_impl(prompt, model, original=None, llm_instance=None):
    # if llm_instance is not None and original is not None:
    #     return original(llm_instance, prompt, model)
    return read_file('tests/test_generator/mocks/mock_test_generator_result')


@pytest.fixture
def llm():
    # Use shared helper to create a patched LLM
    yield from llm_with_mock(mock_query_impl)


@pytest.fixture
def c_file_executable_arguments():
    file_path = "tests/c_examples/add/add.c"
    yield from c_file_executable(file_path)


@pytest.fixture
def c_file_executable_scanf():
    file_path = "tests/c_examples/add_scanf/add.c"
    yield from c_file_executable(file_path)


def check_test_samples_output(expected_output, actual_output):
    expected = json.loads(expected_output)
    actual = json.loads(actual_output)
    if len(expected) != len(actual):
        return False
    input_output = {}
    for i in range(len(expected)):
        input_ = expected[i]['input']
        output = expected[i]['output']
        input_output[input_] = output
    for i in range(len(actual)):
        input_ = actual[i]['input']
        output = actual[i]['output']
        if input_ not in input_output:
            return False
        if input_output[input_] != output:
            return False

    return True

def test_generate_tests(llm, test_samples, c_file_executable_arguments):
    executable, file_path = c_file_executable_arguments

    generator = ExecutableTestGenerator(
        file_path=file_path,
        test_samples=test_samples,
        executable=executable,
        feed_as_arguments=True
    )
    generator.llm = llm  # mock llm
    generator.generate_tests(10)
    assert len(generator.test_samples) == 12
    assert len(generator.test_samples_output) == 12

    with tempfile.TemporaryDirectory() as tmpdirname:
        generator.create_test_task(
            f'{tmpdirname}/test_task.json', f'{tmpdirname}/test_samples.json')
        test_task = read_file(f'{tmpdirname}/test_task.json')
        test_samples = read_file(f'{tmpdirname}/test_samples.json')

    assert test_task.replace(tmpdirname, '.') == read_file('tests/c_examples/add/test_task/test_task.json')
    assert check_test_samples_output(read_file('tests/c_examples/add/test_task/test_samples.json'), test_samples)


def test_generate_tests2(llm, test_samples, c_file_executable_scanf):
    executable, file_path = c_file_executable_scanf

    generator = ExecutableTestGenerator(
        file_path=file_path,
        test_samples=test_samples,
        executable=executable,
        feed_as_arguments=False
    )
    generator.llm = llm  # mock llm
    generator.generate_tests(10)
    assert len(generator.test_samples) == 12
    assert len(generator.test_samples_output) == 12

    with tempfile.TemporaryDirectory() as tmpdirname:
        generator.create_test_task(
            f'{tmpdirname}/test_task.json', f'{tmpdirname}/test_samples.json')
        test_task = read_file(f'{tmpdirname}/test_task.json')
        test_samples = read_file(f'{tmpdirname}/test_samples.json')

    assert test_task.replace(tmpdirname, '.') == read_file('tests/c_examples/add_scanf/test_task/test_task.json')
    assert check_test_samples_output(read_file('tests/c_examples/add_scanf/test_task/test_samples.json'), test_samples)
