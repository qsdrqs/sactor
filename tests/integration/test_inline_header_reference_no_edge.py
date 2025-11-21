import json
from pathlib import Path

from sactor import Sactor


class StubSactor(Sactor):
    instances: list["StubSactor"] = []

    def __init__(self, *args, input_file, result_dir=None, **kwargs):
        self.input_file = input_file
        self.result_dir = result_dir
        StubSactor.instances.append(self)

    def run(self):
        pass


def test_inline_header_reference_no_edge(tmp_path):
    inc = tmp_path / "include"
    src = tmp_path / "src"
    build = tmp_path / "build"
    inc.mkdir()
    src.mkdir()
    build.mkdir()

    # inline function in header
    h = inc / "util.h"
    h.write_text("static inline int inc(int x){return x+1;}\n", encoding="utf-8")

    main_c = src / "main.c"
    main_c.write_text('#include "util.h"\nint main(void){return inc(0);}\n', encoding="utf-8")

    cc = build / "compile_commands.json"
    entries = [
        {
            "directory": str(src),
            "file": str(main_c),
            "command": f"clang -std=c99 -I{inc} -c {main_c}",
        }
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

    # Only one TU should be processed; no unresolved errors
    assert len(StubSactor.instances) == 1
    assert StubSactor.instances[0].input_file == str(main_c.resolve())

