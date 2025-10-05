import os
import subprocess

import pytest

from sactor.verifier import E2EVerifier, VerifyResult
from sactor import utils
from sactor.utils import load_default_config


@pytest.fixture
def e2e_config():
    base = load_default_config()
    return {k: (v.copy() if isinstance(v, dict) else v) for k, v in base.items()}


def test_e2e_verifier_runs_each_executable(tmp_path, monkeypatch, e2e_config):
    calls: list[str] = []

    monkeypatch.setattr(
        E2EVerifier,
        "try_compile_rust_code",
        lambda self, code, executable: (VerifyResult.SUCCESS, None),
    )

    def fake_run_tests(self, target, env=None, test_number=None, valgrind=False):
        calls.append(target)
        return (VerifyResult.SUCCESS, None, None)

    monkeypatch.setattr(E2EVerifier, "_run_tests", fake_run_tests)

    class _Result:
        def __init__(self):
            self.returncode = 0
            self.stdout = b""
            self.stderr = b""

    monkeypatch.setattr(utils, "get_compiler", lambda: "cc")
    monkeypatch.setattr(utils, "patched_env", lambda *args, **kwargs: {})
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _Result())

    verifier = E2EVerifier(
        test_cmd_path="tests/verifier/test_cmd.json",
        config=e2e_config,
        build_path=str(tmp_path),
        is_executable=False,
        executable_object=["tests/verifier/mock_results/test1.o", "tests/verifier/mock_results/test2.o"],
    )

    result = verifier.e2e_verify("fn main() {}")

    assert result == (VerifyResult.SUCCESS, None)
    assert len(calls) == 2
    assert os.path.basename(calls[0]).startswith("combined")
    assert os.path.basename(calls[1]).startswith("combined")
    # New design: reuse the same output name for each variant
    assert os.path.basename(calls[0]) == os.path.basename(calls[1])
