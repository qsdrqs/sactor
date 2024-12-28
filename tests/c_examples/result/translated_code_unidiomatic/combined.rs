use libc::atof;
use libc::atoi;
use libc::c_char;
use libc::c_double;
use libc::c_float;
use libc::c_int;
use libc::free;
use libc::malloc;
use libc::printf;
use libc::strcpy;
use libc::strlen;
use std::ffi::CStr;
use std::ptr;
#[derive(Copy, Clone)]
#[repr(C)]
pub struct Course {
    pub courseName: *mut libc::c_char,
    pub courseCode: libc::c_int,
}
#[derive(Copy, Clone)]
#[repr(C)]
pub struct Student {
    pub name: *mut libc::c_char,
    pub age: libc::c_int,
    pub enrolledCourse: *mut Course,
    pub grades: *mut libc::c_float,
    pub numGrades: libc::c_int,
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
fn main(argc: c_int, argv: *const *mut c_char) -> c_int {
    unsafe {
        if argc < 6 {
            printf(b"Error: Insufficient arguments\n\0".as_ptr() as *const c_char);
            printUsage();
            return 1;
        }
        let studentName: *const c_char = *argv.offset(1);
        let age: c_int = atoi(*argv.offset(2));
        let courseName: *const c_char = *argv.offset(3);
        let courseCode: c_int = atoi(*argv.offset(4));
        if age <= 0 || age > 120 {
            printf(b"Error: Invalid age (must be between 1 and 120)\n\0".as_ptr() as *const c_char);
            return 1;
        }
        if courseCode <= 0 {
            printf(b"Error: Invalid course code\n\0".as_ptr() as *const c_char);
            return 1;
        }
        let numGrades: c_int = argc - 5;
        let grades: *mut c_float =
            malloc(numGrades as usize * std::mem::size_of::<c_float>()) as *mut c_float;
        for i in 0..numGrades {
            let grade = atof(*argv.offset(i as isize + 5)) as c_float;
            *grades.offset(i as isize) = grade;
            if grade < 0.0 || grade > 100.0 {
                printf(
                    b"Error: Invalid grade %f (must be between 0 and 100)\n\0".as_ptr()
                        as *const c_char,
                    grade as c_double,
                );
                free(grades as *mut libc::c_void);
                return 1;
            }
        }
        let mut course = Course {
            courseName: malloc(strlen(courseName) + 1) as *mut c_char,
            courseCode,
        };
        strcpy(course.courseName, courseName);
        let mut student = Student {
            name: std::ptr::null_mut(),
            age,
            enrolledCourse: &mut course,
            grades,
            numGrades,
        };
        updateStudentInfo(&mut student, studentName, age);
        printf(b"\nStudent Information:\n\0".as_ptr() as *const c_char);
        printf(b"------------------\n\0".as_ptr() as *const c_char);
        printf(b"Name: %s\n\0".as_ptr() as *const c_char, student.name);
        printf(b"Age: %d\n\0".as_ptr() as *const c_char, student.age);
        printf(
            b"Course: %s (Code: %d)\n\0".as_ptr() as *const c_char,
            (*student.enrolledCourse).courseName,
            (*student.enrolledCourse).courseCode,
        );
        printf(b"Grades: \0".as_ptr() as *const c_char);
        for i in 0..student.numGrades {
            printf(
                b"%.1f \0".as_ptr() as *const c_char,
                *student.grades.offset(i as isize) as c_double,
            );
        }
        printf(b"\n\0".as_ptr() as *const c_char);
        if student.numGrades > 0 {
            let mut sum: c_float = 0.0;
            for i in 0..student.numGrades {
                sum += *student.grades.offset(i as isize);
            }
            printf(
                b"Average Grade: %.2f\n\0".as_ptr() as *const c_char,
                (sum / student.numGrades as c_float) as c_double,
            );
        }
        free(course.courseName as *mut libc::c_void);
        free(student.name as *mut libc::c_void);
        free(student.grades as *mut libc::c_void);
        return 0;
    }
}
