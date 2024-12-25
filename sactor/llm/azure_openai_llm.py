import os
from typing import override

from openai import AzureOpenAI

from . import LLM


class AzureOpenAILLM(LLM):
    '''
    Azure OpenAI LLM

    Requires the following environment variables:
    - AZURE_OPENAI_API_KEY
    - AZURE_OPENAI_ENDPOINT
    - AZURE_OPENAI_API_VERSION
    - AZURE_OPENAI_MODEL

    '''
    def __init__(self, encoding=None, system_msg=None):
        super().__init__(
            encoding,
            system_msg
        )
        try:
            api_key = os.environ["AZURE_OPENAI_API_KEY"]
            endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
            api_version = os.environ["AZURE_OPENAI_API_VERSION"]
        except KeyError:
            raise OSError("AZURE_OPENAI_API_KEY is not set")

        self.gpt_client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint,
        )

    @override
    def _query_impl(self, prompt, model) -> str:
        if model is None:
            try:
                model = os.environ["AZURE_OPENAI_MODEL"]
            except KeyError:
                raise OSError("AZURE_OPENAI_MODEL is not set")

        messages = []
        if self.system_msg is not None:
            messages.append({"role": "system", "content": self.system_msg})
        messages.append({"role": "user", "content": f"{prompt}"})

        resp = self.gpt_client.chat.completions.create(
            model=model,
            messages=messages,
            # temperature=0.2,
        )

        assert resp.choices[0].message.content is not None
        return resp.choices[0].message.content
