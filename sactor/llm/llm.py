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
            system_msg = config['general']['system_message']

        self.system_msg = system_msg

        if not encoding:
            encoding = config['general']['encoding']

        self.enc = tiktoken.get_encoding(encoding)
        self.costed_input_tokens = []
        self.costed_output_tokens = []
        self.costed_time = []

    @abstractmethod
    def _query_impl(self, prompt, model) -> str:
        pass

    def query(self, prompt, model=None, override_system_message=None) -> str:
        input_tokens = self.enc.encode(prompt)
        if len(input_tokens) > 20480:
            print(f"Input is too long: {len(prompt)}")
            return ""
        utils.print_red(prompt)
        old_system_msg = None
        if override_system_message is not None:
            old_system_msg = self.system_msg
            self.system_msg = override_system_message

        start_time = time.time()
        response = self._query_impl(prompt, model)
        end_time = time.time()
        last_costed_time = end_time - start_time
        self.costed_time.append(last_costed_time)

        output_tokens = self.enc.encode(response)

        self.costed_input_tokens.append(len(input_tokens))
        self.costed_output_tokens.append(len(output_tokens))

        utils.print_green(response)

        if override_system_message is not None and old_system_msg is not None:
            # Restore old message
            self.system_msg = old_system_msg

        return response

    def statistic(self, path: str) -> None:
        if os.path.isdir(path):
            path = os.path.join(path, "llm_stat.json")
        total_costed_input_tokens = sum(self.costed_input_tokens)
        total_costed_output_tokens = sum(self.costed_output_tokens)
        total_costed_time = sum(self.costed_time)

        statistic_result = {
            "total_queries": len(self.costed_input_tokens),
            "total_costed_input_tokens": total_costed_input_tokens,
            "total_costed_output_tokens": total_costed_output_tokens,
            "total_costed_time": total_costed_time,
            "costed_input_tokens": self.costed_input_tokens,
            "costed_output_tokens": self.costed_output_tokens,
            "costed_time": self.costed_time,
        }
        utils.try_backup_file(path)
        with open(path, "w") as f:
            json.dump(statistic_result, f, indent=4)
