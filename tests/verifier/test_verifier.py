from sactor import rust_ast_parser
from sactor.c_parser import CParser
from sactor.verifier import UnidiomaticVerifier, VerifyResult

def test_run_tests1():
    verifier = UnidiomaticVerifier("tests/verifier/mock_results/return0stdout")
    result = verifier._run_tests("")
    assert result[0] == VerifyResult.SUCCESS
    assert result[1] == None

def test_run_tests2():
    verifier = UnidiomaticVerifier("tests/verifier/mock_results/return0stderr")
    result = verifier._run_tests("")
    assert result[0] == VerifyResult.SUCCESS
    assert result[1] == None

def test_run_tests3():
    verifier = UnidiomaticVerifier("tests/verifier/mock_results/return1stdout")
    result = verifier._run_tests("")
    assert result[0] == VerifyResult.TEST_ERROR
    assert result[1] == "Hello, world!\n"

def test_run_tests4():
    verifier = UnidiomaticVerifier("tests/verifier/mock_results/return1stderr")
    result = verifier._run_tests("")
    assert result[0] == VerifyResult.TEST_ERROR
    assert result[1] == "Some error message\n"

def test_run_tests5():
    verifier = UnidiomaticVerifier("tests/verifier/mock_results/return1stdoutstderr")
    result = verifier._run_tests("")
    assert result[0] == VerifyResult.TEST_ERROR
    assert result[1] == "Some error message\n"

def test_embed_test():
    c_path = "tests/c_examples/course_manage.c"
    func_path = "tests/c_examples/result/translated_code_unidiomatic/functions/updateStudentInfo.rs"
    struct_path1 = "tests/c_examples/result/translated_code_unidiomatic/structs/Course.rs"
    struct_path2 = "tests/c_examples/result/translated_code_unidiomatic/structs/Student.rs"

    struct_code = ""
    with open(struct_path1, "r") as f:
        struct_code = f.read()
    with open(struct_path2, "r") as f:
        struct_code += f.read()

    function_code = ""
    with open(func_path, "r") as f:
        function_code = f.read()

    rust_code = rust_ast_parser.combine_struct_function(struct_code, function_code)
    c_parser = CParser(c_path)

    verifier = UnidiomaticVerifier(['python', 'tests/c_examples/course_manage_test.py'])
    result = verifier._embed_test_rust(
        c_parser.get_function_info("updateStudentInfo"),
        rust_code=rust_code,
        function_dependency_signatures=[],
    )
    assert result[0] == VerifyResult.SUCCESS

    verifier = UnidiomaticVerifier(['python', 'tests/c_examples/course_manage_wrong_test.py'])
    result = verifier._embed_test_rust(
        c_parser.get_function_info("updateStudentInfo"),
        rust_code=rust_code,
        function_dependency_signatures=[],
    )
    assert result[0] == VerifyResult.TEST_ERROR
    print(result[1])
