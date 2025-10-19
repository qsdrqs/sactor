import json
import textwrap
from pathlib import Path

from sactor.verifier.spec.harness_codegen import (
    _render_len_expression,
    generate_struct_harness_from_spec_file,
    generate_function_harness_from_spec_file,
)


def write_json(p: Path, obj: dict) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2))
    return p


def test_generate_struct_harness_basic(tmp_path: Path):
    # Struct: A { num: u32, name: *const c_char, data: *mut u8, data_len: usize }
    # Idiomatic: A { num: u32, name: String, data: Vec<u8> }
    spec = {
        "struct_name": "A",
        "fields": [
            {
                "u_field": {"name": "num", "type": "u32", "shape": "scalar"},
                "i_field": {"name": "num", "type": "u32"},
            },
            {
                "u_field": {
                    "name": "name",
                    "type": "*const c_char",
                    "shape": {"ptr": {"kind": "cstring"}},
                },
                "i_field": {"name": "name", "type": "String"},
            },
            {
                "u_field": {
                    "name": "data",
                    "type": "*mut u8",
                    "shape": {"ptr": {"kind": "slice", "len_from": "data_len"}},
                },
                "i_field": {"name": "data", "type": "Vec<u8>"},
            },
            {
                "u_field": {"name": "data_len", "type": "usize", "shape": "scalar"},
                "i_field": {"name": "data.len", "type": "usize"},
            },
        ],
    }
    spec_path = write_json(tmp_path / "spec.json", spec)

    # Minimal code strings that allow field type discovery for unidiomatic struct
    unidiomatic_struct_code = """#[repr(C)]
pub struct CA {
    pub num: u32,
    pub name: *const libc::c_char,
    pub data: *mut u8,
    pub data_len: usize,
}
"""
    idiomatic_struct_code = """pub struct A {
    pub num: u32,
    pub name: String,
    pub data: Vec<u8>,
}
"""

    code = generate_struct_harness_from_spec_file(
        "A", idiomatic_struct_code, unidiomatic_struct_code, str(spec_path)
    )
    assert code is not None
    expected = textwrap.dedent(
        """\
        use core::ptr;
        use std::ffi;
        unsafe fn CA_to_A_mut(input: *mut CA) -> &'static mut A {
            assert!(!input.is_null());
            let c = &*input;
            let r = A {
                    // Field 'num' -> 'num' (C -> idiomatic)
                    num: c.num as u32,
                    // Field 'name' -> 'name' (C -> idiomatic)
                    name: if !c.name.is_null() {
                        unsafe { std::ffi::CStr::from_ptr(c.name) }.to_string_lossy().into_owned()
                    } else {
                        String::new()
                    },
                    // Field 'data' -> 'data' (C -> idiomatic)
                    data: if !c.data.is_null() && (c.data_len as usize) > 0 {
                        unsafe { std::slice::from_raw_parts(c.data as *const u8, (c.data_len as usize)) }.to_vec()
                    } else {
                        Vec::<u8>::new()
                    },
                    // Field 'data_len' -> 'data.len' (C -> idiomatic)
                    // Derived field 'data.len' computed via slice metadata
            };
            Box::leak(Box::new(r))
        }
        unsafe fn A_to_CA_mut(r: &mut A) -> *mut CA {
            // Field 'num' -> 'num' (idiomatic -> C)
            let _num = r.num;
            // Field 'name' -> 'name' (idiomatic -> C)
            let _name_ptr: *mut libc::c_char = {
                let s = std::ffi::CString::new(r.name.clone())
                    .unwrap_or_else(|_| std::ffi::CString::new("").unwrap());
                s.into_raw()
            };
            // Field 'data' -> 'data' (idiomatic -> C)
            let _data_ptr: *mut u8 = if r.data.is_empty() {
                core::ptr::null_mut()
            } else {
                let mut boxed = r.data.clone().into_boxed_slice();
                let ptr = boxed.as_mut_ptr();
                core::mem::forget(boxed);
                ptr
            };
            let _data_len: usize = (r.data.len() as usize) as usize;
            let c = CA {
                num: _num,
                name: _name_ptr,
                data: _data_ptr,
                data_len: _data_len,
            };
            Box::into_raw(Box::new(c))
        }
        """
    ).strip("\n")
    assert code == expected


