from .azure_openai_llm import AzureOpenAILLM
from .llm import LLM
from .ollama_llm import OllamaLLM
from .openai_llm import OpenAILLM

__all__ = [
    'LLM',
    'AzureOpenAILLM',
    'OpenAILLM',
    'OllamaLLM',
]


def llm_factory(config: dict, encoding=None, system_message=None) -> LLM:
    match config['general'].get("llm"):
        case "AzureOpenAI":
            return AzureOpenAILLM(config, encoding=encoding, system_msg=system_message)
        case "OpenAI":
            return OpenAILLM(config, encoding=encoding, system_msg=system_message)
        case "Ollama":
            return OllamaLLM(config, encoding=encoding, system_msg=system_message)
        case _:
            raise ValueError(
                f"Invalid LLM type: {config['general'].get('llm')}")
