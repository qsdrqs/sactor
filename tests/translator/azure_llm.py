import os
from functools import partial
from unittest.mock import patch, MagicMock

from sactor.llm import AzureOpenAILLM

def azure_llm(mock_query_impl):
    original_query = AzureOpenAILLM._query_impl
    if not os.environ.get("AZURE_OPENAI_API_KEY"):
        with patch.dict(os.environ, {
            "AZURE_OPENAI_API_KEY": "mocked_value",
            "AZURE_OPENAI_ENDPOINT": "mocked_value",
            "AZURE_OPENAI_API_VERSION": "mocked_value",
            "AZURE_OPENAI_MODEL": "mocked_value",
        }):
            llm = AzureOpenAILLM()
            mock_gpt_client = MagicMock()
            mock_gpt_client.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(
                    content="mocked_response"))]
            )
            llm.gpt_client = mock_gpt_client

            mock_with_original = partial(
                mock_query_impl, original=original_query, llm_instance=llm)
            with patch('sactor.llm.AzureOpenAILLM._query_impl', side_effect=mock_with_original):
                yield llm

            yield llm
    else:
        llm = AzureOpenAILLM()

        mock_with_original = partial(
            mock_query_impl, original=original_query, llm_instance=llm)
        with patch('sactor.llm.AzureOpenAILLM._query_impl', side_effect=mock_with_original):
            yield llm