def test_generate_struct_harness_with_struct_pointer(tmp_path: Path):
    spec = {
        "struct_name": "Student",
        "fields": [
            {
                "u_field": {
                    "name": "name",
                    "type": "*mut libc::c_char",
                    "shape": {"ptr": {"kind": "cstring", "null": "nullable"}},
                },
                "i_field": {"name": "name", "type": "Option<String>"},
            },
            {
                "u_field": {"name": "age", "type": "libc::c_int", "shape": "scalar"},
                "i_field": {"name": "age", "type": "i32"},
            },
            {
                "u_field": {
                    "name": "enrolledCourse",
                    "type": "*mut CCourse",
                    "shape": {"ptr": {"kind": "ref", "null": "nullable"}},
                },
                "i_field": {"name": "enrolled_course", "type": "Option<Course>"},
            },
            {
                "u_field": {
                    "name": "grades",
                    "type": "*mut libc::c_float",
                    "shape": {"ptr": {"kind": "slice", "len_from": "numGrades"}},
                },
                "i_field": {"name": "grades", "type": "Vec<f32>"},
            },
            {
                "u_field": {
                    "name": "numGrades",
                    "type": "libc::c_int",
                    "shape": "scalar",
                },
                "i_field": {"name": "grades.len", "type": "usize"},
            },
        ],
    }
    spec_path = write_json(tmp_path / "student_spec.json", spec)

    fixtures_dir = Path(__file__).parent
    unidiomatic_struct_code = (fixtures_dir / "student_c.rs").read_text()
    idiomatic_struct_code = (fixtures_dir / "student_idiomatic.rs").read_text()

    code = generate_struct_harness_from_spec_file(
        "Student",
        idiomatic_struct_code,
        unidiomatic_struct_code,
        str(spec_path),
    )
    assert code is not None
    expected = (fixtures_dir / "student_harness.rs").read_text().strip("\n")
    assert code == expected


def test_generate_struct_harness_todo_skeleton(tmp_path: Path):
    spec = {
        "struct_name": "A",
        "fields": [
            {
                "u_field": {"name": "value", "type": "i32", "shape": "scalar"},
                "i_field": {"name": "details.value", "type": "i32"},
            }
        ],
    }
    spec_path = write_json(tmp_path / "todo_spec.json", spec)

    unidiomatic_struct_code = """#[repr(C)]
pub struct CA {
    pub value: i32,
}
"""
    idiomatic_struct_code = """pub struct A { pub value: i32 }
"""

    code = generate_struct_harness_from_spec_file(
        "A", idiomatic_struct_code, unidiomatic_struct_code, str(spec_path)
    )
    expected = textwrap.dedent(
        """\
        // TODO: Spec exceeds automatic rules. Items to handle manually:
        // TODO: nested field path not supported: u=value i=details.value
        unsafe fn A_to_CA_mut(input: &mut A) -> *mut CA {
            // TODO: implement I->U conversion based on above items
            unimplemented!()
        }

        unsafe fn CA_to_A_mut(input: *mut CA) -> &'static mut A {
            // TODO: implement U->I conversion based on above items
            unimplemented!()
        }
        """
    )
    assert code == expected


