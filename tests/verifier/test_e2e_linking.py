import os
import subprocess

import pytest

from sactor.verifier import E2EVerifier, VerifyResult
from sactor.utils import load_default_config
from sactor import utils


@pytest.fixture
def e2e_config():
    base = load_default_config()
    # Shallow copy dicts to avoid mutating global defaults
    return {k: (v.copy() if isinstance(v, dict) else v) for k, v in base.items()}


def _ok_compile(self, code, executable):
    return (VerifyResult.SUCCESS, None)


class _Result:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.stdout = b""
        self.stderr = b""


def test_e2e_string_single_variant_links_once_and_runs(tmp_path, monkeypatch, e2e_config):
    link_calls: list[list[str]] = []
    run_calls: list[tuple[str, dict]] = []

    monkeypatch.setattr(E2EVerifier, "try_compile_rust_code", _ok_compile)
    monkeypatch.setattr(utils, "get_compiler", lambda: "cc")
    monkeypatch.setattr(utils, "patched_env", lambda *args, **kwargs: {"LD_LIBRARY_PATH": "foo"})

    def fake_run(cmd, *_, **__):
        # capture link command
        assert isinstance(cmd, list)
        link_calls.append(cmd)
        return _Result(0)

    def fake_run_tests(self, target, env=None, test_number=None, valgrind=False):
        run_calls.append((target, env or {}))
        return (VerifyResult.SUCCESS, None, None)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(E2EVerifier, "_run_tests", fake_run_tests)

    verifier = E2EVerifier(
        test_cmd_path="tests/verifier/test_cmd.json",
        config=e2e_config,
        build_path=str(tmp_path),
        is_executable=False,
        executable_object="tests/verifier/mock_results/test1.o tests/verifier/mock_results/test2.o",
    )

    result = verifier.e2e_verify("fn main() {}")
    assert result == (VerifyResult.SUCCESS, None)

    # one link, one run
    assert len(link_calls) == 1
    assert len(run_calls) == 1

    link_cmd = link_calls[0]
    # Ensure objects come before the Rust lib flag
    pos1 = link_cmd.index("tests/verifier/mock_results/test1.o")
    pos2 = link_cmd.index("tests/verifier/mock_results/test2.o")
    lpos = link_cmd.index("-lbuild_attempt")
    assert pos1 < lpos and pos2 < lpos

    # Output is program_combiner/combined
    assert os.path.basename(run_calls[0][0]) == "combined"
    # LD_LIBRARY_PATH is provided
    assert "LD_LIBRARY_PATH" in run_calls[0][1]


def test_e2e_list_multi_variant_reuses_same_output(tmp_path, monkeypatch, e2e_config):
    link_calls: list[list[str]] = []
    run_targets: list[str] = []

    monkeypatch.setattr(E2EVerifier, "try_compile_rust_code", _ok_compile)
    monkeypatch.setattr(utils, "get_compiler", lambda: "cc")
    monkeypatch.setattr(utils, "patched_env", lambda *args, **kwargs: {})

    def fake_run(cmd, *_, **__):
        link_calls.append(cmd)
        return _Result(0)

    def fake_run_tests(self, target, env=None, test_number=None, valgrind=False):
        run_targets.append(os.path.basename(target))
        return (VerifyResult.SUCCESS, None, None)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(E2EVerifier, "_run_tests", fake_run_tests)

    verifier = E2EVerifier(
        test_cmd_path="tests/verifier/test_cmd.json",
        config=e2e_config,
        build_path=str(tmp_path),
        is_executable=False,
        executable_object=[
            "tests/verifier/mock_results/test1.o",
            "tests/verifier/mock_results/test2.o",
        ],
    )

    result = verifier.e2e_verify("fn main() {}")
    assert result == (VerifyResult.SUCCESS, None)
    # two variants → two links and two runs
    assert len(link_calls) == 2
    assert len(run_targets) == 2
    assert run_targets[0] == "combined" and run_targets[1] == "combined"


def test_e2e_extra_compile_args_are_split(tmp_path, monkeypatch, e2e_config):
    link_calls: list[list[str]] = []

    monkeypatch.setattr(E2EVerifier, "try_compile_rust_code", _ok_compile)
    monkeypatch.setattr(utils, "get_compiler", lambda: "cc")
    monkeypatch.setattr(utils, "patched_env", lambda *args, **kwargs: {})

    def fake_run(cmd, *_, **__):
        link_calls.append(cmd)
        return _Result(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(E2EVerifier, "_run_tests", lambda *a, **k: (VerifyResult.SUCCESS, None, None))

    verifier = E2EVerifier(
        test_cmd_path="tests/verifier/test_cmd.json",
        config=e2e_config,
        build_path=str(tmp_path),
        is_executable=False,
        executable_object="tests/verifier/mock_results/test1.o",
        extra_compile_command="-pthread -s",
    )

    result = verifier.e2e_verify("fn main() {}")
    assert result == (VerifyResult.SUCCESS, None)
    assert len(link_calls) == 1
    link_cmd = link_calls[0]
    # Args should be split into separate tokens
    assert "-pthread" in link_cmd and "-s" in link_cmd


def test_e2e_library_without_objects_raises(tmp_path, monkeypatch, e2e_config):
    monkeypatch.setattr(E2EVerifier, "try_compile_rust_code", _ok_compile)

    verifier = E2EVerifier(
        test_cmd_path="tests/verifier/test_cmd.json",
        config=e2e_config,
        build_path=str(tmp_path),
        is_executable=False,
        executable_object=None,
    )

    with pytest.raises(ValueError):
        verifier.e2e_verify("fn main() {}")


def test_e2e_executable_mode_runs_rust_binary(tmp_path, monkeypatch, e2e_config):
    calls: list[str] = []

    monkeypatch.setattr(E2EVerifier, "try_compile_rust_code", _ok_compile)
    monkeypatch.setattr(E2EVerifier, "_run_tests", lambda self, target: (calls.append(target), (VerifyResult.SUCCESS, None, None))[1])

    verifier = E2EVerifier(
        test_cmd_path="tests/verifier/test_cmd.json",
        config=e2e_config,
        build_path=str(tmp_path),
        is_executable=True,
    )

    result = verifier.e2e_verify("fn main() {}")
    assert result == (VerifyResult.SUCCESS, None)
    assert len(calls) == 1
    expected = os.path.join(str(tmp_path), "build_attempt", "target", "debug", "build_attempt")
    assert calls[0] == expected

