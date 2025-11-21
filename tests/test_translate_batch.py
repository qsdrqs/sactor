import argparse
import json
import os
from pathlib import Path

import pytest

from sactor import Sactor
from sactor import __main__ as cli


class StubSactor(Sactor):
    instances: list["StubSactor"] = []

    def __init__(self, *args, input_file, result_dir=None, **kwargs):
        self.input_file = input_file
        self.result_dir = result_dir
        StubSactor.instances.append(self)

    def run(self):
        os.makedirs(self.result_dir, exist_ok=True)
        for sub in ("translated_code_unidiomatic", "translated_code_idiomatic"):
            d = os.path.join(self.result_dir, sub)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "combined.rs"), "w", encoding="utf-8") as f:
                f.write(f"// {sub} {self.input_file}\n")


@pytest.fixture(autouse=True)
def reset_stub_runner():
    StubSactor.instances = []
    yield
    StubSactor.instances = []


def test_translate_batch_api_orders_units(tmp_path):
    compile_dir = tmp_path / "project"
    compile_dir.mkdir()
    util_c = compile_dir / "util.c"
    helper_c = compile_dir / "helper.c"
    main_c = compile_dir / "main.c"
    util_c.write_text("int util(void){return 42;}\n", encoding="utf-8")
    helper_c.write_text(
        "int util(void);\nint helper(void){return util();}\n", encoding="utf-8"
    )
    main_c.write_text(
        "int helper(void);\nint main(void){return helper();}\n", encoding="utf-8"
    )

    compile_commands = [
        {
            "directory": str(compile_dir),
            "file": str(main_c),
            "command": f"clang -std=c99 -c {main_c}",
        },
        {
            "directory": str(compile_dir),
            "file": str(helper_c),
            "command": f"clang -std=c99 -c {helper_c}",
        },
        {
            "directory": str(compile_dir),
            "file": str(util_c),
            "command": f"clang -std=c99 -c {util_c}",
        },
    ]
    commands_path = compile_dir / "compile_commands.json"
    commands_path.write_text(json.dumps(compile_commands), encoding="utf-8")

    test_cmd_path = tmp_path / "test_cmd.json"
    test_cmd_path.write_text(json.dumps([{"command": "echo ok"}]), encoding="utf-8")

    result = StubSactor.translate(
        target_type="bin",
        test_cmd_path=str(test_cmd_path),
        compile_commands_file=str(commands_path),
        result_dir=str(tmp_path / "out"),
        configure_logging=False,
    )

    inputs = [instance.input_file for instance in StubSactor.instances]
    assert inputs == [
        str(util_c.resolve()),
        str(helper_c.resolve()),
        str(main_c.resolve()),
    ]

    base_result_dir = Path(result.base_result_dir)
    combined_root = base_result_dir / "combined"
    uni_files = sorted((combined_root / "unidiomatic").glob("*.rs"))
    idi_files = sorted((combined_root / "idiomatic").glob("*.rs"))
    assert len(uni_files) == 3
    assert len(idi_files) == 3

    summary_path = base_result_dir / "batch_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert {entry["status"] for entry in summary} == {"success"}

    result_dirs = {Path(entry["result_dir"]) for entry in summary}
    assert len(result_dirs) == 3
    for entry in summary:
        assert Path(entry["result_dir"]).exists()


def test_translate_cli_delegates_to_sactor(monkeypatch, tmp_path):
    called: dict[str, dict[str, object]] = {}

    class DummyResult:
        any_failed = False

    def fake_translate(cls, **kwargs):
        called["kwargs"] = kwargs
        return DummyResult()

    monkeypatch.setattr(cli.Sactor, "translate", classmethod(fake_translate))

    parser = argparse.ArgumentParser()
    cli.parse_translate(parser)
    args = parser.parse_args(
        [
            "--test-command-path",
            str(tmp_path / "test_cmd.json"),
            "--type",
            "bin",
            "--compile-commands-file",
            str(tmp_path / "compile_commands.json"),
            "--result-dir",
            str(tmp_path / "out"),
        ]
    )

    cli.translate(parser, args)

    assert called["kwargs"]["target_type"] == "bin"
    assert called["kwargs"]["compile_commands_file"] == str(tmp_path / "compile_commands.json")
