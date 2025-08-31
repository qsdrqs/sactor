use libc::c_char;
use libc::c_float;
use libc::c_int;
use libc::free;
use libc::malloc;
use libc::printf;
use libc::strcpy;
use libc::strlen;
use std::ffi::CStr;
use std::ffi::CString;
use std::process;
use std::ptr;
#[derive(Copy, Clone, Debug)]
#[repr(C)]
pub struct Student {
    pub name: *mut libc::c_char,
    pub age: libc::c_int,
    pub enrolledCourse: *mut Course,
    pub grades: *mut libc::c_float,
    pub numGrades: libc::c_int,
}
#[derive(Copy, Clone, Debug)]
#[repr(C)]
pub struct Course {
    pub courseName: *mut libc::c_char,
    pub courseCode: libc::c_int,
}
unsafe fn printUsage() {
    printf (b"Usage: ./program <student_name> <age> <course_name> <course_code> <grade1> [grade2] [grade3] ...\n\0" . as_ptr () as * const i8) ;
    printf(
        b"Example: ./program \"John Doe\" 20 \"Computer Science\" 101 85.5 92.0 88.5\n\0".as_ptr()
            as *const i8,
    );
}
pub unsafe fn updateStudentInfo(student: *mut Student, newName: *const c_char, newAge: c_int) {
    if student.is_null() || newName.is_null() {
        println!("Invalid input parameters");
        return;
    }
    let student_ref = &mut *student;
    if !student_ref.name.is_null() {
        free(student_ref.name as *mut _);
    }
    let name_length = strlen(newName) + 1;
    student_ref.name = malloc(name_length) as *mut c_char;
    if !student_ref.name.is_null() {
        strcpy(student_ref.name, newName);
    }
    student_ref.age = newAge;
}
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let argc = args.len();
    if argc < 6 {
        println!("Error: Insufficient arguments");
        unsafe { printUsage() };
        process::exit(1);
    }
    let student_name = CString::new(args[1].clone()).unwrap();
    let age: c_int = args[2].parse().unwrap_or(0);
    let course_name = CString::new(args[3].clone()).unwrap();
    let course_code: c_int = args[4].parse().unwrap_or(0);
    if age <= 0 || age > 120 {
        println!("Error: Invalid age (must be between 1 and 120)");
        process::exit(1);
    }
    if course_code <= 0 {
        println!("Error: Invalid course code");
        process::exit(1);
    }
    let num_grades = (argc - 5) as c_int;
    let mut grades: Vec<c_float> = Vec::with_capacity(num_grades as usize);
    for i in 0..num_grades {
        let grade: c_float = args[(i + 5) as usize].parse().unwrap_or(0.0);
        if !(0.0..=100.0).contains(&grade) {
            println!(
                "Error: Invalid grade {:.6} (must be between 0 and 100)",
                grade
            );
            process::exit(1);
        }
        grades.push(grade);
    }
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
    let mut student = Student {
        name: ptr::null_mut(),
        age: 0,
        enrolledCourse: &mut course,
        grades: grades.as_mut_ptr(),
        numGrades: num_grades,
    };
    unsafe {
        updateStudentInfo(&mut student, student_name.as_ptr(), age);
    }
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
    if student.numGrades > 0 {
        let sum: c_float = grades.iter().sum();
        println!("Average Grade: {:.2}", sum / student.numGrades as c_float);
    }
    unsafe {
        libc::free(course.courseName as *mut libc::c_void);
        libc::free(student.name as *mut libc::c_void);
    }
}
