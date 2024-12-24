import json
import os
import time
from abc import ABC, abstractmethod

import tiktoken
from sactor import utils


class LLM(ABC):
    def __init__(self, encoding=None, mock_code_file=None, system_msg=None):
        self.mock_code_file = mock_code_file

        if system_msg is None:
            system_msg = '''
You are an expert in translating code from C to Rust. You will take all information from the user as reference, and will output the translated code into the format that the user wants.
'''

        self.system_msg = system_msg

        if not encoding:
            encoding = "o200k_base"  # default encoding, for gpt-4o

        self.enc = tiktoken.get_encoding(encoding)
        self.total_costed_tokens = 0
        self.last_costed_tokens = 0
        self.total_costed_time = 0
        self.last_costed_time = 0

    @abstractmethod
    def _query_impl(self, prompt, model) -> str:
        pass

    def query(self, prompt, model=None) -> str:
        if self.mock_code_file is not None:
            with open(self.mock_code_file, "r") as f:
                return f.read()
        utils.print_red(prompt)

        start_time = time.time()
        response = self._query_impl(prompt, model)
        end_time = time.time()
        self.last_costed_time = end_time - start_time
        self.total_costed_time += self.last_costed_time

        tokens = self.enc.encode(response + prompt)
        self.last_costed_tokens = len(tokens)
        self.total_costed_tokens += self.last_costed_tokens

        utils.print_green(response)

        return response

    def statistic(self, path: str) -> None:
        if os.path.isdir(path):
            path = os.path.join(path, "statistic.json")
        statistic_result = {
            "total_costed_tokens": self.total_costed_tokens,
            "total_costed_time": self.total_costed_time,
            "last_costed_tokens": self.last_costed_tokens,
            "last_costed_time": self.last_costed_time,
        }
        with open(path, "w") as f:
            json.dump(statistic_result, f)
