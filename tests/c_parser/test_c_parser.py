import os
import subprocess
import tempfile

from sactor import utils
from tests.utils import find_project_root
from sactor.c_parser import CParser


def test_c_parser():
    file_path = 'tests/c_examples/course_manage/course_manage.c'
    c_parser = CParser(file_path)
    print(c_parser.statistic())  # Will be emmited to the console

    assert len(c_parser.get_functions()) == 3
    assert len(c_parser.get_structs()) == 2
    update_student_info_deps = c_parser.get_function_info(
        'updateStudentInfo').struct_dependencies
    assert set([struct.name for struct in update_student_info_deps]) == {
        'Student',
    }
    main_function_deps = c_parser.get_function_info(
        'main').function_dependencies
    assert set([function.name for function in main_function_deps]) == {
        'updateStudentInfo',
        'printUsage',
    }


def test_c_parser_get_signature():
    file_path = 'tests/c_examples/course_manage/course_manage.c'
    c_parser = CParser(file_path)

    update_student_info = c_parser.get_function_info('updateStudentInfo')
    assert update_student_info.get_signature(
    ) == 'void updateStudentInfo ( struct Student * student , const char * newName , int newAge )'

    print_usage = c_parser.get_function_info('printUsage')
    assert print_usage.get_signature() == 'void printUsage ( )'


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
    structs_in_signature_names = [
        struct.name for struct in structs_in_signature]
    assert set(structs_in_signature_names) == {'Point'}
    structs_in_function = printpoint.struct_dependencies
    structs_in_function_names = [struct.name for struct in structs_in_function]
    assert set(structs_in_function_names) == {'Point'}

    foo = c_parser.get_function_info('foo')
    structs_in_signature = foo.get_structs_in_signature()
    structs_in_signature_names = [
        struct.name for struct in structs_in_signature]
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

    main_function_deps = c_parser.get_function_info(
        'main').function_dependencies
    assert set([function.name for function in main_function_deps]) == {
        'foo',
    }


def test_function_get_declaration():
    file_path = 'tests/c_parser/c_example_size_t.c'
    c_parser = CParser(file_path)

    foo = c_parser.get_function_info('foo')
    foo_declaration_node = foo.get_declaration_nodes()
    assert len(foo_declaration_node) > 0
    foo_declaration_node = foo_declaration_node[0]
    foo_start_line = foo.node.extent.start.line
    foo_declaration_start_line = foo_declaration_node.extent.start.line
    print(
        f'foo_start_line: {foo_start_line}, foo_declaration_start_line: {foo_declaration_start_line}')
    assert foo_declaration_start_line < foo_start_line

    main = c_parser.get_function_info('main')
    main_declaration_node = main.get_declaration_nodes()
    assert len(main_declaration_node) == 0


def test_global_var():
    file_path = 'tests/c_parser/c_example_global_var.c'
    c_parser = CParser(file_path)

    assert len(c_parser.get_functions()) == 1
    assert len(c_parser.get_structs()) == 0

    main_function_deps = c_parser.get_function_info(
        'main').global_vars_dependencies
    assert set([var.name for var in main_function_deps]) == {
        'global_var',
    }


def test_const_global_var():
    file_path = 'tests/c_examples/const_global/const_global.c'
    c_parser = CParser(file_path)

    assert len(c_parser.get_functions()) == 2
    assert len(c_parser.get_structs()) == 0

    g_var = c_parser.get_function_info('printGrades').global_vars_dependencies
    assert len(g_var) == 1
    assert g_var[0].is_const
    assert g_var[0].is_array
    assert g_var[0].array_size == 5

    g_var = c_parser.get_function_info('main').global_vars_dependencies
    assert len(g_var) == 1
    assert g_var[0].is_const


def test_const_global_var2():
    c_code = '''
static const unsigned short arr[4] = {
// comment here
1, 2, // comment here
3, 4
};
int main() { arr; }
'''
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = f'{tmpdir}/const_global_var2.c'
        with open(file_path, 'w') as f:
            f.write(c_code)
        c_parser = CParser(file_path)

        g_var = c_parser._global_vars
        assert 'arr' in g_var
        g_var_code = c_parser.extract_global_var_definition_code('arr')
        expected_code = '''
static const unsigned short arr[4] = {
// comment here
1, 2, // comment here
3, 4
};'''
        assert g_var_code.strip() == expected_code.strip()


def test_struct_enum_dependencies():
    c_code = '''
struct Foo {
    enum { FOO_KIND_A = 0, FOO_KIND_B = 1 } kind;
    int value;
};

int consume(struct Foo *foo) {
    if (foo->kind == FOO_KIND_A) {
        return foo->value;
    }
    return 0;
}
'''

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = f'{tmpdir}/struct_enum.c'
        with open(file_path, 'w') as f:
            f.write(c_code)

        c_parser = CParser(file_path)
        foo_info = c_parser.get_struct_info('Foo')

        enum_names = [enum.name for enum in foo_info.enum_dependencies]
        assert len(enum_names) == 1
        assert enum_names[0].startswith('enum_')

        parser_enum_names = [enum.name for enum in c_parser.get_enums()]
        assert enum_names[0] in parser_enum_names


def test_typedef():
    file_path = 'tests/c_examples/typedef/typedef_sample.c'
    c_parser = CParser(file_path)
    print(c_parser._type_alias)

    assert len(c_parser.get_functions()) == 2
    calculate_distance = c_parser.get_function_info('calculate_distance')
    assert len(calculate_distance.get_structs_in_signature()) == 1
    assert len(calculate_distance.struct_dependencies) == 1


def test_extract_enum_def():
    file_path = 'tests/c_examples/enum/enum.c'
    c_parser = CParser(file_path)
    print(c_parser._enums)

    foo = c_parser.get_function_info('foo')
    assert len(foo.enum_dependencies) == 1

    days = c_parser.get_enum_info('Days')
    code = c_parser.extract_enum_definition_code(days.name)
    expected_code = '''
enum Days {
    MON = 1,
    TUE = 2,
    WED = 3,
    THU = 4,
    FRI = 5,
    SAT = 6,
    SUN = 7
};'''
    assert code.strip() == expected_code.strip()

def test_include():
    code = '''
#include <stdbool.h>
bool foo() { return true; }'''
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = f'{tmpdir}/tmp.c'
        with open(file_path, 'w') as f:
            f.write(code)
        print(f'-I{find_project_root()}/include')
        c_parser = CParser(file_path)
        foo = c_parser.get_function_info('foo')
        tokens = utils.cursor_get_tokens(foo.node)
        token_spellings = [token.spelling for token in tokens]
        print(token_spellings)
        assert token_spellings == ['bool', 'foo',
                                   '(', ')', '{', 'return', 'true', ';', '}']


def test_stdio():
    code = '''
#include <stdio.h>
int main() {
    char str[100];
    fgets(str, 100, stdin);
    str[99] = '\\0';
    fprintf(stderr, "%s", str);
    return 0;
}'''
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = f'{tmpdir}/tmp.c'
        with open(file_path, 'w') as f:
            f.write(code)
        c_parser = CParser(file_path)
        main = c_parser.get_function_info('main')
        assert set(main.stdio_list) == {'stdin', 'stderr'}
