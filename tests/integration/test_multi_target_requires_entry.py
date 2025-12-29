import json
import os
from pathlib import Path
import textwrap
import pytest

from sactor.c_parser.project_index import build_link_closure


def _write(tmp: Path, rel: str, content: str) -> str:
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')
    return str(p)


def test_multiple_main_requires_entry(tmp_path: Path):
    # Create two simple C files both defining main
    src1 = _write(tmp_path, 'a.c', 'int main(){return 0;}')
    src2 = _write(tmp_path, 'b.c', 'int main(){return 0;}')

    # Minimal compile_commands.json entries
    cc = [
        {
            "directory": str(tmp_path),
            "command": f"gcc -std=c99 -o a.o -c {src1}",
            "file": src1,
            "output": "a.o",
        },
        {
            "directory": str(tmp_path),
            "command": f"gcc -std=c99 -o b.o -c {src2}",
            "file": src2,
            "output": "b.o",
        },
    ]
    cc_path = tmp_path / 'compile_commands.json'
    cc_path.write_text(json.dumps(cc, indent=2), encoding='utf-8')

    with pytest.raises(ValueError) as excinfo:
        build_link_closure(None, str(cc_path))

    msg = str(excinfo.value)
    assert 'Multiple main functions' in msg
    assert '--entry-tu-file' in msg
