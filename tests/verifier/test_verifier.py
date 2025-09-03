import pytest
import subprocess
import shutil
import os
import tempfile
from types import SimpleNamespace

from sactor import rust_ast_parser
from sactor.utils import read_file
from sactor.c_parser import CParser
from sactor.combiner.partial_combiner import PartialCombiner
from sactor.verifier import UnidiomaticVerifier, Verifier, VerifyResult
from tests.utils import config
from sactor.combiner import RustCode


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

    structs["Course"] = read_file(struct_path1)
    structs["Student"] = read_file(struct_path2)

    functions["updateStudentInfo"] = read_file(func_path)

    combiner = PartialCombiner(functions, structs)
    _, combined_code = combiner.combine()

    return combined_code


def test_embed_test(c_parser, rust_code, config):
    verifier = UnidiomaticVerifier(
        'tests/c_examples/course_manage/course_manage_test.json', config)
    result = verifier._embed_test_rust(
        c_parser.get_function_info("updateStudentInfo"),
        rust_code=rust_code,
        function_dependency_signatures=[],
    )
    assert result[0] == VerifyResult.SUCCESS


def test_embed_test_wrong(c_parser, rust_code, config):
    verifier = UnidiomaticVerifier(
        'tests/c_examples/course_manage/course_manage_test_wrong.json', config)
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

def test_verify_function_with_dependency_uses(config, monkeypatch):
    dependency_code = """
use std::collections::HashMap;

fn my_dependency() -> i32 {
    let mut map = HashMap::new();
    map.insert(1, 2);
    map.get(&1).copied().unwrap_or(0)
}
"""
    function_code = """
use foo::bar;

fn my_function() -> i32 {
    my_dependency()
}
"""

    def mock_try_compile_rust_code_impl(self, rust_code, executable=False):
        # This is the core of the test. We check if the `use` statement from the dependency
        # is correctly added to the code that is being compiled.
        print(rust_code)
        assert "use std::collections::HashMap;" in rust_code
        assert "fn my_dependency() -> i32" in rust_code
        assert "use foo::bar;" in rust_code
        return (VerifyResult.SUCCESS, None)

    # We mock the implementation of `_try_compile_rust_code_impl` to avoid actual compilation
    # and just check the generated code.
    monkeypatch.setattr(UnidiomaticVerifier, "_try_compile_rust_code_impl", mock_try_compile_rust_code_impl)

    # We also need to mock `_embed_test_rust` to avoid running the test harness
    def mock_embed_test_rust(*args, **kwargs):
        return (VerifyResult.SUCCESS, None)

    monkeypatch.setattr(UnidiomaticVerifier, "_embed_test_rust", mock_embed_test_rust)

    verifier = UnidiomaticVerifier(
        'tests/c_examples/course_manage/course_manage_test.json', config
    )

    # Mock FunctionInfo object
    function_info = SimpleNamespace(
        name="my_function",
        node=SimpleNamespace(location=SimpleNamespace(file=SimpleNamespace(name="dummy.c")))
    )

    dependency_uses = RustCode(dependency_code).used_code_list

    verifier.verify_function(
        function_info,
        function_code=function_code,
        data_type_code={},
        function_dependency_signatures=["fn my_dependency() -> i32;"],
        function_dependency_uses=dependency_uses,
        has_prefix=False
    )
