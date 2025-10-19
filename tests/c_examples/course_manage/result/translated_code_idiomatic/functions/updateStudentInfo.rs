pub fn updateStudentInfo(student: &mut Student, new_name: Option<&str>, new_age: i32) {
    if let Some(name) = new_name {
        student.name = name.to_owned();
        student.age = new_age;
    } else {
        eprintln!("Invalid input parameters");
    }
}
