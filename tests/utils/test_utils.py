import subprocess
import sys

import pytest

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
    assert config['general']['max_translation_attempts'] == 3
    assert config['general']['model'] == 'gpt-4o'
    assert config['general']['command_output_byte_limit'] == 40000
    assert 'litellm' in config and 'model_list' in config['litellm']

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

def test_parse_llm_result_accepts_tags():
    raw = """
----ARG----
content
----END ARG----
"""
    result = utils.parse_llm_result(raw, "arg")
    assert result["arg"] == "content\n"

def test_parse_llm_result_accepts_flexible_tags():
    raw = """
 --Function--
pub fn foo() {}
--END Function--
"""
    result = utils.parse_llm_result(raw, "function")
    assert result["function"] == "pub fn foo() {}\n"


def test_parse_llm_result_skips_code_fences_and_multiple_blocks():
    raw = """
----Function----
```rust
pub fn foo() {}
```
----END FUNCTION
----ENUM----
pub enum Foo { Bar }
----END ENUM----
"""
    result = utils.parse_llm_result(raw, "function", "enum")
    assert result["function"] == "pub fn foo() {}\n"
    assert result["enum"] == "pub enum Foo { Bar }\n"


def test_parse_llm_result_accepts_start_tag_without_trailing_dashes():
    raw = """
----FUNCTION
pub fn foo() {}
----END FUNCTION
"""
    result = utils.parse_llm_result(raw, "function")
    assert result["function"] == "pub fn foo() {}\n"

def test_parse_llm_result_errors_on_missing_content():
    raw = """
----Function----
```rust
```
----END FUNCTION----
"""
    with pytest.raises(ValueError):
        utils.parse_llm_result(raw, "function")


def test_parse_llm_result_errors_on_missing_end_tag():
    raw = """
----Function----
pub fn foo() {}
"""
    with pytest.raises(ValueError):
        utils.parse_llm_result(raw, "function")


def test_run_command_limit_success():
    result = utils.run_command(
        [sys.executable, "-c", "print('ok')"],
        limit_bytes=1024,
    )
    assert result.stdout.startswith("ok")
    assert result.returncode == 0


def test_run_command_limit_enforces_truncation():
    script = """
import sys
import time
sys.stdout.write('x' * 50000)
sys.stdout.flush()
time.sleep(5)
"""
    result = utils.run_command(
        [sys.executable, "-c", script],
        limit_bytes=1024,
    )
    assert len(result.stdout) == 1024
    assert result.returncode is not None and result.returncode != 0


def test_run_command_limit_timeout():
    with pytest.raises(TimeoutError):
        utils.run_command(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            limit_bytes=1024,
            timeout=0.2,
        )


def test_run_command_check_raises():
    with pytest.raises(subprocess.CalledProcessError):
        utils.run_command(
            [sys.executable, "-c", "import sys; sys.exit(3)"],
            check=True,
        )


def test_run_command_limit_requires_capture_output():
    with pytest.raises(ValueError):
        utils.run_command(
            [sys.executable, "-c", "print('hi')"],
            limit_bytes=128,
            capture_output=False,
        )
