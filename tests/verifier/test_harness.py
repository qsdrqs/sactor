import pytest

from sactor.c_parser import CParser
from sactor.verifier import IdiomaticVerifier, VerifyResult
from tests.azure_llm import azure_llm, general_mock_query_impl

def mock_query_impl(prompt, model, original=None, llm_instance=None):
    if prompt.find('There are two structs: Student and CStudent') != -1:
        with open('tests/verifier/mock_results/mock_student_harness') as f:
            return f.read()
    if prompt.find('There are two structs: Course and CCourse') != -1:
        with open('tests/verifier/mock_results/mock_course_harness') as f:
            return f.read()
    return mock_query_impl(original, llm_instance, prompt, model)

@pytest.fixture
def llm():
    yield from azure_llm(mock_query_impl)


def test_struct_harness(llm):
    c_path = 'tests/c_examples/course_manage/course_manage.c'
    c_parser = CParser(c_path)
    verifier = IdiomaticVerifier(
        'tests/c_examples/course_manage/course_manage_test.json',
        llm=llm,
        max_attempts=6
    )
    struct_path1 = "tests/c_examples/course_manage/result/translated_code_unidiomatic/structs/Course.rs"
    struct_path2 = "tests/c_examples/course_manage/result/translated_code_unidiomatic/structs/Student.rs"

    unidiomatic_structs_code = {}
    with open(struct_path1, 'r') as f:
        unidiomatic_structs_code['Course'] = f.read()
    with open(struct_path2, 'r') as f:
        unidiomatic_structs_code['Student'] = f.read()

    struct_path1 = "tests/c_examples/course_manage/result/translated_code_idiomatic/structs/Course.rs"
    struct_path2 = "tests/c_examples/course_manage/result/translated_code_idiomatic/structs/Student.rs"

    idiomatic_structs_code = {}
    with open(struct_path1, 'r') as f:
        idiomatic_structs_code['Course'] = f.read()
    with open(struct_path2, 'r') as f:
        idiomatic_structs_code['Student'] = f.read()


    result = verifier._struct_generate_test_harness(
        "Course",
        unidiomatic_structs_code['Course'],
        idiomatic_structs_code['Course'],
        []
    )
    assert result[0] == VerifyResult.SUCCESS

    course = c_parser.get_struct_info('Course')

    verifier._struct_generate_test_harness(
        "Student",
        unidiomatic_structs_code['Student'],
        idiomatic_structs_code['Student'],
    [course]
    )
