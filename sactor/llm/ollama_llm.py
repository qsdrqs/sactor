from typing import override

from ollama import Client

from .llm import LLM


class OllamaLLM(LLM):
    '''
    Ollama Language Model Wrapper

    '''

    def __init__(self, config, encoding=None, system_msg=None):
        super().__init__(
            config,
            encoding=encoding,
            system_msg=system_msg
        )
        host = config['Ollama']['host']
        headers = config['Ollama']['headers']

        self.client = Client(
            host=host,
            headers=headers
        )

    @override
    def _query_impl(self, prompt, model) -> str:
        if model is None:
            model = self.config['Ollama']['model']

        messages = []
        if self.system_msg is not None:
            messages.append({"role": "system", "content": self.system_msg})
        messages.append({"role": "user", "content": f"{prompt}"})

        temperature = self.config['Ollama'].get(
            'temperature')  # default value varies by model

        resp = self.client.chat(
            model=model,
            messages=messages,
            options={
                "temperature": temperature
            }
        )

        if resp['message']['content'] is None:
            raise Exception(f"Failed to generate response: {resp}")
        return resp['message']['content']
