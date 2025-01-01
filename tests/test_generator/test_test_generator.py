import pytest
import subprocess
import shutil
import tempfile

from sactor.c_parser import CParser
from sactor.test_generator import ExecutableTestGenerator
from tests.ollama_llm import ollama_llm


@pytest.fixture
def test_samples():
    return [
        "1 2",
        "3 4",
    ]

def mock_query_impl(prompt, model, original=None, llm_instance=None):
    # if llm_instance is not None and original is not None:
    #     return original(llm_instance, prompt, model)
    with open('tests/test_generator/mocks/mock_test_generator_result', 'r') as f:
        return f.read()


@pytest.fixture
def llm():
    yield from ollama_llm(mock_query_impl)

def c_file_executable(file_path):
    with tempfile.TemporaryDirectory() as tmpdirname:
        compiler = None
        if shutil.which("gcc"):
            compiler = "gcc"
        elif shutil.which("clang"):
            compiler = "clang"

        assert compiler is not None
        subprocess.run([compiler, file_path, "-o", f"{tmpdirname}/a.out"])

        executable = f"{tmpdirname}/a.out"
        yield (executable, file_path)

@pytest.fixture
def c_file_executable_arguments():
    file_path = "tests/c_examples/add/add.c"
    yield from c_file_executable(file_path)

@pytest.fixture
def c_file_executable_scanf():
    file_path = "tests/c_examples/add_scanf/add.c"
    yield from c_file_executable(file_path)

def test_generate_tests(llm, test_samples, c_file_executable_arguments):
    executable, file_path = c_file_executable_arguments
    c_parser = CParser(file_path)

    genetor = ExecutableTestGenerator(
        llm=llm,
        test_samples=test_samples,
        c_parser=c_parser,
        executable=executable,
        feed_as_arguments=True
    )
    genetor.generate(10)
    assert len(genetor.test_samples) == 12
    assert len(genetor.test_samples_output) == 12


def test_generate_tests2(llm, test_samples, c_file_executable_scanf):
    executable, file_path = c_file_executable_scanf
    c_parser = CParser(file_path)

    genetor = ExecutableTestGenerator(
        llm=llm,
        test_samples=test_samples,
        c_parser=c_parser,
        executable=executable,
        feed_as_arguments=False
    )
    genetor.generate(10)
    assert len(genetor.test_samples) == 12
    assert len(genetor.test_samples_output) == 12
