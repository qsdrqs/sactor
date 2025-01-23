import json
import os
import shutil
from abc import ABC, abstractmethod

from sactor import utils
from sactor.c_parser import CParser
from sactor.llm import llm_factory
from .test_generator_types import TestGeneratorResult


class TestGenerator(ABC):
    def __init__(
        self,
        file_path,
        test_samples,
        config_path=None,
        test_samples_path=None,
        input_document=None,
    ):
        self.init_test_samples = test_samples
        self.test_samples = set(test_samples)
        self.file_path = file_path
        if input_document:
            with open(input_document, 'r') as f:
                self.input_document = f.read()
        else:
            self.input_document = None
        self.test_samples_output = []
        self.config = utils.try_load_config(config_path)
        self.max_attempts = self.config['test_generator']['max_attempts']
        self.timeout_seconds = self.config['test_runner']['timeout_seconds']

        # get the LLM
        self.llm = llm_factory(self.config)

        self.c_parser = CParser(file_path)

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

        # parse the test_samples path
        if test_samples_path:
            with open(test_samples_path, 'r') as f:
                test_samples = json.load(f)
            for sample in test_samples:
                self.test_samples.add(sample['input']) # only append the input, ignore the output

    @abstractmethod
    def generate_tests(self, count) -> TestGeneratorResult:
        pass

    @abstractmethod
    def create_test_task(self, task_path, test_sample_path):
        pass

    def _check_runner_exist(self):
        # check if `sactor` is installed
        if shutil.which('sactor') is None:
            raise ValueError(
                "sactor is not installed. Please install sactor first.")

    def export_test_samples(self, file_path):
        dir = os.path.dirname(file_path)
        if dir:
            os.makedirs(dir, exist_ok=True)
        with open(file_path, 'w') as f:
            json.dump(self.test_samples_output, f, indent=4)
