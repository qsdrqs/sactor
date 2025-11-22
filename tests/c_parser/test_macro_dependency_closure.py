import os

from sactor.c_parser import CParser


def test_macro_dependency_closure_includes_nested_macros():
    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "macro_closure.c")
    parser = CParser(fixture, omit_error=True)

    macros = parser.get_macro_definitions_for_function("use_macros")
    text = "\n".join(macros)
    assert "#define OUTER" in text
    assert "#define MID" in text
    assert "#define INNER" in text
    # Ensure order is closure-respecting (OUTER should appear first)
    assert text.index("OUTER") < text.index("MID")
    assert text.index("MID") < text.index("INNER")
