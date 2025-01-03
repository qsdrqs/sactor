import json
import os
import shutil
from abc import ABC, abstractmethod

from sactor.c_parser import CParser
from sactor.llm import LLM


class TestGenerator(ABC):
    def __init__(self, llm: LLM, c_parser: CParser, test_samples, input_document=None):
        self.llm = llm
        self.init_test_samples = test_samples
        self.test_samples = test_samples
        self.c_parser = c_parser
        self.input_document = input_document
        self.test_samples_output = []

        # check valgrind existence
        if shutil.which('valgrind') is None:
            raise ValueError(
                "valgrind is not installed. Please install valgrind first for test generation.")
        self.valgrind_cmd = [
            'valgrind',
            '--error-exitcode=1',
            '--leak-check=no',
            '--',
        ]

    @abstractmethod
    def generate_tests(self, count):
        pass

    @abstractmethod
    def create_test_task(self, task_path, test_sample_path):
        pass

    def _check_runner_exist(self):
        # check if `sactor-test-runner` is installed
        if shutil.which('sactor-test-runner') is None:
            raise ValueError(
                "sactor-test-runner is not installed. Please install sactor first.")

    def export_test_samples(self, file_path):
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w') as f:
            json.dump(self.test_samples_output, f, indent=4)
