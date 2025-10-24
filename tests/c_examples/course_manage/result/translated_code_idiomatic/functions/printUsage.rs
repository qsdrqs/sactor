pub fn print_usage() {
    let usage_message = "Usage: ./program <student_name> <age> <course_name> <course_code> <grade1> [grade2] [grade3] ...\n";
    let example_message =
        "Example: ./program \"John Doe\" 20 \"Computer Science\" 101 85.5 92.0 88.5\n";
    println!("{}", usage_message);
    println!("{}", example_message);
}
