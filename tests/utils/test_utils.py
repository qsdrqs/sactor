from sactor import utils


def test_merge_configs():
    config = {
        "a": {
            "b": 1,
        },
    }
    default_config = {
        "a": {
            "b": 2,
            "c": 3,
        },
        "d": 4,
    }
    assert utils._merge_configs(config, default_config) == {
        "a": {
            "b": 1,
            "c": 3,
        },
        "d": 4,
    }


def test_load_config():
    mock_config_path = "tests/utils/sactor.mock.toml"
    config = utils.try_load_config(mock_config_path)
    assert config['general']['llm'] == "AzureOpenAI"
    assert config['general']['max_translation_attempts'] == 3
    assert config['AzureOpenAI']['api_key'] == "your-api-key"
    assert config['OpenAI']['api_key'] == 'mock-api-key'
