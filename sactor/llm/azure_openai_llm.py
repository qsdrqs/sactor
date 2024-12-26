import os
from typing import override

from openai import AzureOpenAI

from . import LLM


class AzureOpenAILLM(LLM):
    '''
    Azure OpenAI LLM

    '''
    def __init__(self, config, encoding=None, system_msg=None):
        super().__init__(
                config,
            encoding=encoding,
            system_msg=system_msg
        )
        api_key = config['AzureOpenAI']['api_key']
        endpoint = config['AzureOpenAI']['endpoint']
        api_version = config['AzureOpenAI']['api_version']

        self.gpt_client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint,
        )

    @override
    def _query_impl(self, prompt, model) -> str:
        if model is None:
            model = self.config['AzureOpenAI']['model']

        messages = []
        if self.system_msg is not None:
            messages.append({"role": "system", "content": self.system_msg})
        messages.append({"role": "user", "content": f"{prompt}"})

        temperature =  self.config['AzureOpenAI'].get('temperature') # default is 1 if not set

        resp = self.gpt_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )

        assert resp.choices[0].message.content is not None
        return resp.choices[0].message.content
