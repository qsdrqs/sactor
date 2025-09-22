from .llm import LLM

__all__ = [
    'LLM',
]


def llm_factory(config: dict, encoding=None, system_message=None) -> LLM:
    # litellm handles all providers through unified interface
    return LLM(config, encoding=encoding, system_msg=system_message)
