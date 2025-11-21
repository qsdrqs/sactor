import os
import json
from pathlib import Path

from sactor.c_parser import CParser
from tests.utils import load_default_config
import pytest
from sactor.translator.unidiomatic_translator import UnidiomaticTranslator
from sactor.translator.translator_types import TranslateResult


@pytest.fixture
def config():
    return load_default_config()


def test_prepare_function_context_cross_tu(tmp_path, config):
    proj = tmp_path / 'proj'
    proj.mkdir()

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

    # Build compile_commands.json to parse with correct includes
    cc = [
        {
            'directory': str(proj),
            'file': str(util_c),
            'command': f'clang -I{proj} -std=c99 -c {util_c}',
            'output': 'util.o',
        },
        {
            'directory': str(proj),
            'file': str(main_c),
            'command': f'clang -I{proj} -std=c99 -c {main_c}',
            'output': 'main.o',
        },
    ]
    cc_path = proj / 'compile_commands.json'
    cc_path.write_text(json.dumps(cc, indent=2), encoding='utf-8')

    # Parse util to get USR for add_integers
    util_parser = CParser(str(util_c), extra_args=[f'-I{proj}'])
    add_fn = util_parser.get_function_info('add_integers')
    add_usr = getattr(add_fn, 'usr', '')
    assert add_usr

    # Create fake util result dir with unidiomatic artifact for add_integers
    util_result_dir = tmp_path / 'out' / 'util_slug'
    (util_result_dir / 'translated_code_unidiomatic' / 'functions').mkdir(parents=True)
    util_artifact = util_result_dir / 'translated_code_unidiomatic' / 'functions' / 'add_integers.rs'
    util_artifact.write_text(
        'extern crate libc;\n\n'
        'pub unsafe fn add_integers(lhs: libc::c_int, rhs: libc::c_int) -> libc::c_int { lhs + rhs }\n',
        encoding='utf-8',
    )

    # Prepare main translator with project_usr_to_result_dir mapping
    main_parser = CParser(str(main_c), extra_args=[f'-I{proj}'])
    project_map = {add_usr: str(util_result_dir)}
    main_result_dir = tmp_path / 'out' / 'main_slug'
    translator = UnidiomaticTranslator(
        llm=None,  # not used in prepare context
        c2rust_translation='',
        c_parser=main_parser,
        test_cmd_path=str(cc_path),  # dummy path; not used here
        config=config,
        result_path=str(main_result_dir),
        processed_compile_commands=[],
        link_args=[],
        compile_commands_file=str(cc_path),
        entry_tu_file=str(main_c),
        link_closure=[],
        project_usr_to_result_dir=project_map,
    )

    status, ctx = translator._prepare_function_context(main_parser.get_function_info('main'))
    assert status == TranslateResult.SUCCESS
    assert ctx is not None
    sigs = ctx['function_dependency_signatures']
    assert any('add_integers' in s for s in sigs)
