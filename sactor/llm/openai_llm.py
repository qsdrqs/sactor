import os
from typing import override

from openai import OpenAI

from . import LLM


class OpenAILLM(LLM):
    '''
    OpenAI LLM

    Requires the following environment variables:
    - OPENAI_API_KEY
    - OPENAI_MODEL
    - OPENAI_ORGANIZATION (optional)
    - OPENAI_PROJECT_ID (optional)

    '''
    def __init__(self, encoding=None, mock_code_file=None, system_msg=None):
        super().__init__(encoding, mock_code_file, system_msg)
        try:
            api_key = os.environ["OPENAI_API_KEY"]
        except KeyError:
            raise OSError("OPENAI_API_KEY is not set")

        # Optional
        try:
            organization = os.environ["OPENAI_ORGANIZATION"]
            project_id = os.environ["OPENAI_PROJECT_ID"]
        except KeyError:
            organization = None
            project_id = None

        self.gpt_client = OpenAI(
            api_key=api_key,
            organization=organization,
            project=project_id,
        )

    @override
    def _query_impl(self, prompt, model) -> str:
        if model is None:
            try:
                model = os.environ["OPENAI_MODEL"]
            except KeyError:
                raise OSError("OPENAI_MODEL is not set")

        messages = []
        if self.system_msg is not None:
            messages.append({"role": "system", "content": self.system_msg})
        messages.append({"role": "user", "content": f"{prompt}"})

        resp = self.gpt_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
        )

        assert resp.choices[0].message.content is not None
        return resp.choices[0].message.content
