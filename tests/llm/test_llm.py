import os
from unittest.mock import MagicMock, patch

import pytest

from sactor.llm import AzureOpenAILLM, OpenAILLM


@pytest.fixture
def azure_llm():
    # patch environment variables
    with patch.dict(os.environ, {
        "AZURE_OPENAI_API_KEY": "mocked_value",
        "AZURE_OPENAI_ENDPOINT": "mocked_value",
        "AZURE_OPENAI_API_VERSION": "mocked_value",
        "AZURE_OPENAI_MODEL": "mocked_value",
    }):
        llm = AzureOpenAILLM()
        mock_gpt_client = MagicMock()
        mock_gpt_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="mocked_response"))]
        )
        llm.gpt_client = mock_gpt_client

        yield llm

@pytest.fixture
def openai_llm():
    with patch.dict(os.environ, {
        "OPENAI_API_KEY": "mocked_value",
        "OPENAI_MODEL": "mocked_value",
    }):
        llm = OpenAILLM()
        mock_gpt_client = MagicMock()
        mock_gpt_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="mocked_response"))]
        )
        llm.gpt_client = mock_gpt_client

        yield llm


def test_azure_llm(azure_llm):
    assert azure_llm.query("prompt") == "mocked_response"


def test_openai_llm(openai_llm):
    assert openai_llm.query("prompt") == "mocked_response"