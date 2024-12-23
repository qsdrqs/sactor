#[derive(Copy, Clone)]
#[repr(C)]
pub struct Course {
    pub courseName: *mut libc::c_char,
    pub courseCode: libc::c_int,
}
