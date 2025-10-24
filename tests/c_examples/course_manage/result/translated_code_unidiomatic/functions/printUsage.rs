use libc::printf;
use std::ffi::CString;
pub unsafe fn printUsage() {
    let usage_message = CString::new(
            "Usage: ./program <student_name> <age> <course_name> <course_code> <grade1> [grade2] [grade3] ...\n",
        )
        .unwrap();
    let example_message = CString::new(
        "Example: ./program \"John Doe\" 20 \"Computer Science\" 101 85.5 92.0 88.5\n",
    )
    .unwrap();
    printf(usage_message.as_ptr());
    printf(example_message.as_ptr());
}
