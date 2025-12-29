from pathlib import Path

from sactor import utils
from sactor.c_parser import CParser
from sactor.c_parser.project_index import build_link_closure
from sactor.verifier.idiomatic_verifier import IdiomaticVerifier
from sactor.verifier.unidiomatic_verifier import UnidiomaticVerifier
from sactor.verifier.verifier_types import VerifyResult


class _DummyLLM:
    def query(self, *args, **kwargs):
        raise AssertionError("LLM should not be called during relink tests")

    def statistic(self, *args, **kwargs):
        return None


RUST_DOT_PRODUCT = """\
pub unsafe fn dot_product(lhs: *const i32, rhs: *const i32, length: usize) -> i32 {
    let mut total: i32 = 0;
    let mut i: usize = 0;
    while i < length {
        total = total.wrapping_add((*lhs.add(i) as i32).wrapping_mul(*rhs.add(i) as i32));
        i += 1;
    }
    total
}
"""

RUST_AVERAGE = """\
pub unsafe fn average(values: *const i32, length: usize) -> f64 {
    if length == 0 {
        return 0.0;
    }
    let mut sum: i64 = 0;
    let mut i: usize = 0;
    while i < length {
        sum += *values.add(i) as i64;
        i += 1;
    }
    sum as f64 / length as f64
}
"""


def _project_paths() -> tuple[Path, Path, Path, Path]:
    base = Path(__file__).resolve().parents[1] / "c_examples" / "cmake_multi"
    cc_path = base / "build" / "compile_commands.json"
    entry_tu = base / "src" / "main.c"
    test_cmd = base / "test_cmd.json"
    return base, cc_path, entry_tu, test_cmd


def _load_function_info(cc_path: Path, c_path: Path, function_name: str):
    commands = utils.load_compile_commands_from_file(str(cc_path), str(c_path))
    flags = utils.get_compile_flags_from_commands(commands)
    parser = CParser(str(c_path), extra_args=flags, omit_error=True)
    return parser.get_function_info(function_name)


def _run_project_relink(verifier, function_info, rust_code, idiomatic: bool):
    result = verifier._embed_test_rust(
        function_info,
        rust_code,
        prefix=False,
        idiomatic=idiomatic,
    )
    assert result[0] == VerifyResult.SUCCESS, result[1]


def test_project_relink_verify_bin_unidiomatic(tmp_path):
    base, cc_path, entry_tu, test_cmd = _project_paths()
    target_tu = base / "src" / "math_utils.c"
    link_closure = build_link_closure(str(entry_tu), str(cc_path))
    assert link_closure

    function_info = _load_function_info(cc_path, target_tu, "dot_product")
    config = utils.try_load_config(None)

    verifier = UnidiomaticVerifier(
        test_cmd_path=str(test_cmd),
        config=config,
        build_path=str(tmp_path / "build"),
        processed_compile_commands=[],
        link_args=[],
        compile_commands_file=str(cc_path),
        entry_tu_file=str(entry_tu),
        link_closure=link_closure,
    )

    _run_project_relink(verifier, function_info, RUST_DOT_PRODUCT, idiomatic=False)


def test_project_relink_verify_bin_idiomatic(tmp_path):
    base, cc_path, entry_tu, test_cmd = _project_paths()
    target_tu = base / "src" / "stats.c"
    link_closure = build_link_closure(str(entry_tu), str(cc_path))
    assert link_closure

    function_info = _load_function_info(cc_path, target_tu, "average")
    config = utils.try_load_config(None)

    verifier = IdiomaticVerifier(
        test_cmd_path=str(test_cmd),
        llm=_DummyLLM(),
        config=config,
        build_path=str(tmp_path / "build"),
        processed_compile_commands=[],
        link_args=[],
        compile_commands_file=str(cc_path),
        entry_tu_file=str(entry_tu),
        link_closure=link_closure,
    )

    _run_project_relink(verifier, function_info, RUST_AVERAGE, idiomatic=True)
