from sactor.thirdparty import Crown, CrownType
import tempfile

def test_crown():
    file_c2rust_path = 'tests/c_examples/course_manage_c2rust.rs'
    with open(file_c2rust_path) as f:
        c2rust_code = f.read()
    with tempfile.TemporaryDirectory() as tmpdir:
        print(tmpdir)
        crown = Crown(tmpdir)
        crown.analyze(c2rust_code)
        result = crown.query('updateStudentInfo', CrownType.FUNCTION)
        assert result == {
            'student': {
                'fatness': ['Ptr'],
                'mutability': ['Mut'],
                'ownership': ['Owning'],
            },
            'newName': {
                'fatness': ['Arr'],
                'mutability': ['Mut'],
                'ownership': ['Transient'],
            },
        }

        result = crown.query('Student', CrownType.STRUCT)
        assert result == {
            'grades': {'fatness': ['Arr'], 'mutability': ['Mut'], 'ownership': ['Unknown']},
            'enrolledCourse': {'fatness': ['Ptr'], 'mutability': ['Imm'], 'ownership': ['Unknown']},
            'name': {'fatness': ['Arr'], 'mutability': ['Mut'], 'ownership': ['Unknown']},
        }
