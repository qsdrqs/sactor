from sactor.c_parser import CParser
import os
import tempfile
import subprocess


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

def test_clang_compile():
    file_path = 'tests/c_parser/c_example.c'
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = ['clang', file_path, '-o', f'{tmpdir}/c_example']
        subprocess.run(cmd, check=True)
        assert os.path.exists(f'{tmpdir}/c_example')

def test_c_parser2():
    file_path = 'tests/c_parser/c_example_size_t.c'
    c_parser = CParser(file_path)
    c_parser.print_ast()

    assert len(c_parser.get_functions()) == 2
    assert len(c_parser.get_structs()) == 0

    main_function_deps = c_parser.get_function_info('main').function_dependencies
    assert set([function.name for function in main_function_deps]) == {
        'foo',
    }

def test_function_get_declaration():
    file_path = 'tests/c_parser/c_example_size_t.c'
    c_parser = CParser(file_path)

    foo = c_parser.get_function_info('foo')
    foo_declaration_node = foo.get_declaration_node()
    assert foo_declaration_node is not None

    foo_start_line = foo.node.extent.start.line
    foo_declaration_start_line = foo_declaration_node.extent.start.line
    print(f'foo_start_line: {foo_start_line}, foo_declaration_start_line: {foo_declaration_start_line}')
    assert foo_declaration_start_line < foo_start_line

    main = c_parser.get_function_info('main')
    main_declaration_node = main.get_declaration_node()
    assert main_declaration_node is None


def test_global_var():
    file_path = 'tests/c_parser/c_example_global_var.c'
    c_parser = CParser(file_path)

    assert len(c_parser.get_functions()) == 1
    assert len(c_parser.get_structs()) == 0

    main_function_deps = c_parser.get_function_info('main').global_vars_dependencies
    assert set([var.displayname for var in main_function_deps]) == {
        'global_var',
    }

def test_typedef():
    file_path = 'tests/c_examples/typedef/typedef_sample.c'
    c_parser = CParser(file_path)
    print(c_parser._type_alias)

    assert len(c_parser.get_functions()) == 2
    calculate_distance = c_parser.get_function_info('calculate_distance')
    assert len(calculate_distance.get_structs_in_signature()) == 1
    assert len(calculate_distance.struct_dependencies) == 1
