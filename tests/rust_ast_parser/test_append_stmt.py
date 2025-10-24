import pytest

from sactor import rust_ast_parser


def test_append_stmt_to_function_appends_exit_and_normalizes_tail_expr():
    source = 'fn main() {\n    println!("hi")\n}\n'

    result = rust_ast_parser.append_stmt_to_function(
        source, "main", "libc::exit(0);"
    )

    assert 'println!("hi");' in result
    assert 'libc::exit(0);' in result
    assert result.count('libc::exit(0);') == 1

    lines = [line.strip() for line in result.splitlines() if line.strip()]
    assert lines[-2] == 'libc::exit(0);'
    assert lines[-1] == '}'


def test_append_stmt_to_function_is_idempotent():
    source = 'fn main() {\n    let value = 4;\n    value\n}\n'

    first = rust_ast_parser.append_stmt_to_function(
        source, "main", "libc::exit(0);"
    )
    second = rust_ast_parser.append_stmt_to_function(
        first, "main", "libc::exit(0);"
    )

    assert first == second


def test_append_stmt_to_function_missing_target_errors():
    with pytest.raises(ValueError):
        rust_ast_parser.append_stmt_to_function(
            "fn other() {}\n", "main", "libc::exit(0);"
        )
