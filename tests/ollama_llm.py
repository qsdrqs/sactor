from functools import partial
from unittest.mock import patch, MagicMock
import ollama

from sactor import utils
from sactor.llm import OllamaLLM

def ollama_llm(mock_query_impl):
    original_query = OllamaLLM._query_impl
    config = utils.try_load_config()
    llm = OllamaLLM(config)
    try:
        ollama.chat(
            model=config['Ollama']['model'],
            messages=[{"role": "user", "content": "hello"}],
        )
    except Exception:
        # default values
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            'message': {'content': 'mocked_response'}
        }
        llm.client = mock_client

    mock_with_original = partial(
        mock_query_impl, original=original_query, llm_instance=llm)
    with patch('sactor.llm.OllamaLLM._query_impl', side_effect=mock_with_original):
        yield llm
