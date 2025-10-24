pub fn update_student_info(student: &mut Student, new_name: Option<&str>, new_age: i32) {
    if let Some(name) = new_name {
        student.name = name.to_string();
    } else {
        eprintln!("Invalid input parameters");
        return;
    }
    student.age = new_age;
}
