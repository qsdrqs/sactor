pub fn main() -> () {
    use libc::{atof, atoi, free, malloc};
    use std::env;
    use std::ffi::{CStr, CString};
    use std::os::raw::{c_char, c_float, c_int};
    use std::ptr;
    let args: Vec<String> = env::args().collect();
    let argc = args.len();
    if argc < 6 {
        println!("Error: Insufficient arguments");
        unsafe {
            printUsage();
        }
        std::process::exit(1);
    }
    let student_name = CString::new(args[1].clone()).unwrap();
    let age = unsafe { atoi(args[2].as_ptr() as *const c_char) };
    let course_name = CString::new(args[3].clone()).unwrap();
    let course_code = unsafe { atoi(args[4].as_ptr() as *const c_char) };
    if age <= 0 || age > 120 {
        println!("Error: Invalid age (must be between 1 and 120)");
        std::process::exit(1);
    }
    if course_code <= 0 {
        println!("Error: Invalid course code");
        std::process::exit(1);
    }
    let num_grades = (argc - 5) as c_int;
    let grades =
        unsafe { malloc(num_grades as usize * std::mem::size_of::<c_float>()) as *mut c_float };
    for i in 0..num_grades {
        let grade = unsafe { atof(args[(i + 5) as usize].as_ptr() as *const c_char) as c_float };
        unsafe { *grades.add(i as usize) = grade };
        if grade < 0.0 || grade > 100.0 {
            println!(
                "Error: Invalid grade {:.6} (must be between 0 and 100)",
                grade
            );
            unsafe { free(grades as *mut libc::c_void) };
            std::process::exit(1);
        }
    }
    let course = Course {
        courseName: unsafe { malloc(course_name.to_bytes_with_nul().len()) as *mut c_char },
        courseCode: course_code,
    };
    unsafe {
        ptr::copy_nonoverlapping(
            course_name.as_ptr(),
            course.courseName,
            course_name.to_bytes_with_nul().len(),
        )
    };
    let mut student = Student {
        name: ptr::null_mut(),
        age: 0,
        enrolledCourse: &course as *const Course as *mut Course,
        grades,
        numGrades: num_grades,
    };
    unsafe {
        updateStudentInfo(&mut student, student_name.as_ptr(), age);
    }
    println!("\nStudent Information:");
    println!("------------------");
    println!("Name: {}", unsafe {
        CStr::from_ptr(student.name).to_string_lossy()
    });
    println!("Age: {}", student.age);
    println!(
        "Course: {} (Code: {})",
        unsafe { CStr::from_ptr(course.courseName).to_string_lossy() },
        course.courseCode
    );
    print!("Grades: ");
    for i in 0..student.numGrades {
        print!("{:.1} ", unsafe { *student.grades.add(i as usize) });
    }
    println!();
    if student.numGrades > 0 {
        let mut sum = 0.0;
        for i in 0..student.numGrades {
            sum += unsafe { *student.grades.add(i as usize) };
        }
        println!("Average Grade: {:.2}", sum / student.numGrades as f32);
    }
    unsafe {
        free(course.courseName as *mut libc::c_void);
        free(student.name as *mut libc::c_void);
        free(student.grades as *mut libc::c_void);
    }
}
