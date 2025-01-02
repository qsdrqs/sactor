import difflib
import subprocess
from typing import override

from sactor import utils

from .test_runner import TestRunner
from .test_runner_types import TestRunnerResult


class ExecutableTestRunner(TestRunner):
    def __init__(
        self,
        test_samples_path: str,
        target: str,
        feed_as_arguments=True,
    ):
        super().__init__(
            test_samples_path=test_samples_path,
            target=target
        )
        self.feed_as_arguments = feed_as_arguments

    def _compare_outputs(self, actual: str, expected: str) -> tuple[TestRunnerResult, str | None]:
        if actual == expected:
            return TestRunnerResult.PASSED, None

        differ = difflib.Differ()
        diff = list(differ.compare(actual.splitlines(), expected.splitlines()))
        diff_text = '\n'.join(diff)

        return TestRunnerResult.FAILED, diff_text

    @override
    def run_test(self, test_sample_number: int) -> tuple[TestRunnerResult, str | None]:
        len_test_samples_output = len(self.test_samples_output)
        if test_sample_number >= len_test_samples_output or test_sample_number < 0:
            raise ValueError(
                f'test_sample_number should be in the range [0, {len_test_samples_output})')
        test_sample = self.test_samples_output[test_sample_number]
        test_sample_input = test_sample['input']
        test_sample_output = test_sample['output']

        if self.feed_as_arguments:
            feed_input_str = f'{self.target} {test_sample_input}'
            cmd = feed_input_str.split()
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        else:
            cmd = self.target
            result = subprocess.run(
                cmd,
                input=test_sample_input.encode(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        target_output = utils.normalize_string(
            result.stdout.decode() + result.stderr.decode())

        # compare target output with expected output
        return self._compare_outputs(target_output, test_sample_output)
