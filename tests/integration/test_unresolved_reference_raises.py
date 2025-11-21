import json
import pytest
from pathlib import Path

from sactor import Sactor


def test_unresolved_reference_raises(tmp_path):
    src = tmp_path / "src"
    build = tmp_path / "build"
    src.mkdir()
    build.mkdir()

    main_c = src / "main.c"
    util_c = src / "util.c"
    main_c.write_text("int util(void); int main(void){return util();}\n", encoding="utf-8")
    util_c.write_text("int util(void){return 0;}\n", encoding="utf-8")

    cc = build / "compile_commands.json"
    # Intentionally omit util.c so that util() has no owner in the DB
    entries = [
        {
            "directory": str(src),
            "file": str(main_c),
            "command": f"clang -std=c99 -c {main_c}",
        },
    ]
    cc.write_text(json.dumps(entries), encoding="utf-8")

    test_cmd = tmp_path / "test_cmd.json"
    test_cmd.write_text(json.dumps([{"command": "echo ok"}]), encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        Sactor.translate(
            target_type="bin",
            test_cmd_path=str(test_cmd),
            compile_commands_file=str(cc),
            result_dir=str(tmp_path / "out"),
            configure_logging=False,
        )
    assert "Unresolved reference" in str(excinfo.value)

