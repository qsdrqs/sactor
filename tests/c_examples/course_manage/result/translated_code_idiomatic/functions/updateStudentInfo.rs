pub fn updateStudentInfo(student: &mut Student, newName: &str, newAge: i32) {
    if newName.is_empty() {
        println!("Invalid input parameters");
        return;
    }

    student.name = Some(newName.to_owned());
    student.age = newAge;
}
