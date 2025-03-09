from .azure_openai_llm import AzureOpenAILLM
from .llm import LLM
from .ollama_llm import OllamaLLM
from .openai_llm import OpenAILLM
from .anthropic_llm import AnthropicLLM
from .google_llm import GoogleLLM
from .deepseek_llm import DeepSeekLLM

__all__ = [
    'LLM',
    'AzureOpenAILLM',
    'OpenAILLM',
    'OllamaLLM',
    'AnthropicLLM',
    'GoogleLLM',
    'DeepSeekLLM'
]


def llm_factory(config: dict, encoding=None, system_message=None) -> LLM:
    match config['general'].get("llm"):
        case "AzureOpenAI":
            return AzureOpenAILLM(config, encoding=encoding, system_msg=system_message)
        case "OpenAI":
            return OpenAILLM(config, encoding=encoding, system_msg=system_message)
        case "Anthropic":
            return AnthropicLLM(config, encoding=encoding, system_msg=system_message)
        case "Google":
            return GoogleLLM(config, encoding=encoding, system_msg=system_message)
        case "Ollama":
            return OllamaLLM(config, encoding=encoding, system_msg=system_message)
        case "DeepSeek":
            return DeepSeekLLM(config, encoding=encoding, system_msg=system_message)
        case _:
            raise ValueError(
                f"Invalid LLM type: {config['general'].get('llm')}")
