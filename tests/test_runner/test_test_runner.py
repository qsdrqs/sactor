import json
import os
import tempfile

from sactor.test_runner import ExecutableTestRunner
from sactor.test_runner import TestRunnerResult as Result
from sactor.verifier import UnidiomaticVerifier, VerifyResult
from tests.test_generator.test_test_generator import (
    c_file_executable_arguments, c_file_executable_scanf)


def test_test_runner(c_file_executable_arguments):
    test_samples_path = 'tests/c_examples/add/test_task/sample_tests.json'
    with open(test_samples_path, 'r') as file:
        test_samples_output = json.load(file)

    len_test_samples_output = len(test_samples_output)
    runner = ExecutableTestRunner(
        test_samples_path,
        c_file_executable_arguments[0],
        feed_as_arguments=True
    )
    for i in range(len_test_samples_output):
        result, diff = runner.run_test(i)
        assert result == Result.PASSED
        assert diff is None or diff == ''

def test_test_runner2(c_file_executable_scanf):
    test_samples_path = 'tests/c_examples/add_scanf/test_task/sample_tests.json'
    with open(test_samples_path, 'r') as file:
        test_samples_output = json.load(file)

    len_test_samples_output = len(test_samples_output)
    runner = ExecutableTestRunner(
        test_samples_path,
        c_file_executable_scanf[0],
        feed_as_arguments=False
    )
    for i in range(len_test_samples_output):
        result, diff = runner.run_test(i)
        assert result == Result.PASSED
        assert diff is None or diff == ''

def test_test_runner_e2e(c_file_executable_arguments):
    test_samples_path = 'tests/c_examples/add/test_task/sample_tests.json'
    test_task = 'tests/c_examples/add/test_task/test_task.json'
    abs_test_samples_dir = os.path.abspath(os.path.dirname(test_samples_path))

    with tempfile.TemporaryDirectory() as tmpdirname:
        with open(test_task, 'r') as f:
            test_task = f.read().replace('${PLACE_HOLDER}', abs_test_samples_dir)
        with open(f'{tmpdirname}/test_task.json', 'w') as f:
            f.write(test_task)

        verifier = UnidiomaticVerifier(f'{tmpdirname}/test_task.json')
        result = verifier._run_tests(c_file_executable_arguments[0])
        assert result[0] == VerifyResult.SUCCESS

def test_test_runner_e2e_2(c_file_executable_scanf):
    test_samples_path = 'tests/c_examples/add_scanf/test_task/sample_tests.json'
    test_task = 'tests/c_examples/add_scanf/test_task/test_task.json'
    abs_test_samples_dir = os.path.abspath(os.path.dirname(test_samples_path))

    with tempfile.TemporaryDirectory() as tmpdirname:
        with open(test_task, 'r') as f:
            test_task = f.read().replace('${PLACE_HOLDER}', abs_test_samples_dir)
        with open(f'{tmpdirname}/test_task.json', 'w') as f:
            f.write(test_task)

        verifier = UnidiomaticVerifier(f'{tmpdirname}/test_task.json')
        result = verifier._run_tests(c_file_executable_scanf[0])
        assert result[0] == VerifyResult.SUCCESS
