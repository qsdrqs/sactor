import json
from pathlib import Path

from sactor import utils
from sactor.combiner import ProjectCombiner, TuArtifact


def test_project_combiner_creates_standalone_workspace_and_valid_root(tmp_path: Path) -> None:
    # Create an unrelated parent workspace root to simulate being inside a larger repo/workspace.
    wsroot = tmp_path / "wsroot"
    wsroot.mkdir()
    (wsroot / "Cargo.toml").write_text("[workspace]\nmembers = []\n", encoding="utf-8")

    proj = wsroot / "proj"
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

    cc = [
        {
            "directory": str(src_dir),
            "file": str(util_c),
            "command": f"clang -std=c99 -c {util_c}",
        },
        {
            "directory": str(src_dir),
            "file": str(main_c),
            "command": f"clang -std=c99 -c {main_c}",
        },
    ]
    cc_path = build_dir / "compile_commands.json"
    cc_path.write_text(json.dumps(cc, indent=2), encoding="utf-8")

    test_cmd = proj / "test_cmd.json"
    test_cmd.write_text(json.dumps([{"command": "echo ok"}]), encoding="utf-8")

    util_result_dir = proj / "result" / "util"
    main_result_dir = proj / "result" / "main"
    for variant in ("unidiomatic", "idiomatic"):
        (util_result_dir / f"translated_code_{variant}" / "functions").mkdir(parents=True)
        (main_result_dir / f"translated_code_{variant}" / "functions").mkdir(parents=True)

    (util_result_dir / "translated_code_unidiomatic" / "functions" / "add_integers.rs").write_text(
        "pub fn add_integers(lhs: i32, rhs: i32) -> i32 { lhs + rhs + 1 }\n",
        encoding="utf-8",
    )
    (main_result_dir / "translated_code_unidiomatic" / "functions" / "main.rs").write_text(
        "pub fn main() { let _ = add_integers(1, 2); }\n",
        encoding="utf-8",
    )

    (util_result_dir / "translated_code_idiomatic" / "functions" / "add_integers.rs").write_text(
        "pub fn add_integers(lhs: i32, rhs: i32) -> i32 { lhs + rhs + 2 }\n",
        encoding="utf-8",
    )
    (main_result_dir / "translated_code_idiomatic" / "functions" / "main.rs").write_text(
        "pub fn main() { let _ = add_integers(1, 2); }\n",
        encoding="utf-8",
    )

    config = utils.try_load_config(None)

    for variant in ("unidiomatic", "idiomatic"):
        output_root = wsroot / "out" / "combined" / variant
        pc = ProjectCombiner(
            config=config,
            test_cmd_path=str(test_cmd),
            output_root=str(output_root),
            compile_commands_file=str(cc_path),
            entry_tu_file=str(main_c),
            tu_artifacts=[
                TuArtifact(tu_path=str(util_c), result_dir=str(util_result_dir)),
                TuArtifact(tu_path=str(main_c), result_dir=str(main_result_dir)),
            ],
            variant=variant,
        )

        ok, crate_dir, _bin_path = pc.combine_and_build()
        assert ok is True

        manifest = (Path(crate_dir) / "Cargo.toml").read_text(encoding="utf-8")
        assert "[workspace]" in manifest

        main_rs = (Path(crate_dir) / "src" / "main.rs").read_text(encoding="utf-8")
        assert main_rs.splitlines()[0] == "#![allow(unused_imports, unused_variables, dead_code)]"
        util_rs = (Path(crate_dir) / "src" / "util.rs").read_text(encoding="utf-8")
        expected = "+ 1" if variant == "unidiomatic" else "+ 2"
        assert expected in util_rs
