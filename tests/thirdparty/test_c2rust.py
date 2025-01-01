from sactor.thirdparty import C2Rust


def test_c2rust_translation():
    file_path = 'tests/c_examples/course_manage/course_manage.c'
    c2rust_instance = C2Rust(file_path)
    c2rust_content = c2rust_instance.get_c2rust_translation()
    with open('tests/c_examples/course_manage/course_manage_c2rust.rs') as f:
        comparison_content = f.read()
    assert c2rust_content == comparison_content
