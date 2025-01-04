use libc::{c_char, c_int, malloc, free, strlen, strcpy};
use std::ptr;
use std::ffi::CStr;
pub unsafe fn updateStudentInfo(
    student: *mut Student,
    newName: *const c_char,
    newAge: c_int,
) {
    if student.is_null() || newName.is_null() {
        println!("Invalid input parameters");
        return;
    }
    let student_ref = &mut *student;
    if !student_ref.name.is_null() {
        free(student_ref.name as *mut _);
    }
    let name_length = strlen(newName) + 1;
    student_ref.name = malloc(name_length) as *mut c_char;
    if !student_ref.name.is_null() {
        strcpy(student_ref.name, newName);
    }
    student_ref.age = newAge;
}
