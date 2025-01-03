from sactor import utils
from sactor.c_parser import CParser
from sactor.combiner import ProgramCombiner
from sactor.combiner.combiner_types import CombineResult


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


def test_combine():
    file_path = 'tests/c_examples/course_manage/course_manage.c'
    c_parser = CParser(file_path)

    functions = c_parser.get_functions()
    structs = c_parser.get_structs()

    result_dir_with_type = 'tests/c_examples/course_manage/result/translated_code_unidiomatic'
    build_path = utils.get_temp_dir()

    combiner = ProgramCombiner(
        functions,
        structs,
        'tests/c_examples/course_manage/course_manage_test.json',
        build_path
    )

    combiner_result, _ = combiner.combine(result_dir_with_type)
    assert combiner_result == CombineResult.SUCCESS
