import os

from sactor.c_parser import CParser


def test_macro_definition_uses_tokens_not_trimmed():
    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "macro_tokens.c")
    parser = CParser(fixture, omit_error=True)

    macros = parser.get_macro_definitions_for_function("seedexpander_init")
    text = "\n".join(macros)
    assert "#define RNG_BAD_MAXLEN -1" in text
    assert "#define RNG_SUCCESS 0" in text
