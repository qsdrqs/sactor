import json
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

    @abstractmethod
    def generate(self, count):
        pass

    def export_test_samples(self, filename):
        with open(filename) as f:
            json.dump(self.test_samples_output, f)
