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
pub fn printUsage() {
    unsafe {
        let msg1 : * const libc :: c_char = b"Usage: ./program <student_name> <age> <course_name> <course_code> <grade1> [grade2] [grade3] ...\n\0" . as_ptr () as * const libc :: c_char ;
        let msg2: *const libc::c_char =
            b"Example: ./program \"John Doe\" 20 \"Computer Science\" 101 85.5 92.0 88.5\n\0"
                .as_ptr() as *const libc::c_char;
        libc::printf(msg1);
        libc::printf(msg2);
    }
}
pub unsafe fn updateStudentInfo(
    student: *mut Student,
    newName: *const libc::c_char,
    newAge: libc::c_int,
) {
    if student.is_null() || newName.is_null() {
        let msg = b"Invalid input parameters\n\0";
        libc::printf(msg.as_ptr() as *const libc::c_char);
        return;
    }
    if !(*student).name.is_null() {
        libc::free((*student).name as *mut libc::c_void);
    }
    let size = libc::strlen(newName) + 1;
    (*student).name = libc::malloc(size) as *mut libc::c_char;
    libc::strcpy((*student).name, newName);
    (*student).age = newAge;
}
pub fn main() {
    use std::env;
    use std::ffi::CString;
    let args: Vec<String> = env::args().collect();
    let argc = args.len() as libc::c_int;
    if argc < 6 {
        unsafe {
            libc::printf(b"Error: Insufficient arguments\n\0".as_ptr() as *const libc::c_char);
            printUsage();
        }
        std::process::exit(1);
    }
    let c_student_name =
        CString::new(args[1].as_str()).unwrap_or_else(|_| CString::new("").unwrap());
    let c_age = CString::new(args[2].as_str()).unwrap_or_else(|_| CString::new("").unwrap());
    let c_course_name_in =
        CString::new(args[3].as_str()).unwrap_or_else(|_| CString::new("").unwrap());
    let c_course_code =
        CString::new(args[4].as_str()).unwrap_or_else(|_| CString::new("").unwrap());
    let age: libc::c_int = unsafe { libc::atoi(c_age.as_ptr()) };
    if age <= 0 || age > 120 {
        unsafe {
            libc::printf(
                b"Error: Invalid age (must be between 1 and 120)\n\0".as_ptr()
                    as *const libc::c_char,
            );
        }
        std::process::exit(1);
    }
    let course_code: libc::c_int = unsafe { libc::atoi(c_course_code.as_ptr()) };
    if course_code <= 0 {
        unsafe {
            libc::printf(b"Error: Invalid course code\n\0".as_ptr() as *const libc::c_char);
        }
        std::process::exit(1);
    }
    let num_grades: libc::c_int = argc - 5;
    let num_grades_usize = num_grades as usize;
    let grades: *mut libc::c_float = unsafe {
        libc::malloc(num_grades_usize * std::mem::size_of::<libc::c_float>()) as *mut libc::c_float
    };
    for i in 0..num_grades_usize {
        let c_grade =
            CString::new(args[i + 5].as_str()).unwrap_or_else(|_| CString::new("").unwrap());
        let g = unsafe { libc::atof(c_grade.as_ptr()) } as f32;
        unsafe {
            *grades.add(i) = g as libc::c_float;
        }
        if !(0.0..=100.0).contains(&g) {
            unsafe {
                libc::printf(
                    b"Error: Invalid grade %f (must be between 0 and 100)\n\0".as_ptr()
                        as *const libc::c_char,
                    g as f64,
                );
                libc::free(grades as *mut _);
            }
            std::process::exit(1);
        }
    }
    let mut course = Course {
        courseName: std::ptr::null_mut(),
        courseCode: course_code,
    };
    unsafe {
        let len = c_course_name_in.as_bytes().len();
        let buf = libc::malloc(len + 1) as *mut libc::c_char;
        if !buf.is_null() {
            libc::strcpy(buf, c_course_name_in.as_ptr());
        }
        course.courseName = buf;
    }
    let mut student = Student {
        name: std::ptr::null_mut(),
        age: 0,
        enrolledCourse: &mut course as *mut Course,
        grades,
        numGrades: num_grades,
    };
    unsafe {
        updateStudentInfo(&mut student as *mut Student, c_student_name.as_ptr(), age);
    }
    unsafe {
        libc::printf(b"\nStudent Information:\n\0".as_ptr() as *const libc::c_char);
        libc::printf(b"------------------\n\0".as_ptr() as *const libc::c_char);
        libc::printf(
            b"Name: %s\n\0".as_ptr() as *const libc::c_char,
            student.name as *const libc::c_char,
        );
        libc::printf(b"Age: %d\n\0".as_ptr() as *const libc::c_char, student.age);
        libc::printf(
            b"Course: %s (Code: %d)\n\0".as_ptr() as *const libc::c_char,
            (*student.enrolledCourse).courseName as *const libc::c_char,
            (*student.enrolledCourse).courseCode,
        );
        libc::printf(b"Grades: \0".as_ptr() as *const libc::c_char);
        for i in 0..(student.numGrades as usize) {
            let val = *student.grades.add(i) as f32;
            libc::printf(b"%.1f \0".as_ptr() as *const libc::c_char, val as f64);
        }
        libc::printf(b"\n\0".as_ptr() as *const libc::c_char);
        if student.numGrades > 0 {
            let mut sum: f32 = 0.0;
            for i in 0..(student.numGrades as usize) {
                sum += *student.grades.add(i) as f32;
            }
            libc::printf(
                b"Average Grade: %.2f\n\0".as_ptr() as *const libc::c_char,
                (sum / (student.numGrades as f32)) as f64,
            );
        }
    }
    unsafe {
        libc::free(course.courseName as *mut _);
        libc::free(student.name as *mut _);
        libc::free(student.grades as *mut _);
    }
}
