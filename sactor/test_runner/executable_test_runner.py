import difflib
import os
import json
import subprocess
from typing import override, Optional

from sactor import logging as sactor_logging
from sactor import utils

from .test_runner import TestRunner
from .test_runner_types import TestRunnerResult


logger = sactor_logging.get_logger(__name__)


class ExecutableTestRunner(TestRunner):
    def __init__(
        self,
        test_samples_path: str,
        target: str,
        config_path=None,
        feed_as_arguments=True,
    ):
        super().__init__(
            test_samples_path=test_samples_path,
            target=target,
            config_path=config_path,
        )
        self.feed_as_arguments = feed_as_arguments

    def _compare_outputs(self, actual: str, expected: str) -> tuple[TestRunnerResult, Optional[str]]:
        if actual == expected:
            return TestRunnerResult.PASSED, None

        differ = difflib.Differ()
        diff = list(differ.compare(actual.splitlines(), expected.splitlines()))
        diff_text = '\n'.join(diff)

        return TestRunnerResult.FAILED, diff_text

    def _save_test_outputs(self, save_path, test_sample_number: int, compare_result, expected_output: str, actual_output: str) -> None:
        # mkdir -p of parent directory of save_path
        if os.path.dirname(save_path):
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
        if os.path.exists(save_path):
            with open(save_path, 'r') as f:
                current_data = json.load(f)
        else:
            current_data = []
        while len(current_data) <= test_sample_number:
            current_data.append({})
        current_data[test_sample_number]['input'] = self.test_samples_output[test_sample_number]['input']
        current_data[test_sample_number]['expected_output'] = expected_output
        if compare_result[0] == TestRunnerResult.PASSED:
            current_data[test_sample_number]['actual_output'] = expected_output
            current_data[test_sample_number]['result'] = 'PASSED'
            current_data[test_sample_number]['diff'] = None
        else:
            current_data[test_sample_number]['actual_output'] = actual_output
            current_data[test_sample_number]['result'] = 'FAILED'
            current_data[test_sample_number]['diff'] = compare_result[1]
        with open(save_path, 'w') as f:
            json.dump(current_data, f, indent=4)

    @override
    def run_test(self, test_sample_number: int, save_path=None) -> tuple[TestRunnerResult, Optional[str]]:
        len_test_samples_output = len(self.test_samples_output)
        if test_sample_number >= len_test_samples_output or test_sample_number < 0:
            raise ValueError(
                f'test_sample_number should be in the range [0, {len_test_samples_output})')
        test_sample = self.test_samples_output[test_sample_number]
        test_sample_input = test_sample['input']
        test_sample_output = test_sample['output']

        try:
            if self.feed_as_arguments:
                feed_input_str = f'{self.target} {test_sample_input}'
                cmd = feed_input_str.split()
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=self.timeout_seconds,
                )
            else:
                cmd = self.target
                result = subprocess.run(
                    cmd,
                    input=test_sample_input.encode() + '\n'.encode(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=self.timeout_seconds,
                )
        except subprocess.TimeoutExpired as e:
            logger.error('Test %d timed out: %s', test_sample_number, e)
            raise ValueError(f'Test {test_sample_number} timed out: {e}')


        target_output = utils.normalize_string(
            result.stdout.decode() + result.stderr.decode())

        # compare target output with expected output
        compare_result = self._compare_outputs(target_output, test_sample_output)
        if save_path:
            self._save_test_outputs(
                save_path,
                test_sample_number,
                compare_result,
                test_sample_output,
                target_output,
            )
        return compare_result
