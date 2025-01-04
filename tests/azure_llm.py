from functools import partial
from unittest.mock import patch, MagicMock

from sactor import utils
from sactor.llm import AzureOpenAILLM

def azure_llm(mock_query_impl):
    original_query = AzureOpenAILLM._query_impl
    config = utils.try_load_config()
    if config['AzureOpenAI']['api_key'] == 'your-api-key':
        # default values
        config["AzureOpenAI"] = {
            "api_key": "mocked_value",
            "endpoint": "mocked_value",
            "api_version": "mocked_value",
            "model": "mocked_value",
        }
        llm = AzureOpenAILLM(config)
        mock_gpt_client = MagicMock()
        mock_gpt_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(
                content="mocked_response"))]
        )
        llm.client = mock_gpt_client

        mock_with_original = partial(
            mock_query_impl, original=original_query, llm_instance=llm)
        with patch('sactor.llm.AzureOpenAILLM._query_impl', side_effect=mock_with_original):
            yield llm

    else:
        llm = AzureOpenAILLM(config)

        mock_with_original = partial(
            mock_query_impl, original=original_query, llm_instance=llm)
        with patch('sactor.llm.AzureOpenAILLM._query_impl', side_effect=mock_with_original):
            yield llm


def general_mock_query_impl(prompt, model, original=None, llm_instance=None):
    if llm_instance is not None and original is not None:
        return original(llm_instance, prompt, model)
