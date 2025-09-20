pub fn printUsage() {
    unsafe {
        let msg1: *const libc::c_char = b"Usage: ./program <student_name> <age> <course_name> <course_code> <grade1> [grade2] [grade3] ...\n\0"
            .as_ptr() as *const libc::c_char;
        let msg2: *const libc::c_char =
            b"Example: ./program \"John Doe\" 20 \"Computer Science\" 101 85.5 92.0 88.5\n\0"
                .as_ptr() as *const libc::c_char;
        libc::printf(msg1);
        libc::printf(msg2);
    }
}
