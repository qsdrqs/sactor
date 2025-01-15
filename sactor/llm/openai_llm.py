from typing import override

from openai import OpenAI

from .llm import LLM


class OpenAILLM(LLM):
    '''
    OpenAI LLM

    '''
    def __init__(self, config, encoding=None, system_msg=None):
        super().__init__(
            config,
            encoding=encoding,
            system_msg=system_msg
        )
        api_key = config['OpenAI']['api_key']

        # Optional
        organization = config['OpenAI'].get('organization')
        project_id = config['OpenAI'].get('project_id')

        self.client = OpenAI(
            api_key=api_key,
            organization=organization,
            project=project_id,
        )

    @override
    def _query_impl(self, prompt, model) -> str:
        if model is None:
            model = self.config['OpenAI']['model']

        messages = []
        if self.system_msg is not None:
            messages.append({"role": "system", "content": self.system_msg})
        messages.append({"role": "user", "content": f"{prompt}"})

        temperature = self.config['OpenAI'].get('temperature') # default is 1 if not set

        resp = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )

        if resp.choices[0].message.content is None:
            raise Exception(f"Failed to generate response: {resp}")
        return resp.choices[0].message.content
