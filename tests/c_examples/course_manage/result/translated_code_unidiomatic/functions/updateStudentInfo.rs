pub unsafe fn updateStudentInfo(
    student: *mut Student,
    newName: *const libc::c_char,
    newAge: libc::c_int,
) {
    if student.is_null() || newName.is_null() {
        let msg = b"Invalid input parameters\n\0";
        libc::printf(msg.as_ptr() as *const libc::c_char);
        return;
    }
    if !(*student).name.is_null() {
        libc::free((*student).name as *mut libc::c_void);
    }
    let size = libc::strlen(newName) + 1;
    (*student).name = libc::malloc(size) as *mut libc::c_char;
    libc::strcpy((*student).name, newName);
    (*student).age = newAge;
}
