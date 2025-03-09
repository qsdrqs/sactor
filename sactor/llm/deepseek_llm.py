from typing import override

from .openai_llm import OpenAILLM


class DeepSeekLLM(OpenAILLM):
    '''
    DeepSeek LLM

    '''

    def __init__(self, config, encoding=None, system_msg=None):
        super().__init__(
            config,
            encoding=encoding,
            system_msg=system_msg,
            config_key="DeepSeek"
        )


    @override
    def _query_impl(self, prompt, model) -> str:
        resp = self._query_impl_inner(prompt, model)

        ret = ''

        if hasattr(resp.choices[0].message, 'reasoning_content'):
            reasoning_content = resp.choices[0].message.reasoning_content
            if reasoning_content is not None:
                ret += f"<think>\n{reasoning_content}\n</think>\n"

        if resp.choices[0].message.content is None:
            raise Exception(f"Failed to generate response: {resp}")
        ret += resp.choices[0].message.content
        return ret
