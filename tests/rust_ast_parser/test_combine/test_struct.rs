#[derive(Copy, Clone)]
#[repr(C)]
pub struct Student {
    pub name: *mut libc::c_char,
    pub age: libc::c_int,
    pub enrolledCourse: *mut Course,
    pub grades: *mut libc::c_float,
    pub numGrades: libc::c_int,
}
#[derive(Copy, Clone)]
#[repr(C)]
pub struct Course {
    pub courseName: *mut libc::c_char,
    pub courseCode: libc::c_int,
}
