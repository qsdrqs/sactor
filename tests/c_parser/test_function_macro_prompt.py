import os

from sactor.c_parser import CParser


def test_macro_definitions_and_raw_source_are_preserved():
    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "macro_prompt.c")
    parser = CParser(fixture, omit_error=True)

    code = parser.extract_function_code("macro_sample")
    assert "#define DOUBLE" in code
    assert "DOUBLE(x)" in code
    assert "OUTER(x)" in code

    macro_defs = parser.get_macro_definitions_for_function("macro_sample")
    combined = "\n".join(macro_defs)
    assert "DOUBLE(y)" in combined
    assert "OUTER(z)" in combined
    assert "definition unavailable" not in combined
