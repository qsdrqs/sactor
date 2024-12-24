use std::ffi::CStr;

pub fn updateStudentInfo(student: Option<&mut Student>, newName: Option<&CStr>, newAge: i32) {
    if let (Some(student_ref), Some(new_name_cstr)) = (student, newName) {
        // Update the name
        student_ref.name = new_name_cstr.to_bytes().to_vec();

        // Update the age
        student_ref.age = newAge;
    } else {
        println!("Invalid input parameters");
    }
}