def test_generate_function_harness_basic(tmp_path: Path):
    # Function: process(name: &str, data: &[u8]) -> i32
    # C: process(name: *const c_char, data: *const u8, data_len: usize) -> i32
    spec = {
        "function_name": "process",
        "fields": [
            {
                "u_field": {"name": "name", "type": "*const c_char", "shape": {"ptr": {"kind": "cstring"}}},
                "i_field": {"name": "name", "type": "&str"},
            },
            {
                "u_field": {"name": "data", "type": "*const u8", "shape": {"ptr": {"kind": "slice", "len_from": "data_len"}}},
                "i_field": {"name": "data", "type": "&[u8]"},
            },
        ],
    }
    spec_path = write_json(tmp_path / "func_spec.json", spec)

    idiomatic_sig = "pub fn process_idiomatic(name: &str, data: &[u8]) -> i32;"
    c_sig = (
        "pub unsafe extern \"C\" fn process("
        "name: *const libc::c_char, data: *const u8, data_len: usize"
        ") -> i32;"
    )

    code = generate_function_harness_from_spec_file(
        "process", idiomatic_sig, c_sig, [], str(spec_path)
    )
    assert code is not None
    expected = textwrap.dedent(
        """\
        pub unsafe extern \"C\" fn process(name: *const libc::c_char, data: *const u8, data_len: usize) -> i32
        {
            // Arg 'name': borrowed C string at name
            let name_str = if !name.is_null() {
                unsafe { std::ffi::CStr::from_ptr(name) }.to_string_lossy().into_owned()
            } else {
                String::new()
            };
            // Arg 'data': slice from data with len data_len as usize
            let data: &[u8] = unsafe { std::slice::from_raw_parts(data as *const u8, data_len as usize) };
            let __ret = process_idiomatic(&name_str, data);
            return __ret;
        }
        """
    ).strip("\n")
    assert code == expected


def test_generate_function_harness_struct_param(tmp_path: Path):
    spec = {
        "function_name": "updateStudentInfo",
        "fields": [
            {
                "u_field": {
                    "name": "student",
                    "type": "*mut CStudent",
                    "shape": {"ptr": {"kind": "ref", "null": "forbidden"}},
                },
                "i_field": {"name": "student", "type": "Student"},
            },
            {
                "u_field": {
                    "name": "newName",
                    "type": "*const libc::c_char",
                    "shape": {"ptr": {"kind": "cstring", "null": "nullable"}},
                },
                "i_field": {"name": "new_name", "type": "Option<&str>"},
            },
            {
                "u_field": {"name": "newAge", "type": "libc::c_int", "shape": "scalar"},
                "i_field": {"name": "new_age", "type": "i32"},
            },
            {
                "u_field": {
                    "name": "student",
                    "type": "*mut CStudent",
                    "shape": {"ptr": {"kind": "ref", "null": "forbidden"}},
                },
                "i_field": {"name": "ret", "type": "Student"},
            },
        ],
    }
    spec_path = write_json(tmp_path / "update_student_spec.json", spec)

    idiomatic_sig = (
        "fn updateStudentInfo_idiomatic("
        "student: Student, new_name: Option<&str>, new_age: i32"
        ") -> Student;"
    )
    c_sig = (
        "pub extern \"C\" fn updateStudentInfo("
        "student: *mut CStudent, newName: *const libc::c_char, newAge: libc::c_int"
        ");"
    )

    code = generate_function_harness_from_spec_file(
        "updateStudentInfo",
        idiomatic_sig,
        c_sig,
        ["Student"],
        str(spec_path),
    )
    assert code is not None
    expected = (Path(__file__).parent / "update_student_harness.rs").read_text().strip("\n")
    assert code == expected


def test_generate_function_harness_return_cstring(tmp_path: Path):
    spec = {
        "function_name": "create_message",
        "fields": [
            {
                "u_field": {
                    "name": "out",
                    "type": "*mut *mut libc::c_char",
                    "shape": {"ptr": {"kind": "cstring"}},
                },
                "i_field": {"name": "ret", "type": "String"},
            }
        ],
    }
    spec_path = write_json(tmp_path / "return_spec.json", spec)

    idiomatic_sig = "pub fn create_message_idiomatic() -> String;"
    c_sig = "pub unsafe extern \"C\" fn create_message(out: *mut *mut libc::c_char);"

    code = generate_function_harness_from_spec_file(
        "create_message", idiomatic_sig, c_sig, [], str(spec_path)
    )
    expected = textwrap.dedent(
        """\
        pub unsafe extern \"C\" fn create_message(out: *mut *mut libc::c_char)
        {
            let __ret = create_message_idiomatic();
            let __ret_cstr: *mut libc::c_char = {
                let s = std::ffi::CString::new(__ret)
                    .unwrap_or_else(|_| std::ffi::CString::new("").unwrap());
                s.into_raw()
            };
            if !out.is_null() {
                unsafe { *out = __ret_cstr; }
            };
        }
        """
    ).strip("\n")
    assert code == expected


