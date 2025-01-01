#[derive(Copy, Clone, Debug)]
#[repr(C)]
pub struct Student {
    pub name: *mut libc::c_char,
    pub age: libc::c_int,
    pub enrolledCourse: *mut Course,
    pub grades: *mut libc::c_float,
    pub numGrades: libc::c_int,
}
