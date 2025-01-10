import os
from unittest.mock import MagicMock, patch

import pytest

from sactor import utils
from sactor.llm import AzureOpenAILLM, OpenAILLM


@pytest.fixture
def azure_llm():
    # patch environment variables
    config = utils.load_default_config()
    config["AzureOpenAI"] = {
        "api_key": "mocked_value",
        "endpoint": "mocked_value",
        "api_version": "mocked_value",
        "model": "mocked_value",
    }
    llm = AzureOpenAILLM(config)
    mock_gpt_client = MagicMock()
    mock_gpt_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="mocked_response"))]
    )
    llm.client = mock_gpt_client

    return llm


@pytest.fixture
def openai_llm():
    config = utils.load_default_config()
    config["OpenAI"] = {
        "api_key": "mocked_value",
        "model": "mocked_value",
    }
    llm = OpenAILLM(config)
    mock_gpt_client = MagicMock()
    mock_gpt_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="mocked_response"))]
    )
    llm.client = mock_gpt_client

    return llm


def test_azure_llm(azure_llm):
    assert azure_llm.query("prompt") == "mocked_response"


def test_openai_llm(openai_llm):
    assert openai_llm.query("prompt") == "mocked_response"