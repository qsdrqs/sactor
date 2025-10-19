from types import SimpleNamespace

from sactor.c_parser.enum_info import EnumInfo, _sanitize_enum_name


def _make_cursor(
    spelling: str,
    *,
    file_path: str = "/tmp/example.c",
    line: int = 12,
    column: int = 3,
):
    file_obj = SimpleNamespace(name=file_path)
    location = SimpleNamespace(file=file_obj, line=line, column=column)
    return SimpleNamespace(spelling=spelling, location=location)


def test_sanitize_enum_name_preserves_valid_identifier():
    cursor = _make_cursor("ValidEnum")
    assert _sanitize_enum_name(cursor) == "ValidEnum"
    assert EnumInfo(cursor).name == "ValidEnum"


def test_sanitize_enum_name_for_anonymous_enum_uses_location():
    cursor = _make_cursor("", file_path="/path/to/foo-bar.h", line=42, column=7)
    assert _sanitize_enum_name(cursor) == "enum_foo_bar_42_7"
    assert EnumInfo(cursor).name == "enum_foo_bar_42_7"


def test_sanitize_enum_name_handles_leading_digits_and_spaces():
    cursor = _make_cursor("123 bad name")
    assert _sanitize_enum_name(cursor) == "enum_123_bad_name"
    assert EnumInfo(cursor).name == "enum_123_bad_name"


def test_sanitize_enum_name_falls_back_to_enum_unnamed():
    cursor = _make_cursor("!!!")
    assert _sanitize_enum_name(cursor) == "enum_unnamed"
    assert EnumInfo(cursor).name == "enum_unnamed"
