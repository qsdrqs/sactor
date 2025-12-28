from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sactor.translator import Translator
from sactor.translator.translator_types import TranslateResult, TranslationOutcome
from sactor.c_parser.refs import EnumRef, FunctionDependencyRef, GlobalVarRef, StructRef


class DummyTranslator(Translator):
    """Minimal translator implementation for dependency tests."""

    def _translate_enum_impl(self, enum, verify_result=(None, None), error_translation=None, attempts=0):
        return TranslateResult.SUCCESS

    def _translate_global_vars_impl(self, global_var, verify_result=(None, None), error_translation=None, attempts=0):
        return TranslateResult.SUCCESS

    def _translate_struct_impl(self, struct_union, verify_result=(None, None), error_translation=None, attempts=0):
        return TranslateResult.SUCCESS

    def _translate_function_impl(self, function, verify_result=(None, None), error_translation=None, attempts=0):
        return TranslateResult.SUCCESS


@pytest.fixture
def translator(tmp_path):
    config = {"general": {"max_translation_attempts": 2}}
    dummy_llm = Mock()
    dummy_parser = Mock()
    return DummyTranslator(dummy_llm, dummy_parser, config, result_path=str(tmp_path))


def test_dependency_block_records_failure(translator):
    dep = SimpleNamespace(name="DepA")
    translator._set_translation_status("unknown", dep.name, TranslationOutcome.FAILURE)

    ready, blockers = translator.check_dependencies(object(), lambda _: [dep])

    assert not ready
    assert blockers == [{"type": "unknown", "name": "DepA", "status": "failure"}]

    translator.mark_dependency_block("function", "foo", blockers)

    assert translator.failure_info["foo"]["status"] == "blocked_by_failed_dependency"
    assert translator.translation_status["function"]["foo"] == TranslationOutcome.BLOCKED_FAILED
    assert translator.failure_info["foo"]["blockers"] == blockers


def test_dependency_block_waits_for_missing(translator):
    dep = SimpleNamespace(name="DepB")
    with pytest.raises(RuntimeError):
        translator.check_dependencies(object(), lambda _: [dep])


def test_mark_translation_success_updates_status(translator):
    translator.init_failure_info("struct", "Item")
    translator.mark_translation_success("struct", "Item")

    assert translator.failure_info["Item"]["status"] == "success"
    assert translator.translation_status["struct"]["Item"] == TranslationOutcome.SUCCESS


def test_dependency_detects_existing_artifact(translator, tmp_path):
    artifact_dir = tmp_path / "existing"
    artifact_dir.mkdir()
    (artifact_dir / "DepC.rs").write_text("// artifact\n", encoding="utf-8")

    # Point the translator's function output dir at the pre-existing artifact.
    translator.translated_function_path = str(artifact_dir)

    dep = FunctionDependencyRef(name="DepC", usr="usr_depc")

    ready, blockers = translator.check_dependencies(object(), lambda _: [dep])

    assert ready
    assert blockers == []


def test_dependency_cache_updates_after_success(translator):
    dep = SimpleNamespace(name="DepD")

    with pytest.raises(RuntimeError):
        translator.check_dependencies(object(), lambda _: [dep])

    translator.mark_translation_success("unknown", dep.name)

    ready_again, blockers_again = translator.check_dependencies(object(), lambda _: [dep])
    assert ready_again
    assert blockers_again == []


def test_dependency_fast_path_uses_base_name_and_project_maps(translator, tmp_path):
    owner_dir = tmp_path / "owner"
    base_name = "translated_code_idiomatic"

    # Create fake project artifacts under the owner dir.
    (owner_dir / base_name / "functions").mkdir(parents=True)
    (owner_dir / base_name / "structs").mkdir(parents=True)
    (owner_dir / base_name / "enums").mkdir(parents=True)
    (owner_dir / base_name / "global_vars").mkdir(parents=True)

    (owner_dir / base_name / "functions" / "dep_fn.rs").write_text("// fn\n", encoding="utf-8")
    (owner_dir / base_name / "structs" / "DepStruct.rs").write_text("// struct\n", encoding="utf-8")
    (owner_dir / base_name / "enums" / "DepEnum.rs").write_text("// enum\n", encoding="utf-8")
    (owner_dir / base_name / "global_vars" / "dep_global.rs").write_text("// gv\n", encoding="utf-8")

    # Configure translator to emulate idiomatic multi-TU mode.
    translator.base_name = base_name
    translator.project_usr_to_result_dir = {"usr_fn": str(owner_dir)}
    translator.project_struct_usr_to_result_dir = {"usr_struct": str(owner_dir)}
    translator.project_enum_usr_to_result_dir = {"usr_enum": str(owner_dir)}
    translator.project_global_usr_to_result_dir = {"usr_gv": str(owner_dir)}

    deps = [
        FunctionDependencyRef(name="dep_fn", usr="usr_fn"),
        StructRef(name="DepStruct", usr="usr_struct"),
        EnumRef(name="DepEnum", usr="usr_enum"),
        GlobalVarRef(name="dep_global", usr="usr_gv"),
    ]

    ready, blockers = translator.check_dependencies(object(), lambda _: deps)
    assert ready
    assert blockers == []
