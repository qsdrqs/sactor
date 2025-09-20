pub extern "C" fn updateStudentInfo(student: *mut CStudent, newName: *const libc::c_char, newAge: libc::c_int)
{
    // Arg 'student': convert * mut CStudent to Student
    assert!(!student.is_null());
    let mut student_ref: &'static mut Student = unsafe { CStudent_to_Student_mut(student) };
    let student_val: Student = student_ref.clone();
    // Arg 'new_name': optional C string at newName
    let new_name_opt = if !newName.is_null() {
        Some(unsafe { std::ffi::CStr::from_ptr(newName) }.to_string_lossy().into_owned())
    } else {
        None
    };
    let __ret = updateStudentInfo_idiomatic(student_val, new_name_opt.as_deref(), newAge);
    if !student.is_null() {
        let mut __ret_clone = __ret.clone();
        let ret_ptr = unsafe { Student_to_CStudent_mut(&mut __ret_clone) };
        unsafe { *student = *ret_ptr; }
        unsafe { let _ = Box::from_raw(ret_ptr); }
    };
}
