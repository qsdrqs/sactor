from typing import override

from google import genai
from google.genai.types import GenerateContentConfigDict

from .llm import LLM


class GoogleLLM(LLM):
    '''
    Google LLM

    '''
    def __init__(self, config, encoding=None, system_msg=None):
        super().__init__(
            config,
            encoding=encoding,
            system_msg=system_msg
        )
        api_key = config['Google']['api_key']
        self.client = genai.Client(
            api_key=api_key
        )

    @override
    def _query_impl(self, prompt, model) -> str:
        if model is None:
            model = self.config['Google']['model']

        temperature = self.config['Google'].get('temperature') # default value varies by model
        max_tokens = self.config['Google'].get('max_tokens')
        config: GenerateContentConfigDict = {}
        if self.system_msg is not None:
            config['system_instruction'] = self.system_msg
        if temperature is not None:
            config['temperature'] = temperature
        if max_tokens is not None:
            config['max_output_tokens'] = max_tokens

        resp = self.client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )

        if resp.text is None:
            raise Exception(f"Failed to generate response: {resp}")
        return resp.text
