from sactor.c_parser import CParser


def test_c_parser():
    file_path = 'tests/c_examples/course_manage/course_manage.c'
    c_parser = CParser(file_path)
    print(c_parser.statistic())  # Will be emmited to the console

    assert len(c_parser.get_functions()) == 3
    assert len(c_parser.get_structs()) == 2
    update_student_info_deps = c_parser.get_function_info('updateStudentInfo').struct_dependencies
    assert set([struct.name for struct in update_student_info_deps]) == {
        'Student',
    }
    main_function_deps = c_parser.get_function_info('main').function_dependencies
    assert set([function.name for function in main_function_deps]) == {
        'updateStudentInfo',
        'printUsage',
    }

def test_c_parser_struct_dependency():
    file_path = 'tests/c_examples/course_manage/course_manage.c'
    c_parser = CParser(file_path)

    student_struct = c_parser.get_struct_info('Student')
    assert len(student_struct.dependencies) == 1
    assert student_struct.dependencies[0].name == 'Course'

def test_structs_in_signature():
    file_path = 'tests/c_parser/c_example.c'
    c_parser = CParser(file_path)

    printpoint = c_parser.get_function_info('printPoint')
    structs_in_signature = printpoint.get_structs_in_signature()
    structs_in_signature_names = [struct.name for struct in structs_in_signature]
    assert set(structs_in_signature_names) == {'Point'}
    structs_in_function = printpoint.struct_dependencies
    structs_in_function_names = [struct.name for struct in structs_in_function]
    assert set(structs_in_function_names) == {'Point'}

    foo = c_parser.get_function_info('foo')
    structs_in_signature = foo.get_structs_in_signature()
    structs_in_signature_names = [struct.name for struct in structs_in_signature]
    assert set(structs_in_signature_names) == set()
    structs_in_function = foo.struct_dependencies
    structs_in_function_names = [struct.name for struct in structs_in_function]
    assert set(structs_in_function_names) == {'Point'}
