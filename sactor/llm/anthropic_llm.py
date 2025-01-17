from typing import override

from anthropic import NOT_GIVEN, Anthropic
from anthropic.types import TextBlock

from .llm import LLM


class AnthropicLLM(LLM):
    '''
    Anthropic LLM

    '''

    def __init__(self, config, encoding=None, system_msg=None):
        super().__init__(
            config,
            encoding=encoding,
            system_msg=system_msg
        )
        api_key = config['Anthropic']['api_key']

        self.client = Anthropic(
            api_key=api_key,
        )

    @override
    def _query_impl(self, prompt, model) -> str:
        if model is None:
            model = self.config['Anthropic']['model']

        messages = []
        messages.append({"role": "user", "content": f"{prompt}"})

        temperature = self.config['Anthropic'].get('temperature')  # default is 1 if not set
        if temperature is None:
            temperature = NOT_GIVEN
        max_tokens = self.config['Anthropic'].get('max_tokens')

        resp = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=self.system_msg,
            temperature=temperature,
            messages=messages,
        )
        if type(resp.content[0]) != TextBlock:
            raise Exception(f"Failed to generate response: {resp}")
        if resp.content[0].text is None:
            raise Exception(f"Failed to generate response: {resp}")
        return resp.content[0].text