def test_generate_function_harness_mut_struct_param(tmp_path: Path):
    spec = {
        "function_name": "process_student",
        "fields": [
            {
                "u_field": {
                    "name": "student",
                    "type": "*mut CStudent",
                    "shape": {"ptr": {"kind": "ref", "null": "forbidden"}},
                },
                "i_field": {"name": "student", "type": "&mut Student"},
            }
        ],
    }
    spec_path = write_json(tmp_path / "mut_spec.json", spec)

    idiomatic_sig = "pub fn process_student_idiomatic(student: &mut Student);"
    c_sig = "pub unsafe extern \"C\" fn process_student(student: *mut CStudent);"

    code = generate_function_harness_from_spec_file(
        "process_student", idiomatic_sig, c_sig, ["Student"], str(spec_path)
    )
    expected = textwrap.dedent(
        """\
        pub unsafe extern \"C\" fn process_student(student: *mut CStudent)
        {
            // Arg 'student': convert *mut Student to &mut Student
            let mut student: &'static mut Student = unsafe { CStudent_to_Student_mut(student) };
            // will copy back after call for student
            process_student_idiomatic(student);
            if !student.is_null() {
                let __c_student = unsafe { Student_to_CStudent_mut(student) };
                unsafe { *student = *__c_student; }
                unsafe { let _ = Box::from_raw(__c_student); }
            }
        }
        """
    ).strip("\n")
    assert code == expected


def test_generate_function_harness_option_mut_struct_param(tmp_path: Path):
    spec = {
        "function_name": "opt_student",
        "fields": [
            {
                "u_field": {
                    "name": "student",
                    "type": "*mut CStudent",
                    "shape": {"ptr": {"kind": "ref", "null": "nullable"}},
                },
                "i_field": {"name": "student", "type": "Option<&mut Student>"},
            }
        ],
    }
    spec_path = write_json(tmp_path / "opt_mut_spec.json", spec)

    idiomatic_sig = "pub fn opt_student_idiomatic(student: Option<&mut Student>);"
    c_sig = "pub unsafe extern \"C\" fn opt_student(student: *mut CStudent);"

    code = generate_function_harness_from_spec_file(
        "opt_student", idiomatic_sig, c_sig, ["Student"], str(spec_path)
    )
    expected = textwrap.dedent(
        """\
        pub unsafe extern \"C\" fn opt_student(student: *mut CStudent)
        {
            // Arg 'student': optional *mut Student to Option<&mut Student>
            let mut student_storage: Option<&'static mut Student> = if !student.is_null() {
                Some(unsafe { CStudent_to_Student_mut(student) })
            } else {
                None
            };
            opt_student_idiomatic(student_storage.as_deref_mut());
            if !student.is_null() {
                if let Some(inner) = student_storage.as_deref_mut() {
                    let __c_student = unsafe { Student_to_CStudent_mut(inner) };
                    unsafe { *student = *__c_student; }
                    unsafe { let _ = Box::from_raw(__c_student); }
                }
            }
        }
        """
    ).strip("\n")
    assert code == expected


