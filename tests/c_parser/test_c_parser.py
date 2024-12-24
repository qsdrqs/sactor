from sactor.c_parser import CParser


def test_c_parser():
    file_path = 'tests/c_examples/course_manage.c'
    c_parser = CParser(file_path)
    print(c_parser.statistic())  # Will be emmited to the console

    assert len(c_parser.functions) == 3
    assert len(c_parser.structs_unions) == 2
    update_student_info_deps = c_parser.functions['updateStudentInfo'].struct_dependencies
    assert set([struct.name for struct in update_student_info_deps]) == {
        'Student',
    }
    main_function_deps = c_parser.functions['main'].function_dependencies
    assert set([function.name for function in main_function_deps]) == {
        'updateStudentInfo',
        'printUsage',
    }

def test_c_parser_struct_dependency():
    file_path = 'tests/c_examples/course_manage.c'
    c_parser = CParser(file_path)

    student_struct = c_parser.structs_unions['Student']
    assert len(student_struct.dependencies) == 1
    assert student_struct.dependencies[0].name == 'Course'


