from typing import override

from openai import OpenAI
from openai.types.chat import ChatCompletion

from .llm import LLM


class OpenAILLM(LLM):
    '''
    OpenAI LLM

    '''
    def __init__(self, config, encoding=None, system_msg=None, config_key="OpenAI"):
        super().__init__(
            config,
            encoding=encoding,
            system_msg=system_msg
        )
        api_key = config[config_key]['api_key']

        # Optional
        organization = config[config_key].get('organization')
        project_id = config[config_key].get('project_id')
        base_url = config[config_key].get('base_url')

        self.client = OpenAI(
            api_key=api_key,
            organization=organization,
            project=project_id,
            base_url=base_url
        )
        self.config_key = config_key

    def _query_impl_inner(self, prompt, model) -> ChatCompletion:
        if model is None:
            model = self.config[self.config_key]['model']

        messages = []
        if self.system_msg is not None:
            messages.append({"role": "system", "content": self.system_msg})
        messages.append({"role": "user", "content": f"{prompt}"})

        temperature = self.config[self.config_key].get('temperature') # default is 1 if not set

        resp = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )

        return resp


    @override
    def _query_impl(self, prompt, model) -> str:
        resp = self._query_impl_inner(prompt, model)

        if resp.choices[0].message.content is None:
            raise Exception(f"Failed to generate response: {resp}")
        return resp.choices[0].message.content

