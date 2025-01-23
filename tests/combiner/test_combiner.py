import os
import shutil
import tempfile

from sactor import utils
from sactor.c_parser import CParser
from sactor.combiner import ProgramCombiner
from sactor.combiner.combiner_types import CombineResult
from tests.utils import config


def test_merge_groups():
    all_uses = [
        ['a', 'b'],
        ['a', 'b', 'c'],
        ['a', 'b', 'd'],
        ['a', 'b', 'e'],
        ['a', 'b', 'f'],
        ['a', 'g', '*'],
    ]

    # Create a new instance without calling __init__
    combiner = ProgramCombiner.__new__(ProgramCombiner)
    merged_uses = combiner._merge_uses(all_uses)
    assert merged_uses == [
        'use a::b;',
        'use a::b::c;',
        'use a::b::d;',
        'use a::b::e;',
        'use a::b::f;',
        'use a::g::*;',
    ]

def test_handle_ffi_libc_conflict():
    all_uses = [
        ['std', 'ffi', 'c_void'],
        ['std', 'ffi', 'c_int'],
        ['libc', 'c_void'],
    ]

    combiner = ProgramCombiner.__new__(ProgramCombiner)
    merged_uses = combiner._merge_uses(all_uses)
    assert merged_uses == [
        'use std::ffi::c_int;',
        'use libc::c_void;'
    ]


def test_combine(config):
    file_path = 'tests/c_examples/course_manage/course_manage.c'
    c_parser = CParser(file_path)

    functions = c_parser.get_functions()
    structs = c_parser.get_structs()
    global_vars = c_parser.get_global_vars()

    result_dir_with_type = 'tests/c_examples/course_manage/result/translated_code_unidiomatic'
    with tempfile.TemporaryDirectory() as tempdir:
        build_path = os.path.join(tempdir, 'build')
        result_path = os.path.join(
            tempdir, 'result', 'translated_code_unidiomatic')
        shutil.copytree(result_dir_with_type, result_path, dirs_exist_ok=True)
        os.remove(os.path.join(result_path, 'combined.rs'))

        combiner = ProgramCombiner(
            config,
            functions,
            structs,
            global_vars,
            'tests/c_examples/course_manage/course_manage_test.json',
            build_path,
            is_executable=True
        )

        combiner_result, _ = combiner.combine(result_path)
        assert combiner_result == CombineResult.SUCCESS
        assert os.path.exists(os.path.join(result_path, 'combined.rs'))
        with open(os.path.join(result_path, 'combined.rs'), 'r') as f:
            combined_code = f.read()
        with open('tests/c_examples/course_manage/result/translated_code_unidiomatic/combined.rs', 'r') as f:
            expected_code = f.read()

        with open(os.path.join(result_path, 'clippy_stat.json'), 'r') as f:
            stat = f.read()
        with open('tests/c_examples/course_manage/result/translated_code_unidiomatic/clippy_stat.json', 'r') as f:
            expected_stat = f.read()

        assert utils.normalize_string(
            stat) == utils.normalize_string(expected_stat)
        assert utils.normalize_string(
            combined_code) == utils.normalize_string(expected_code)


def test_combine_idiomatic(config):
    file_path = 'tests/c_examples/course_manage/course_manage.c'
    c_parser = CParser(file_path)

    functions = c_parser.get_functions()
    structs = c_parser.get_structs()
    global_vars = c_parser.get_global_vars()

    result_dir_with_type = 'tests/c_examples/course_manage/result/translated_code_idiomatic'
    with tempfile.TemporaryDirectory() as tempdir:
        build_path = os.path.join(tempdir, 'build')
        result_path = os.path.join(
            tempdir, 'result', 'translated_code_idiomatic')
        shutil.copytree(result_dir_with_type, result_path, dirs_exist_ok=True)
        # remove existing combined.rs
        os.remove(os.path.join(result_path, 'combined.rs'))

        combiner = ProgramCombiner(
            config,
            functions,
            structs,
            global_vars,
            'tests/c_examples/course_manage/course_manage_test.json',
            build_path,
            is_executable=True
        )

        combiner_result, _ = combiner.combine(result_path)
        assert combiner_result == CombineResult.SUCCESS
        assert os.path.exists(os.path.join(result_path, 'combined.rs'))
        with open(os.path.join(result_path, 'combined.rs'), 'r') as f:
            combined_code = f.read()
        with open('tests/c_examples/course_manage/result/translated_code_idiomatic/combined.rs', 'r') as f:
            expected_code = f.read()

        with open(os.path.join(result_path, 'clippy_stat.json'), 'r') as f:
            stat = f.read()
        with open('tests/c_examples/course_manage/result/translated_code_idiomatic/clippy_stat.json', 'r') as f:
            expected_stat = f.read()

        assert utils.normalize_string(
            stat) == utils.normalize_string(expected_stat)
        assert utils.normalize_string(
            combined_code) == utils.normalize_string(expected_code)
