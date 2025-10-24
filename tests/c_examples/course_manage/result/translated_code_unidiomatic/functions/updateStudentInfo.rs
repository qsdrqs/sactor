use libc::{c_char, c_int, free, malloc, printf, strcpy, strlen};
pub unsafe fn updateStudentInfo(student: *mut Student, newName: *const c_char, newAge: c_int) {
    if student.is_null() || newName.is_null() {
        printf(b"Invalid input parameters\n\0".as_ptr() as *const c_char);
        return;
    }
    if !(*student).name.is_null() {
        free((*student).name as *mut libc::c_void);
    }
    let name_length = strlen(newName) + 1;
    (*student).name = malloc(name_length) as *mut c_char;
    if !(*student).name.is_null() {
        strcpy((*student).name, newName);
    }
    (*student).age = newAge;
}
