use libc::printf;

unsafe fn printUsage() {
    printf(b"Usage: ./program <student_name> <age> <course_name> <course_code> <grade1> [grade2] [grade3] ...\n\0".as_ptr() as *const i8);
    printf(b"Example: ./program \"John Doe\" 20 \"Computer Science\" 101 85.5 92.0 88.5\n\0".as_ptr() as *const i8);
}
