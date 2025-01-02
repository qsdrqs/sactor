import json
from abc import ABC, abstractmethod

from .test_runner_types import TestRunnerResult


class TestRunner(ABC):
    def __init__(self, test_samples_path: str, target):
        with open(test_samples_path, 'r') as file:
            self.test_samples_output: list[dict] = json.load(file)

        self.target = target

    @abstractmethod
    def run_test(self, test_sample_number: int) -> tuple[TestRunnerResult, str | None]:
        pass
