import json
import os
import time
from abc import ABC, abstractmethod

import tiktoken

from sactor import utils


class LLM(ABC):
    def __init__(self, config, encoding=None, system_msg=None):
        self.config = config
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

    def query(self, prompt, model=None, override_system_message=None) -> str:
        utils.print_red(prompt)
        old_system_msg = None
        if override_system_message is not None:
            old_system_msg = self.system_msg
            self.system_msg = override_system_message

        start_time = time.time()
        response = self._query_impl(prompt, model)
        end_time = time.time()
        self.last_costed_time = end_time - start_time
        self.total_costed_time += self.last_costed_time

        tokens = self.enc.encode(response + prompt)
        self.last_costed_tokens = len(tokens)
        self.total_costed_tokens += self.last_costed_tokens

        utils.print_green(response)

        if override_system_message is not None and old_system_msg is not None:
            # Restore old message
            self.system_msg = old_system_msg

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
            json.dump(statistic_result, f, indent=4)
