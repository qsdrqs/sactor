import json
from abc import ABC, abstractmethod
from typing import Optional

from sactor import utils

from .test_runner_types import TestRunnerResult


class TestRunner(ABC):
    def __init__(self, test_samples_path: str, target, config_path=None):
        with open(test_samples_path, 'r') as file:
            self.test_samples_output: list[dict] = json.load(file)

        self.config = utils.try_load_config(config_path)
        self.timeout_seconds = self.config['test_runner']['timeout_seconds']
        self.target = target

    @abstractmethod
    def run_test(self, test_sample_number: int) -> tuple[TestRunnerResult, Optional[str]]:
        pass
