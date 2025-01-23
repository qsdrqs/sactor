use libc::{c_int, printf};
pub unsafe fn printGrades(idx: c_int) {
    printf("Student grades:\n\0".as_ptr() as *const i8);
    printf(
        "Student %d: %d\n\0".as_ptr() as *const i8,
        idx,
        GRADES[(idx - 1) as usize],
    );
}
