from types import SimpleNamespace

from sactor.c_parser.c_parser import CParser
from sactor.translator.unidiomatic_translator import UnidiomaticTranslator
from sactor.utils import load_default_config


class _DummyLLM:
    def __init__(self, responder=None):
        self._responder = responder

    def query(self, prompt: str):
        if self._responder:
            return self._responder(prompt)
        return ""


def _make_translator(tmp_path, c_code: str, responder=None):
    cfile = tmp_path / "test.c"
    cfile.write_text(c_code)
    cfg = load_default_config()
    parser = CParser(str(cfile))
    tr = UnidiomaticTranslator(
        llm=_DummyLLM(responder),
        c2rust_translation="",
        c_parser=parser,
        test_cmd_path="tests/verifier/test_cmd.json",
        config=cfg,
        build_path=str(tmp_path / "build"),
        result_path=str(tmp_path / "result"),
        executable_object=None,
    )
    return parser, tr


def test_nonconst_global_with_initializer_is_defined(tmp_path, monkeypatch):
    c_code = "typedef struct { int a; int b; } StructX; StructX GLOBAL_X = { .a = 0, .b = 0 };"

    def responder(prompt: str):
        assert "extern \"C\"" not in prompt
        return (
            "----GLOBAL VAR----\n"
            "```rust\n"
            "#[repr(C)] pub struct StructX { pub a: i32, pub b: i32 }\n"
            "#[no_mangle] pub static mut GLOBAL_X: StructX = StructX { a: 0, b: 0 };\n"
            "```\n"
            "----END GLOBAL VAR----\n"
        )

    parser, tr = _make_translator(tmp_path, c_code, responder=responder)
    gv = SimpleNamespace(
        name="GLOBAL_X",
        is_const=False,
        is_array=False,
        array_size=None,
        enum_dependencies=[],
        enum_value_dependencies=[],
        get_decl=lambda: "StructX GLOBAL_X;",
    )
    monkeypatch.setattr(parser, "extract_global_var_definition_code", lambda name: c_code)

    res = tr._translate_global_vars_impl(gv)
    from sactor.translator.translator_types import TranslateResult
    assert res == TranslateResult.SUCCESS


def test_extern_decl_is_left_as_extern(tmp_path, monkeypatch):
    c_code = "typedef struct { int v; } MyS; extern MyS GLOBAL_Y;"

    def responder(prompt: str):
        assert "extern \"C\"" in prompt or "extern \"C\"" in prompt.replace("\n", " ")
        return (
            "----GLOBAL VAR----\n"
            "```rust\n"
            "#[repr(C)] pub struct MyS { pub v: i32 }\n"
            "extern \"C\" { pub static mut GLOBAL_Y: MyS; }\n"
            "```\n"
            "----END GLOBAL VAR----\n"
        )

    parser, tr = _make_translator(tmp_path, c_code, responder=responder)
    gv = SimpleNamespace(
        name="GLOBAL_Y",
        is_const=False,
        is_array=False,
        array_size=None,
        enum_dependencies=[],
        enum_value_dependencies=[],
        get_decl=lambda: "extern MyS GLOBAL_Y;",
    )
    monkeypatch.setattr(parser, "extract_global_var_definition_code", lambda name: "extern MyS GLOBAL_Y;")

    res = tr._translate_global_vars_impl(gv)
    from sactor.translator.translator_types import TranslateResult
    assert res == TranslateResult.SUCCESS
