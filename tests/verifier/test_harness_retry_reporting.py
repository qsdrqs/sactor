import json
from pathlib import Path

from sactor.verifier.idiomatic_verifier import IdiomaticVerifier
from sactor.verifier.verifier_types import VerifyResult


class _DummyLLM:
    def query(self, prompt: str) -> str:  # pragma: no cover - not used here
        return ""


def _make_verifier(tmp_path: Path, max_attempts: int = 1) -> IdiomaticVerifier:
    config = {
        "general": {
            "max_verifier_harness_attempts": max_attempts,
            "timeout_seconds": 1,
        }
    }
    test_cmd_path = tmp_path / "test_cmd.json"
    test_cmd_path.write_text(json.dumps([]))
    build_path = tmp_path / "build"
    result_path = tmp_path / "result"
    return IdiomaticVerifier(
        str(test_cmd_path),
        llm=_DummyLLM(),
        config=config,
        build_path=str(build_path),
        result_path=str(result_path),
    )


def test_function_harness_max_attempts_reports_last_error(tmp_path):
    verifier = _make_verifier(tmp_path, max_attempts=1)
    status, message = verifier._function_generate_test_harness(
        "update",
        idiomatic_impl="",
        original_signature="pub fn update();",
        idiomatic_signature="pub fn update();",
        struct_signature_dependency_names=[],
        verify_result=(VerifyResult.COMPILE_ERROR, "compile failure log"),
        attempts=verifier.max_attempts,
    )
    assert status == VerifyResult.TEST_HARNESS_MAX_ATTEMPTS_EXCEEDED
    assert message is not None and "compile failure log" in message


def test_struct_harness_max_attempts_reports_last_error(tmp_path):
    verifier = _make_verifier(tmp_path, max_attempts=1)
    status, message = verifier._struct_generate_test_harness(
        "Student",
        unidiomatic_struct_code="",
        idiomatic_struct_code="",
        struct_dependencies=[],
        idiomatic_struct_name="Student",
        verify_result=(VerifyResult.COMPILE_ERROR, "struct compile log"),
        attempts=verifier.max_attempts,
    )
    assert status == VerifyResult.TEST_HARNESS_MAX_ATTEMPTS_EXCEEDED
    assert message is not None and "struct compile log" in message
