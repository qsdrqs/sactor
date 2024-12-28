use libc::{c_char, c_float, c_int};
use std::ffi::{CStr, CString};
use std::ptr;
use std::process;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let argc = args.len();

    // Check minimum required arguments (program_name + 5 required args = 6)
    if argc < 6 {
        println!("Error: Insufficient arguments");
        unsafe { printUsage() };
        process::exit(1);
    }

    // Parse basic information
    let student_name = CString::new(args[1].clone()).unwrap();
    let age: c_int = args[2].parse().unwrap_or(0);
    let course_name = CString::new(args[3].clone()).unwrap();
    let course_code: c_int = args[4].parse().unwrap_or(0);

    // Validate age
    if age <= 0 || age > 120 {
        println!("Error: Invalid age (must be between 1 and 120)");
        process::exit(1);
    }

    // Validate course code
    if course_code <= 0 {
        println!("Error: Invalid course code");
        process::exit(1);
    }

    // Calculate number of grades provided
    let num_grades = (argc - 5) as c_int;
    let mut grades: Vec<c_float> = Vec::with_capacity(num_grades as usize);

    // Parse grades
    for i in 0..num_grades {
        let grade: c_float = args[(i + 5) as usize].parse().unwrap_or(0.0);
        // Validate grade
        if grade < 0.0 || grade > 100.0 {
            println!("Error: Invalid grade {:.6} (must be between 0 and 100)", grade);
            process::exit(1);
        }
        grades.push(grade);
    }

    // Create course
    let mut course = Course {
        courseName: unsafe { libc::malloc(course_name.to_bytes_with_nul().len()) as *mut c_char },
        courseCode: course_code,
    };
    unsafe {
        ptr::copy_nonoverlapping(
            course_name.as_ptr(),
            course.courseName,
            course_name.to_bytes_with_nul().len(),
        );
    }

    // Create student
    let mut student = Student {
        name: ptr::null_mut(),
        age: 0,
        enrolledCourse: &mut course,
        grades: grades.as_mut_ptr(),
        numGrades: num_grades,
    };

    // Update student information
    unsafe {
        updateStudentInfo(&mut student, student_name.as_ptr(), age);
    }

    // Print student information
    println!("\nStudent Information:");
    println!("------------------");
    unsafe {
        let student_name_str = CStr::from_ptr(student.name).to_string_lossy();
        println!("Name: {}", student_name_str);
    }
    println!("Age: {}", student.age);
    unsafe {
        let course_name_str = CStr::from_ptr(course.courseName).to_string_lossy();
        println!("Course: {} (Code: {})", course_name_str, course.courseCode);
    }

    print!("Grades: ");
    for i in 0..student.numGrades {
        print!("{:.1} ", grades[i as usize]);
    }
    println!();

    // Calculate and print average grade
    if student.numGrades > 0 {
        let sum: c_float = grades.iter().sum();
        println!("Average Grade: {:.2}", sum / student.numGrades as c_float);
    }

    // Free allocated memory
    unsafe {
        libc::free(course.courseName as *mut libc::c_void);
        libc::free(student.name as *mut libc::c_void);
    }
}