def test_generate_function_harness_mut_scalar_param(tmp_path: Path):
    spec = {
        "function_name": "bump",
        "fields": [
            {
                "u_field": {
                    "name": "value",
                    "type": "*mut i32",
                    "shape": {"ptr": {"kind": "ref", "null": "forbidden"}},
                },
                "i_field": {"name": "value", "type": "&mut i32"},
            }
        ],
    }
    spec_path = write_json(tmp_path / "mut_scalar_spec.json", spec)

    idiomatic_sig = "pub fn bump_idiomatic(value: &mut i32);"
    c_sig = "pub unsafe extern \"C\" fn bump(value: *mut i32);"

    code = generate_function_harness_from_spec_file(
        "bump", idiomatic_sig, c_sig, [], str(spec_path)
    )
    expected = textwrap.dedent(
        """\
        pub unsafe extern \"C\" fn bump(value: *mut i32)
        {
            // Arg 'value': convert *mut i32 to &mut i32
            assert!(!value.is_null());
            let value_ref: &'static mut i32 = unsafe { &mut *value };
            bump_idiomatic(value_ref);
        }
        """
    ).strip("\n")
    assert code == expected


def test_generate_function_harness_todo_fallback(tmp_path: Path):
    # Unsupported param type triggers TODO skeleton generation
    spec = {
        "function_name": "weird",
        "fields": [
            {
                "u_field": {"name": "p", "type": "*const c_char", "shape": {"ptr": {"kind": "cstring"}}},
                "i_field": {"name": "p", "type": "HashMap<String, String>"},
            }
        ],
    }
    spec_path = write_json(tmp_path / "todo_func_spec.json", spec)

    idiomatic_sig = "pub fn weird_idiomatic(p: HashMap<String, String>) -> i32;"
    c_sig = "pub unsafe extern \"C\" fn weird(p: *const libc::c_char) -> i32;"

    code = generate_function_harness_from_spec_file(
        "weird", idiomatic_sig, c_sig, [], str(spec_path)
    )
    assert code is not None
    expected = textwrap.dedent(
        """\
        pub unsafe extern \"C\" fn weird(p: *const libc::c_char) -> i32
        {
            // TODO: param p of type HashMap < String , String >: unsupported mapping
            let __ret = weird_idiomatic(/* TODO param p */);
            return __ret;
        }
        """
    ).strip("\n")
    assert code == expected

def test_render_len_expression_supports_composite_product():
    field_types = {"rows": "usize", "cols": "usize"}
    rendered = _render_len_expression("rows * cols", field_types, "c.")
    assert rendered == "((c.rows as usize) * (c.cols as usize))"


def test_render_len_expression_returns_none_with_unknown_identifier():
    field_types = {"rows": "usize"}
    rendered = _render_len_expression("rows * missing", field_types, "c.")
    assert rendered is None


def test_generate_struct_harness_with_len_expression(tmp_path: Path):
    spec = {
        "struct_name": "Matrix",
        "fields": [
            {
                "u_field": {"name": "n_rows", "type": "usize", "shape": "scalar"},
                "i_field": {"name": "n_rows", "type": "usize"},
            },
            {
                "u_field": {"name": "n_cols", "type": "usize", "shape": "scalar"},
                "i_field": {"name": "n_cols", "type": "usize"},
            },
            {
                "u_field": {
                    "name": "vals",
                    "type": "*mut f64",
                    "shape": {"ptr": {"kind": "slice", "len_from": "n_rows * n_cols"}},
                },
                "i_field": {"name": "vals", "type": "Vec<f64>"},
            },
        ],
    }
    spec_path = write_json(tmp_path / "matrix_spec.json", spec)

    unidiomatic_struct_code = """#[repr(C)]
pub struct CMatrix {
    pub n_rows: usize,
    pub n_cols: usize,
    pub vals: *mut f64,
}
"""
    idiomatic_struct_code = """pub struct Matrix {
    pub n_rows: usize,
    pub n_cols: usize,
    pub vals: Vec<f64>,
}
"""

    code = generate_struct_harness_from_spec_file(
        "Matrix",
        idiomatic_struct_code,
        unidiomatic_struct_code,
        str(spec_path),
    )

    assert code is not None
    assert "TODO: unsupported len_from expression" not in code
    assert "((c.n_rows as usize) * (c.n_cols as usize))" in code
