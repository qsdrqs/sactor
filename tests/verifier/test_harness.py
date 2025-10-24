from functools import partial
from textwrap import dedent
from unittest.mock import patch

import pytest

from sactor import utils
from sactor.c_parser import CParser
from sactor.llm import LLM, llm_factory
from sactor.utils import read_file
from sactor.verifier import IdiomaticVerifier, VerifyResult
from tests.mock_llm import llm_with_mock
from tests.utils import config

pytestmark = pytest.mark.filterwarnings(
    "ignore:Pydantic serializer warnings:UserWarning"
)


def mock_query_impl(prompt, model, original=None, llm_instance=None):
    if "The following struct converters failed to compile." in prompt:
        if "pub struct Student" in prompt:
            return read_file('tests/verifier/mock_results/mock_student_harness')
        if "pub struct Course" in prompt:
            return read_file('tests/verifier/mock_results/mock_course_harness')
    if prompt.find('There are two structs: Student and CStudent') != -1:
        return read_file('tests/verifier/mock_results/mock_student_harness')
    if prompt.find('There are two structs: Course and CCourse') != -1:
        return read_file('tests/verifier/mock_results/mock_course_harness')
    return general_mock_query_impl(prompt, model, original, llm_instance)


def general_mock_query_impl(prompt, model, original=None, llm_instance=None):
    raise AssertionError(f"Unexpected LLM prompt in struct harness test: {prompt[:80]}")


@pytest.fixture
def llm():
    # Use shared helper to create a patched LLM
    yield from llm_with_mock(mock_query_impl)


def test_struct_harness(llm, config):
    c_path = 'tests/c_examples/course_manage/course_manage.c'
    c_parser = CParser(c_path)
    fixture_result_dir = 'tests/c_examples/course_manage/result'
    verifier = IdiomaticVerifier(
        'tests/c_examples/course_manage/course_manage_test.json',
        llm=llm,
        config=config,
        result_path=fixture_result_dir,
        unidiomatic_result_path=fixture_result_dir,
    )
    struct_path1 = "tests/c_examples/course_manage/result/translated_code_unidiomatic/structs/Course.rs"
    struct_path2 = "tests/c_examples/course_manage/result/translated_code_unidiomatic/structs/Student.rs"

    unidiomatic_structs_code = {}
    unidiomatic_structs_code['Course'] = read_file(struct_path1)
    unidiomatic_structs_code['Student'] = read_file(struct_path2)

    struct_path1 = "tests/c_examples/course_manage/result/translated_code_idiomatic/structs/Course.rs"
    struct_path2 = "tests/c_examples/course_manage/result/translated_code_idiomatic/structs/Student.rs"

    idiomatic_structs_code = {}
    idiomatic_structs_code['Course'] = read_file(struct_path1)
    idiomatic_structs_code['Student'] = read_file(struct_path2)

    result = verifier._struct_generate_test_harness(
        "Course",
        unidiomatic_structs_code['Course'],
        idiomatic_structs_code['Course'],
        [],
        "Course",
    )
    assert result[0] == VerifyResult.SUCCESS

    course = c_parser.get_struct_info('Course')

    verifier._struct_generate_test_harness(
        "Student",
        unidiomatic_structs_code['Student'],
        idiomatic_structs_code['Student'],
        [course],
        "Student",
    )


def test_struct_harness_case_insensitive_converters(monkeypatch, tmp_path, config):
    test_cmd = tmp_path / "test_cmd.json"
    test_cmd.write_text("[]")

    build_path = tmp_path / "build"
    struct_dir = build_path / "struct_test_harness"
    struct_dir.mkdir(parents=True)

    result_path = tmp_path / "result"
    (result_path / "translated_code_idiomatic" / "structs").mkdir(parents=True)
    (result_path / "translated_code_idiomatic" / "specs" / "structs").mkdir(parents=True)
    (result_path / "test_harness" / "structs").mkdir(parents=True)

    harness_template = dedent(
        """
        pub unsafe fn CNode_to_Node_mut(c: *mut Cnode) -> Node {
            let c_ref = unsafe { &*c };
            Node { value: c_ref.value }
        }

        pub unsafe fn Node_to_CNode_mut(node: *mut Node) -> *mut Cnode {
            let node_ref = unsafe { &*node };
            let boxed = Box::new(Cnode { value: node_ref.value });
            Box::into_raw(boxed)
        }
        """
    ).strip()

    monkeypatch.setattr(
        "sactor.verifier.idiomatic_verifier.generate_struct_harness_from_spec_file",
        lambda *args, **kwargs: harness_template,
    )

    compiled_payloads: list[str] = []

    def fake_compile(self, code, executable=False):
        compiled_payloads.append(code)
        assert "Cnode_to_Node_mut" in code
        assert "Node_to_Cnode_mut" in code
        return (VerifyResult.SUCCESS, None)

    monkeypatch.setattr(IdiomaticVerifier, "try_compile_rust_code", fake_compile)
    monkeypatch.setattr(
        "sactor.verifier.idiomatic_verifier.StructRoundTripTester.run_minimal",
        lambda self, combined_code, struct_name, idiomatic_name: (True, ""),
    )

    class _SilentLLM:
        def query(self, prompt):  # pragma: no cover - should not be used
            raise AssertionError("LLM should not be invoked in case fix test")

    verifier = IdiomaticVerifier(
        str(test_cmd),
        llm=_SilentLLM(),
        config=config,
        build_path=str(build_path),
        result_path=str(result_path),
        unidiomatic_result_path=str(result_path),
    )

    idiomatic_struct = "pub struct Node { pub value: i32 }\n"
    unidiomatic_struct = "#[repr(C)] pub struct node { pub value: i32 }\n"

    status, message = verifier._struct_generate_test_harness(
        "node",
        unidiomatic_struct,
        idiomatic_struct,
        [],
        "Node",
    )

    assert status == VerifyResult.SUCCESS
    assert message is None
    assert compiled_payloads
