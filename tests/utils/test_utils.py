import json
import os
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


def test_load_compile_commands_from_file_arguments(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    source = src_dir / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")

    compile_commands = [
        {
            "directory": str(src_dir),
            "file": str(source),
            "arguments": ["clang", "-I", "include", "-c", "main.c", "-o", "main.o"],
        }
    ]
    commands_path = tmp_path / "compile_commands.json"
    commands_path.write_text(json.dumps(compile_commands), encoding="utf-8")

    commands = utils.load_compile_commands_from_file(str(commands_path), str(source))
    assert len(commands) == 1
    command = commands[0]
    assert command[0] == "clang"
    assert utils.TO_TRANSLATE_C_FILE_MARKER in command
    assert command[-2:] == ["-Og", "-g"]


def test_load_compile_commands_from_file_command_field(tmp_path):
    src_dir = tmp_path / "project"
    src_dir.mkdir()
    source = src_dir / "entry.c"
    source.write_text("int x(void) { return 1; }\n", encoding="utf-8")

    compile_commands = [
        {
            "directory": str(src_dir),
            "file": str(source),
            "command": "clang -DMODE=1 -c entry.c -o entry.o",
        }
    ]
    commands_path = tmp_path / "compile_commands.json"
    commands_path.write_text(json.dumps(compile_commands), encoding="utf-8")

    commands = utils.load_compile_commands_from_file(str(commands_path), str(source))
    assert len(commands) == 1
    command = commands[0]
    assert "-DMODE=1" in command
    assert utils.TO_TRANSLATE_C_FILE_MARKER in command
    assert command[-2:] == ["-Og", "-g"]


def test_load_compile_commands_from_file_missing_entry(tmp_path):
    source = tmp_path / "missing.c"
    source.write_text("int q(void) { return 2; }\n", encoding="utf-8")
    compile_commands = [
        {
            "directory": str(tmp_path),
            "file": os.path.join(str(tmp_path), "other.c"),
            "arguments": ["clang", "-c", "other.c", "-o", "other.o"],
        }
    ]
    commands_path = tmp_path / "compile_commands.json"
    commands_path.write_text(json.dumps(compile_commands), encoding="utf-8")

    with pytest.raises(ValueError):
        utils.load_compile_commands_from_file(str(commands_path), str(source))


def test_list_c_files_from_compile_commands(tmp_path):
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()

    a_c = proj_dir / "a.c"
    b_c = proj_dir / "dir" / "b.c"
    b_c.parent.mkdir()
    a_c.write_text("int a(void){return 1;}\n", encoding="utf-8")
    b_c.write_text("int b(void){return 2;}\n", encoding="utf-8")

    compile_commands = [
        {
            "directory": str(proj_dir),
            "file": str(a_c),
            "arguments": ["clang", "-c", "a.c"],
        },
        {
            "directory": str(b_c.parent),
            "file": str(b_c),
            "command": "clang -c b.c",
        },
        {
            # Duplicate entry should be ignored
            "directory": str(proj_dir),
            "file": str(a_c),
            "arguments": ["clang", "-c", "a.c"],
        },
        {
            # Fallback style entry should be ignored
            "directory": str(proj_dir),
            "file": str(a_c),
            "arguments": ["clang", "-c", "--", str(a_c)],
        },
        {
            # Non C source should be ignored
            "directory": str(proj_dir),
            "file": str(proj_dir / "not_c.cpp"),
            "arguments": ["clang++", "-c", "not_c.cpp"],
        },
    ]

    commands_path = proj_dir / "compile_commands.json"
    commands_path.write_text(json.dumps(compile_commands), encoding="utf-8")

    files = utils.list_c_files_from_compile_commands(str(commands_path))
    assert sorted(files) == sorted([str(a_c.resolve()), str(b_c.resolve())])
