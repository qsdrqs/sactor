import os
from unittest.mock import MagicMock, patch

import pytest

from sactor import utils
from sactor.llm import llm_factory

from tests.utils import config

@pytest.fixture
def litellm_llm(config):
    # Configure for litellm with mock model list
    config["general"]["model"] = "gpt-4o"
    config["litellm"] = {
        "router_settings": {
            "routing_strategy": "simple-shuffle",
            "num_retries": 2,
            "timeout": 30
        },
        "model_list": [
            {
                "model_name": "gpt-4o",
                "litellm_params": {
                    "model": "openai/gpt-4o",
                    "api_key": "mocked_value"
                }
            }
        ]
    }
    
    # Create LLM instance
    llm = llm_factory(config)
    
    # Mock the router's completion method
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="mocked_response"))]
    llm.router.completion = MagicMock(return_value=mock_response)

    return llm


@pytest.fixture
def azure_litellm_llm(config):
    # Configure for Azure through litellm
    config["general"]["model"] = "azure-gpt-4o"
    config["litellm"] = {
        "router_settings": {
            "routing_strategy": "simple-shuffle",
            "num_retries": 2,
            "timeout": 30
        },
        "model_list": [
            {
                "model_name": "azure-gpt-4o",
                "litellm_params": {
                    "model": "azure/gpt-4o",
                    "api_key": "mocked_value",
                    "api_base": "mocked_endpoint",
                    "api_version": "2024-12-01-preview"
                }
            }
        ]
    }
    
    # Create LLM instance
    llm = llm_factory(config)
    
    # Mock the router's completion method
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="mocked_response"))]
    llm.router.completion = MagicMock(return_value=mock_response)

    return llm


def test_litellm_openai(litellm_llm):
    assert litellm_llm.query("prompt") == "mocked_response"


def test_litellm_azure(azure_litellm_llm):
    assert azure_litellm_llm.query("prompt") == "mocked_response"


def test_litellm_factory(config):
    config["general"]["model"] = "gpt-4o"
    config["litellm"] = {
        "router_settings": {},
        "model_list": []
    }
    
    llm = llm_factory(config)
    assert llm.default_model == "gpt-4o"
    assert hasattr(llm, 'router')