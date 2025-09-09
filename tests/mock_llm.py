from functools import partial
from contextlib import contextmanager
from unittest.mock import patch

from sactor import utils
from sactor.llm import LLM, llm_factory


def llm_with_mock(mock_query_impl):
    """
    Generator-based helper to yield a unified LLM instance with
    its _query_impl patched to use the provided mock_query_impl.

    Usage in tests:
        @pytest.fixture
        def llm():
            yield from llm_with_mock(mock_query_impl)
    """
    cfg = utils.load_default_config()
    llm = llm_factory(cfg)
    original_query = LLM._query_impl
    mock_with_original = partial(
        mock_query_impl, original=original_query, llm_instance=llm
    )
    with patch('sactor.llm.llm.LLM._query_impl', side_effect=mock_with_original):
        yield llm

