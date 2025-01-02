import pytest

from sactor import rust_ast_parser
from sactor.c_parser import CParser
from sactor.verifier import UnidiomaticVerifier, VerifyResult
from sactor.verifier import Verifier

def test_verify_test_cmd():
    cmd_path = "tests/verifier/test_cmd.json"
    assert Verifier.verify_test_cmd(cmd_path)
    cmd_bad1_path = "tests/verifier/test_cmd_bad1.json"
    assert not Verifier.verify_test_cmd(cmd_bad1_path)
    cmd_bad2_path = "tests/verifier/test_cmd_bad2.json"
    assert not Verifier.verify_test_cmd(cmd_bad2_path)
    cmd_bad3_path = "tests/verifier/test_cmd_bad3.json"
    assert not Verifier.verify_test_cmd(cmd_bad3_path)

@pytest.fixture
def c_parser():
    c_path = "tests/c_examples/course_manage/course_manage.c"
    return CParser(c_path)

@pytest.fixture
def rust_code():
    func_path = "tests/c_examples/course_manage/result/translated_code_unidiomatic/functions/updateStudentInfo.rs"
    struct_path1 = "tests/c_examples/course_manage/result/translated_code_unidiomatic/structs/Course.rs"
    struct_path2 = "tests/c_examples/course_manage/result/translated_code_unidiomatic/structs/Student.rs"

    struct_code = ""
    with open(struct_path1, "r") as f:
        struct_code = f.read()
    with open(struct_path2, "r") as f:
        struct_code += f.read()

    function_code = ""
    with open(func_path, "r") as f:
        function_code = f.read()

    return rust_ast_parser.combine_struct_function(
        struct_code, function_code)


def test_embed_test(c_parser, rust_code):
    verifier = UnidiomaticVerifier(
        'tests/c_examples/course_manage/course_manage_test.json')
    result = verifier._embed_test_rust(
        c_parser.get_function_info("updateStudentInfo"),
        rust_code=rust_code,
        function_dependency_signatures=[],
    )
    assert result[0] == VerifyResult.SUCCESS

def test_embed_test_wrong(c_parser, rust_code):
    verifier = UnidiomaticVerifier(
        'tests/c_examples/course_manage/course_manage_test_wrong.json')
    result = verifier._embed_test_rust(
        c_parser.get_function_info("updateStudentInfo"),
        rust_code=rust_code,
        function_dependency_signatures=[],
    )
    assert result[0] == VerifyResult.FEEDBACK
    print(result[1])
