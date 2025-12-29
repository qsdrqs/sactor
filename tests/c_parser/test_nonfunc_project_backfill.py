import json
import os
from pathlib import Path

from sactor.c_parser import CParser
from sactor.c_parser.project_index import build_nonfunc_def_maps


def _write_compile_commands(path: Path, entries: list[dict]) -> Path:
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def test_nonfunc_refs_project_backfill(tmp_path):
    root = tmp_path
    inc = root / "include"
    src = root / "src"
    build = root / "build"
    inc.mkdir()
    src.mkdir()
    build.mkdir()

    defs_h = inc / "defs.h"
    defs_h.write_text(
        """
struct Foo { int x; };
enum Color { RED = 1, GREEN = 2 };
extern int g;
""".strip()
        + "\n",
        encoding="utf-8",
    )

    defs_c = src / "defs.c"
    defs_c.write_text(
        '#include "defs.h"\nint g = 7;\n',
        encoding="utf-8",
    )

    user_c = src / "user.c"
    user_c.write_text(
        '#include "defs.h"\nint use(void){ struct Foo f; f.x = 2; return g + (int)GREEN; }\n',
        encoding="utf-8",
    )

    # compile_commands.json describing both .c files
    cc = build / "compile_commands.json"
    entries = [
        {
            "directory": str(src),
            "file": str(defs_c),
            "command": f"clang -std=c99 -I{inc} -c {defs_c}",
        },
        {
            "directory": str(src),
            "file": str(user_c),
            "command": f"clang -std=c99 -I{inc} -c {user_c}",
        },
    ]
    _write_compile_commands(cc, entries)

    # Build project-wide definition maps (struct/enum/global)
    struct_map, enum_map, global_map = build_nonfunc_def_maps(str(cc))
    assert struct_map and enum_map and global_map

    # Parse the user TU and collect non-function refs, then backfill
    user_parser = CParser(str(user_c), extra_args=[f"-I{inc}", "-std=c99"])
    func = user_parser.get_function_info("use")

    # Before backfill, refs should not have tu_path assigned (cross-file)
    assert any(getattr(ref, "tu_path", None) in (None, "") for ref in func.struct_dependency_refs)
    assert any(getattr(ref, "tu_path", None) in (None, "") for ref in func.enum_dependency_refs)
    assert any(getattr(ref, "tu_path", None) in (None, "") for ref in func.global_dependency_refs)

    # Backfill
    user_parser.backfill_nonfunc_refs(struct_map, enum_map, global_map)

    # After backfill, tu_path should be set appropriately
    # struct Foo and enum Color come from defs.h; global g may resolve to defs.c (definition)
    # or defs.h (extern declaration), depending on libclang reference resolution.
    struct_paths = {ref.tu_path for ref in func.struct_dependency_refs}
    enum_paths = {ref.tu_path for ref in func.enum_dependency_refs}
    global_paths = {ref.tu_path for ref in func.global_dependency_refs}

    assert any(path and path.endswith("defs.h") for path in struct_paths)
    assert any(path and path.endswith("defs.h") for path in enum_paths)
    assert any(path and (path.endswith("defs.c") or path.endswith("defs.h")) for path in global_paths)
