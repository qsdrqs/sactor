import os

import pytest

from sactor.combiner import CombineResult
from sactor.sactor import Sactor
from sactor.translator.translator_types import TranslateResult


class DummyLLM:
    def __init__(self):
        self.calls = []

    def statistic(self, path):
        self.calls.append(path)

    def reset_statistics(self):
        pass


class DummyCombiner:
    def __init__(self):
        self.calls = []

    def combine(self, path, is_idiomatic):
        self.calls.append((path, is_idiomatic))
        return CombineResult.SUCCESS, None


class DummyTranslator:
    def __init__(self, tmp_path):
        self.failure_info_path = str(tmp_path / "failure.json")
        self.saved = []
        self.summary = []

    def save_failure_info(self, path):
        self.saved.append(path)

    def print_result_summary(self, title):
        self.summary.append(title)


def make_sactor(tmp_path, continue_flag, idiomatic_result):
    sactor = object.__new__(Sactor)
    sactor.idiomatic_only = False
    sactor.unidiomatic_only = False
    sactor.continue_run_when_incomplete = continue_flag
    sactor.result_dir = str(tmp_path)
    sactor.llm_stat = str(tmp_path / "llm_stat.json")
    sactor.llm = DummyLLM()
    sactor.combiner = DummyCombiner()
    sactor.c2rust_translation = None

    unidiomatic_translator = DummyTranslator(tmp_path)
    idiomatic_translator = DummyTranslator(tmp_path)

    def run_unidiomatic():
        return TranslateResult.SUCCESS, unidiomatic_translator

    def run_idiomatic():
        return idiomatic_result, idiomatic_translator

    sactor._run_unidomatic_translation = run_unidiomatic
    sactor._run_idiomatic_translation = run_idiomatic

    return sactor, unidiomatic_translator, idiomatic_translator


def make_base_sactor(tmp_path):
    sactor = object.__new__(Sactor)
    sactor.result_dir = str(tmp_path)
    sactor.llm_stat = str(tmp_path / "llm_stat.json")
    sactor.llm = DummyLLM()
    sactor.combiner = DummyCombiner()
    sactor.c2rust_translation = None
    return sactor


def test_idiomatic_only_skips_unidiomatic(tmp_path):
    sactor = make_base_sactor(tmp_path)
    sactor.idiomatic_only = True
    sactor.unidiomatic_only = False
    sactor.continue_run_when_incomplete = False

    idiomatic_translator = DummyTranslator(tmp_path)
    sactor._run_unidomatic_translation = lambda: (_ for _ in ()).throw(AssertionError("unidiomatic stage should not run"))
    sactor._run_idiomatic_translation = lambda: (TranslateResult.SUCCESS, idiomatic_translator)

    sactor.run()

    assert sactor.combiner.calls == [(os.path.join(sactor.result_dir, "translated_code_idiomatic"), True)]
    assert idiomatic_translator.saved == [idiomatic_translator.failure_info_path]
    assert sactor.llm.calls == [str(tmp_path / "llm_stat_idiomatic.json")]


def test_unidiomatic_only_skips_idiomatic(tmp_path):
    sactor = make_base_sactor(tmp_path)
    sactor.idiomatic_only = False
    sactor.unidiomatic_only = True
    sactor.continue_run_when_incomplete = False

    unidiomatic_translator = DummyTranslator(tmp_path)
    sactor._run_unidomatic_translation = lambda: (TranslateResult.SUCCESS, unidiomatic_translator)
    sactor._run_idiomatic_translation = lambda: (_ for _ in ()).throw(AssertionError("idiomatic stage should not run"))

    sactor.run()

    assert sactor.combiner.calls == [(os.path.join(sactor.result_dir, "translated_code_unidiomatic"), False)]
    assert unidiomatic_translator.saved == [unidiomatic_translator.failure_info_path]
    assert sactor.llm.calls == [str(tmp_path / "llm_stat_unidiomatic.json")]


def test_idiomatic_continue_flag_skips_abort(tmp_path):
    sactor, _, idiomatic_translator = make_sactor(
        tmp_path, True, TranslateResult.NO_UNIDIOMATIC_CODE
    )

    sactor.run()

    assert len(sactor.combiner.calls) == 1
    assert sactor.combiner.calls[0][1] is False
    assert idiomatic_translator.summary == ["Idiomatic"]


def test_llm_stat_split_by_stage(tmp_path):
    sactor, _, _ = make_sactor(
        tmp_path, False, TranslateResult.SUCCESS
    )

    sactor.run()

    assert sactor.llm.calls == [
        str(tmp_path / "llm_stat_unidiomatic.json"),
        str(tmp_path / "llm_stat_idiomatic.json"),
    ]


def test_idiomatic_continue_flag_raises_without_flag(tmp_path):
    sactor, _, idiomatic_translator = make_sactor(
        tmp_path, False, TranslateResult.NO_UNIDIOMATIC_CODE
    )

    with pytest.raises(ValueError):
        sactor.run()

    assert len(sactor.combiner.calls) == 1
    assert sactor.combiner.calls[0][1] is False
    assert idiomatic_translator.summary == ["Idiomatic"]
