import json
import os
import shutil
import tempfile

from sactor import rust_ast_parser, utils
from sactor.utils import read_file
from sactor.c_parser import CParser
from sactor.combiner import ProgramCombiner
from sactor.combiner import merge_uses
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

    merged_uses = merge_uses(all_uses)
    assert set(merged_uses) == {
        'use a::b;',
        'use a::b::c;',
        'use a::b::d;',
        'use a::b::e;',
        'use a::b::f;',
        'use a::g::*;',
    }

def test_handle_ffi_libc_conflict():
    all_uses = [
        ['std', 'env'],
        ['std', 'ffi', 'CString'],
        ['std', 'ffi', 'c_void'],
        ['std', 'ffi', 'c_int'],
        ['libc', 'c_void'],
        ['std', 'os', 'raw', 'c_int'],
    ]

    merged_uses = merge_uses(all_uses)
    print(merged_uses)
    assert set(merged_uses) == {
        'use std::env;',
        'use std::ffi::CString;',
        'use libc::c_void;',
        'use std::ffi::c_int;',
    }

def test_combine(config):
    file_path = 'tests/c_examples/course_manage/course_manage.c'
    c_parser = CParser(file_path)

    result_dir_with_type = 'tests/c_examples/course_manage/result/translated_code_unidiomatic'
    with tempfile.TemporaryDirectory() as tempdir:
        build_path = os.path.join(tempdir, 'build')
        result_path = os.path.join(
            tempdir, 'result', 'translated_code_unidiomatic')
        shutil.copytree(result_dir_with_type, result_path, dirs_exist_ok=True)
        os.remove(os.path.join(result_path, 'combined.rs'))

        combiner = ProgramCombiner(
            config,
            c_parser,
            'tests/c_examples/course_manage/course_manage_test.json',
            build_path,
            is_executable=True
        )

        combiner_result, _ = combiner.combine(result_path)
        assert combiner_result == CombineResult.SUCCESS
        assert os.path.exists(os.path.join(result_path, 'combined.rs'))
        combined_code = read_file(os.path.join(result_path, 'combined.rs'))
        expected_code = read_file('tests/c_examples/course_manage/result/translated_code_unidiomatic/combined.rs')

        stat = json.loads(read_file(os.path.join(result_path, 'clippy_stat.json')))
        expected_stat = json.loads(read_file('tests/c_examples/course_manage/result/translated_code_unidiomatic/clippy_stat.json'))

        for key in ("total_warnings", "total_errors", "warnings", "errors"):
            assert stat[key] == expected_stat[key]

        total_tokens, unsafe_tokens = rust_ast_parser.count_unsafe_tokens(combined_code)
        unsafe_fraction = (unsafe_tokens / total_tokens) if total_tokens else 0.0
        assert stat["total_tokens"] == total_tokens
        assert stat["unsafe_tokens"] == unsafe_tokens
        assert stat["unsafe_fraction"] == unsafe_fraction
        assert utils.normalize_string(
            combined_code) == utils.normalize_string(expected_code)


def test_combine_idiomatic(config):
    file_path = 'tests/c_examples/course_manage/course_manage.c'
    c_parser = CParser(file_path)

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
            c_parser,
            'tests/c_examples/course_manage/course_manage_test.json',
            build_path,
            is_executable=True
        )

        combiner_result, _ = combiner.combine(result_path)
        assert combiner_result == CombineResult.SUCCESS
        assert os.path.exists(os.path.join(result_path, 'combined.rs'))
        combined_code = read_file(os.path.join(result_path, 'combined.rs'))
        expected_code = read_file('tests/c_examples/course_manage/result/translated_code_idiomatic/combined.rs')

        stat = json.loads(read_file(os.path.join(result_path, 'clippy_stat.json')))
        expected_stat = json.loads(read_file('tests/c_examples/course_manage/result/translated_code_idiomatic/clippy_stat.json'))

        for key in ("total_warnings", "total_errors", "warnings", "errors"):
            assert stat[key] == expected_stat[key]

        total_tokens, unsafe_tokens = rust_ast_parser.count_unsafe_tokens(combined_code)
        unsafe_fraction = (unsafe_tokens / total_tokens) if total_tokens else 0.0
        assert stat["total_tokens"] == total_tokens
        assert stat["unsafe_tokens"] == unsafe_tokens
        assert stat["unsafe_fraction"] == unsafe_fraction
        assert utils.normalize_string(
            combined_code) == utils.normalize_string(expected_code)
