import pytest
import subprocess
import shutil
import os
import tempfile

from sactor import rust_ast_parser
from sactor.c_parser import CParser
from sactor.combiner.partial_combiner import PartialCombiner
from sactor.verifier import UnidiomaticVerifier, Verifier, VerifyResult


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

    functions = {}
    structs = {}

    with open(struct_path1, "r") as f:
        structs["Course"] = f.read()
    with open(struct_path2, "r") as f:
        structs["Student"] = f.read()

    with open(func_path, "r") as f:
        functions["updateStudentInfo"] = f.read()

    combiner = PartialCombiner(functions, structs)
    _, combined_code = combiner.combine()

    return combined_code


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


def test_mutate_c_code():
    file_path = "tests/verifier/mutation_test.c"
    c_parser = CParser(file_path)
    verifier = UnidiomaticVerifier.__new__(UnidiomaticVerifier)

    with tempfile.TemporaryDirectory() as tmpdir:
        add = c_parser.get_function_info("add")

        result = verifier._mutate_c_code(
            add,
            file_path
        )
        print(result)
        with open(os.path.join(tmpdir, "mutation_add.c"), "w") as f:
            f.write(result)

        main = c_parser.get_function_info("main")
        result = verifier._mutate_c_code(
            main,
            file_path
        )
        print(result)

        with open(os.path.join(tmpdir, "mutation_main.c"), "w") as f:
            f.write(result)

        # compile the mutated code
        compiler = None
        if shutil.which("clang"):
            compiler = "clang"
        elif shutil.which("gcc"):
            compiler = "gcc"

        assert compiler is not None

        subprocess.run([
            compiler,
            os.path.join(tmpdir, "mutation_add.c"),
            os.path.join(tmpdir, "mutation_main.c"),
            "-o",
            os.path.join(tmpdir, "a.out"),
            '-ftrapv',
        ], check=True)

        result = subprocess.run(
            [os.path.join(tmpdir, "a.out")],
            check=True,
            capture_output=True
        )
        output = result.stdout.decode("utf-8")
        assert output.strip() == "c = 3"
