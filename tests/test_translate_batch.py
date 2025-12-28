import argparse
import json
import os
from pathlib import Path

import pytest

from sactor import Sactor
from sactor import __main__ as cli
from sactor import sactor as sactor_module
from sactor import sactor as sactor_module


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
    summary_path = base_result_dir / "batch_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert {entry["status"] for entry in summary} == {"success"}

    result_dirs = {Path(entry["result_dir"]) for entry in summary}
    assert len(result_dirs) == 3
    for entry in summary:
        assert Path(entry["result_dir"]).exists()
        unit_dir = Path(entry["result_dir"])
        assert (unit_dir / "translated_code_unidiomatic" / "combined.rs").exists()
        assert (unit_dir / "translated_code_idiomatic" / "combined.rs").exists()


def test_translate_batch_creates_two_project_crates(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    src_dir = proj / "src"
    build_dir = proj / "build"
    src_dir.mkdir(parents=True)
    build_dir.mkdir()

    util_c = src_dir / "util.c"
    main_c = src_dir / "main.c"
    util_c.write_text(
        "int add_integers(int lhs, int rhs){return lhs+rhs;}\n",
        encoding="utf-8",
    )
    main_c.write_text(
        "int add_integers(int lhs, int rhs);\nint main(void){return add_integers(1,2);}\n",
        encoding="utf-8",
    )

    compile_commands = [
        {
            "directory": str(build_dir),
            "file": str(util_c),
            "command": f"clang -std=c99 -c {util_c}",
        },
        {
            "directory": str(build_dir),
            "file": str(main_c),
            "command": f"clang -std=c99 -c {main_c}",
        },
    ]
    commands_path = build_dir / "compile_commands.json"
    commands_path.write_text(json.dumps(compile_commands), encoding="utf-8")

    test_cmd_path = proj / "test_cmd.json"
    test_cmd_path.write_text(json.dumps([{"command": "echo ok"}]), encoding="utf-8")

    combiner_calls: list[tuple[str, str]] = []

    class FakeProjectCombiner:
        def __init__(self, *args, output_root, variant, **kwargs):
            self.output_root = output_root
            self.variant = variant

        def combine_and_build(self):
            combiner_calls.append((self.variant, self.output_root))
            crate_dir = Path(self.output_root) / "proj"
            crate_dir.mkdir(parents=True, exist_ok=True)
            (crate_dir / "Cargo.toml").write_text(
                "[package]\nname = \"proj\"\nversion = \"0.1.0\"\nedition = \"2021\"\n\n[workspace]\n",
                encoding="utf-8",
            )
            return True, str(crate_dir), None

    monkeypatch.setattr(sactor_module, "ProjectCombiner", FakeProjectCombiner)

    class MinimalSactor(Sactor):
        def __init__(
            self,
            *args,
            input_file,
            result_dir=None,
            unidiomatic_only=False,
            idiomatic_only=False,
            **kwargs,
        ):
            self.input_file = input_file
            self.result_dir = result_dir
            self.unidiomatic_only = unidiomatic_only
            self.idiomatic_only = idiomatic_only

        def run(self):
            base = Path(self.result_dir)
            if self.unidiomatic_only:
                (base / "translated_code_unidiomatic").mkdir(parents=True, exist_ok=True)
            if self.idiomatic_only:
                (base / "translated_code_idiomatic").mkdir(parents=True, exist_ok=True)

    out_dir = tmp_path / "out"
    res = MinimalSactor.translate(
        target_type="bin",
        test_cmd_path=str(test_cmd_path),
        compile_commands_file=str(commands_path),
        result_dir=str(out_dir),
        configure_logging=False,
    )

    assert res.any_failed is False

    combined_root = Path(res.base_result_dir) / "combined"
    assert (combined_root / "unidiomatic" / "proj").exists()
    assert (combined_root / "idiomatic" / "proj").exists()

    assert {variant for variant, _root in combiner_calls} == {"unidiomatic", "idiomatic"}

    assert list((combined_root / "unidiomatic").glob("*.rs")) == []
    assert list((combined_root / "idiomatic").glob("*.rs")) == []


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


def test_translate_batch_creates_variant_projects_without_flat_rs(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    src_dir = proj / "src"
    build_dir = proj / "build"
    src_dir.mkdir(parents=True)
    build_dir.mkdir()

    util_c = src_dir / "util.c"
    main_c = src_dir / "main.c"
    util_c.write_text("int add_integers(int lhs, int rhs){return lhs+rhs;}\n", encoding="utf-8")
    main_c.write_text("int add_integers(int lhs, int rhs);\nint main(void){return add_integers(1,2);}\n", encoding="utf-8")

    compile_commands = [
        {
            "directory": str(build_dir),
            "file": str(util_c),
            "command": f"clang -std=c99 -c {util_c}",
        },
        {
            "directory": str(build_dir),
            "file": str(main_c),
            "command": f"clang -std=c99 -c {main_c}",
        },
    ]
    commands_path = build_dir / "compile_commands.json"
    commands_path.write_text(json.dumps(compile_commands), encoding="utf-8")

    test_cmd_path = proj / "test_cmd.json"
    test_cmd_path.write_text(json.dumps([{"command": "echo ok"}]), encoding="utf-8")

    class MinimalSactor(Sactor):
        def __init__(
            self,
            *args,
            input_file,
            result_dir=None,
            unidiomatic_only=False,
            idiomatic_only=False,
            **kwargs,
        ):
            self.input_file = input_file
            self.result_dir = result_dir
            self.unidiomatic_only = unidiomatic_only
            self.idiomatic_only = idiomatic_only

        def run(self):
            os.makedirs(self.result_dir, exist_ok=True)
            if not self.idiomatic_only:
                base = Path(self.result_dir) / "translated_code_unidiomatic" / "functions"
                base.mkdir(parents=True, exist_ok=True)
                (base / "add_integers.rs").write_text(
                    "// unidiomatic\npub fn add_integers(lhs: i32, rhs: i32) -> i32 { lhs + rhs }\n",
                    encoding="utf-8",
                )
                (base / "main.rs").write_text(
                    "// unidiomatic\npub fn main() { let _ = add_integers(1, 2); }\n",
                    encoding="utf-8",
                )
            if not self.unidiomatic_only:
                base = Path(self.result_dir) / "translated_code_idiomatic" / "functions"
                base.mkdir(parents=True, exist_ok=True)
                (base / "add_integers.rs").write_text(
                    "// idiomatic\npub fn add_integers(lhs: i32, rhs: i32) -> i32 { lhs + rhs }\n",
                    encoding="utf-8",
                )
                (base / "main.rs").write_text(
                    "// idiomatic\npub fn main() { let _ = add_integers(1, 2); }\n",
                    encoding="utf-8",
                )

    combine_calls: list[tuple[str, str]] = []

    def fake_combine_and_build(self):
        combine_calls.append((self.variant, self.output_root))
        crate_dir = Path(self.output_root) / self._crate_name()
        (crate_dir / "src").mkdir(parents=True, exist_ok=True)
        (crate_dir / "Cargo.toml").write_text("[package]\nname = \"proj\"\nversion = \"0.1.0\"\n", encoding="utf-8")
        (crate_dir / "src" / "main.rs").write_text(f"// combined {self.variant}\n", encoding="utf-8")
        return True, str(crate_dir), str(crate_dir / "target" / "debug" / "proj")

    monkeypatch.setattr(sactor_module.ProjectCombiner, "combine_and_build", fake_combine_and_build)

    out_dir = tmp_path / "out"
    res = MinimalSactor.translate(
        target_type="bin",
        test_cmd_path=str(test_cmd_path),
        compile_commands_file=str(commands_path),
        result_dir=str(out_dir),
        configure_logging=False,
    )

    assert res.any_failed is False
    combined_root = Path(res.base_result_dir) / "combined"
    assert (combined_root / "unidiomatic" / "proj" / "Cargo.toml").exists()
    assert (combined_root / "idiomatic" / "proj" / "Cargo.toml").exists()
    assert list((combined_root / "unidiomatic").glob("*.rs")) == []
    assert list((combined_root / "idiomatic").glob("*.rs")) == []

    variants_seen = [variant for (variant, _root) in combine_calls]
    assert variants_seen == ["unidiomatic", "idiomatic"]
