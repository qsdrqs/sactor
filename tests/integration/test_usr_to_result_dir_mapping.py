import json
import os
from pathlib import Path

import pytest

from sactor import Sactor
from tests.mock_llm import llm_with_mock


def _mock_query_impl(prompt, model, original=None, llm_instance=None):
    # Minimal function translations for this test
    if 'int add_integers' in prompt:
        return (
            '----FUNCTION----\n'
            '```rust\n'
            'extern crate libc;\n'
            'pub unsafe fn add_integers(lhs: libc::c_int, rhs: libc::c_int) -> libc::c_int { lhs + rhs }\n'
            '```\n'
            '----END FUNCTION----\n'
        )
    if 'int main' in prompt:
        return (
            '----FUNCTION----\n'
            '```rust\n'
            'pub fn main() { }\n'
            '```\n'
            '----END FUNCTION----\n'
        )
    # Any unexpected prompt should fail fast in this test
    raise AssertionError(f"Unexpected prompt: {prompt[:120]}")


@pytest.fixture
def llm():
    yield from llm_with_mock(_mock_query_impl)


def test_usr_to_result_dir_resolution_cross_tu(tmp_path, llm):
    proj = tmp_path / 'proj'
    build_dir = proj / 'build'
    proj.mkdir()
    build_dir.mkdir()

    util_c = proj / 'util.c'
    util_h = proj / 'util.h'
    main_c = proj / 'main.c'

    util_h.write_text('int add_integers(int lhs, int rhs);\n', encoding='utf-8')
    util_c.write_text(
        '#include "util.h"\nint add_integers(int lhs, int rhs){return lhs+rhs;}\n',
        encoding='utf-8',
    )
    main_c.write_text(
        '#include "util.h"\nint main(void){return add_integers(1,2);}\n',
        encoding='utf-8',
    )

    cc = [
        {
            'directory': str(build_dir),
            'file': str(util_c),
            'command': f'clang -I{proj} -std=c99 -c {util_c}',
            'output': 'util.o',
        },
        {
            'directory': str(build_dir),
            'file': str(main_c),
            'command': f'clang -I{proj} -std=c99 -c {main_c}',
            'output': 'main.o',
        },
    ]
    cc_path = build_dir / 'compile_commands.json'
    cc_path.write_text(json.dumps(cc, indent=2), encoding='utf-8')

    test_cmd = proj / 'test_cmd.json'
    test_cmd.write_text(json.dumps([{'command': 'echo ok'}]), encoding='utf-8')

    outdir = tmp_path / 'out'
    res = Sactor.translate(
        target_type='bin',
        test_cmd_path=str(test_cmd),
        compile_commands_file=str(cc_path),
        result_dir=str(outdir),
        unidiomatic_only=True,
        configure_logging=False,
    )

    assert res.any_failed is False

    combined_root = Path(res.base_result_dir) / 'combined'
    uni_crate_dir = combined_root / 'unidiomatic' / 'proj'
    assert (uni_crate_dir / 'Cargo.toml').exists()
    assert (uni_crate_dir / 'src' / 'main.rs').exists()
    assert list((combined_root / 'unidiomatic').glob('*.rs')) == []
    assert (combined_root / 'idiomatic').exists() is False
