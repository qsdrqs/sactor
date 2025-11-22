import os

from sactor.c_parser import CParser


def test_function_code_excludes_inactive_branches_and_handles_nonascii():
    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "conditional_prompt.c")
    parser = CParser(fixture, omit_error=True)

    code = parser.extract_function_code("conditional_demo")
    assert "return x + 2;" in code
    assert "return x + 1;" not in code
    # ensure non-ascii header didn't break offsets
    assert "conditional_demo" in code
