from sactor import utils
from sactor.data_types import DataType


def test_merge_configs():
    config = {
        "a": {
            "b": 1,
        },
    }
    default_config = {
        "a": {
            "b": 2,
            "c": 3,
        },
        "d": 4,
    }
    assert utils._merge_configs(config, default_config) == {
        "a": {
            "b": 1,
            "c": 3,
        },
        "d": 4,
    }


def test_load_config():
    mock_config_path = "tests/utils/sactor.mock.toml"
    config = utils.try_load_config(mock_config_path)
    assert config['general']['llm'] == "AzureOpenAI"
    assert config['general']['max_translation_attempts'] == 3
    assert config['AzureOpenAI']['api_key'] == "your-api-key"
    assert config['OpenAI']['api_key'] == 'mock-api-key'

def test_rename_signature():
    signature = "fn foo(a: i32, b: i32) -> i32;"
    renamed_signature = "fn bar(a: i32, b: i32) -> i32;"
    assert utils.rename_rust_function_signature(
        signature,
        "foo",
        "bar",
        DataType.FUNCTION
    ) == renamed_signature

    signature = "fn changeStudentName(student: Student, name: String) -> Student;"
    renamed_signature = "fn changeStudentName(student: CStudent, name: String) -> CStudent;"

    assert utils.rename_rust_function_signature(
        signature,
        "Student",
        "CStudent",
        DataType.STRUCT
    ) == renamed_signature


def test_load_text_with_mappings_and_b2s_s2b(tmp_path):
    text = "a中文😊ωb\n"
    p = tmp_path / "u.txt"
    p.write_text(text, encoding="utf-8")
    s, b, b2s, s2b = utils.load_text_with_mappings(str(p))
    assert s == text
    assert s2b[len(s)] == len(b)
    assert b2s[len(b)] == len(s)
    for i in range(len(s)):
        boff = s2b[i]
        assert utils.byte_to_str_index(b2s, boff) == i
    idx_zh = s.index("中")
    sb = s2b[idx_zh]
    se = s2b[idx_zh + 1]
    for j in range(sb, se):
        assert utils.byte_to_str_index(b2s, j) == idx_zh


def test_scan_ws_semicolon_bytes_with_unicode_prefix():
    prefix = "中文😊"
    data = (prefix + "  ;x").encode("utf-8")
    pos = len(prefix.encode("utf-8"))
    assert utils.scan_ws_semicolon_bytes(data, pos) == pos + 3
