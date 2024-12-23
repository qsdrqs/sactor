from sactor.thirdparty import c2rust


def test_c2rust_translation():
    file_path = 'tests/c_examples/course_manage.c'
    c2rust_content = c2rust.get_c2rust_translation(file_path)
    with open('tests/c_examples/course_manage_c2rust.rs') as f:
        comparison_content = f.read()
    assert c2rust_content == comparison_content
