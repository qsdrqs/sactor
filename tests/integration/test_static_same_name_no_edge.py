import json
from pathlib import Path

from sactor import Sactor


class StubSactor(Sactor):
    instances: list["StubSactor"] = []

    def __init__(self, *args, input_file, result_dir=None, **kwargs):
        # no heavy init
        self.input_file = input_file
        self.result_dir = result_dir
        StubSactor.instances.append(self)

    def run(self):
        # no-op run
        pass


def test_static_same_name_no_edge(tmp_path):
    src = tmp_path / "src"
    build = tmp_path / "build"
    src.mkdir()
    build.mkdir()

    a_c = src / "a.c"
    b_c = src / "b.c"
    a_c.write_text("static int foo(){return 1;} int a(){return foo();}\n", encoding="utf-8")
    b_c.write_text("static int foo(){return 2;} int b(){return foo();}\n", encoding="utf-8")

    cc = build / "compile_commands.json"
    entries = [
        {
            "directory": str(src),
            "file": str(a_c),
            "command": f"clang -std=c99 -c {a_c}",
        },
        {
            "directory": str(src),
            "file": str(b_c),
            "command": f"clang -std=c99 -c {b_c}",
        },
    ]
    cc.write_text(json.dumps(entries), encoding="utf-8")

    test_cmd = tmp_path / "test_cmd.json"
    test_cmd.write_text(json.dumps([{"command": "echo ok"}]), encoding="utf-8")

    StubSactor.instances = []
    StubSactor.translate(
        target_type="bin",
        test_cmd_path=str(test_cmd),
        compile_commands_file=str(cc),
        result_dir=str(tmp_path / "out"),
        configure_logging=False,
    )

    inputs = {p for p in (inst.input_file for inst in StubSactor.instances)}
    assert str(a_c.resolve()) in inputs
    assert str(b_c.resolve()) in inputs

