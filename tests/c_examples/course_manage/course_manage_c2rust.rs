#![allow(
    dead_code,
    mutable_transmutes,
    non_camel_case_types,
    non_snake_case,
    non_upper_case_globals,
    unused_assignments,
    unused_mut
)]
extern "C" {
    fn printf(_: *const libc::c_char, _: ...) -> libc::c_int;
    fn atof(__nptr: *const libc::c_char) -> libc::c_double;
    fn atoi(__nptr: *const libc::c_char) -> libc::c_int;
    fn malloc(_: libc::c_ulong) -> *mut libc::c_void;
    fn free(_: *mut libc::c_void);
    fn strcpy(_: *mut libc::c_char, _: *const libc::c_char) -> *mut libc::c_char;
    fn strlen(_: *const libc::c_char) -> libc::c_ulong;
}
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
#[no_mangle]
pub unsafe extern "C" fn printUsage() {
    printf(
        b"Usage: ./program <student_name> <age> <course_name> <course_code> <grade1> [grade2] [grade3] ...\n\0"
            as *const u8 as *const libc::c_char,
    );
    printf(
        b"Example: ./program \"John Doe\" 20 \"Computer Science\" 101 85.5 92.0 88.5\n\0"
            as *const u8 as *const libc::c_char,
    );
}
#[no_mangle]
pub unsafe extern "C" fn updateStudentInfo(
    mut student: *mut Student,
    mut newName: *const libc::c_char,
    mut newAge: libc::c_int,
) {
    if student.is_null() || newName.is_null() {
        printf(b"Invalid input parameters\n\0" as *const u8 as *const libc::c_char);
        return;
    }
    if !((*student).name).is_null() {
        free((*student).name as *mut libc::c_void);
    }
    (*student)
        .name = malloc((strlen(newName)).wrapping_add(1 as libc::c_int as libc::c_ulong))
        as *mut libc::c_char;
    strcpy((*student).name, newName);
    (*student).age = newAge;
}
unsafe fn main_0(
    mut argc: libc::c_int,
    mut argv: *mut *mut libc::c_char,
) -> libc::c_int {
    if argc < 6 as libc::c_int {
        printf(b"Error: Insufficient arguments\n\0" as *const u8 as *const libc::c_char);
        printUsage();
        return 1 as libc::c_int;
    }
    let mut studentName: *const libc::c_char = *argv.offset(1 as libc::c_int as isize);
    let mut age: libc::c_int = atoi(*argv.offset(2 as libc::c_int as isize));
    let mut courseName: *const libc::c_char = *argv.offset(3 as libc::c_int as isize);
    let mut courseCode: libc::c_int = atoi(*argv.offset(4 as libc::c_int as isize));
    if age <= 0 as libc::c_int || age > 120 as libc::c_int {
        printf(
            b"Error: Invalid age (must be between 1 and 120)\n\0" as *const u8
                as *const libc::c_char,
        );
        return 1 as libc::c_int;
    }
    if courseCode <= 0 as libc::c_int {
        printf(b"Error: Invalid course code\n\0" as *const u8 as *const libc::c_char);
        return 1 as libc::c_int;
    }
    let mut numGrades: libc::c_int = argc - 5 as libc::c_int;
    let mut grades: *mut libc::c_float = malloc(
        (numGrades as libc::c_ulong)
            .wrapping_mul(::core::mem::size_of::<libc::c_float>() as libc::c_ulong),
    ) as *mut libc::c_float;
    let mut i: libc::c_int = 0 as libc::c_int;
    while i < numGrades {
        *grades
            .offset(
                i as isize,
            ) = atof(*argv.offset((i + 5 as libc::c_int) as isize)) as libc::c_float;
        if *grades.offset(i as isize) < 0 as libc::c_int as libc::c_float
            || *grades.offset(i as isize) > 100 as libc::c_int as libc::c_float
        {
            printf(
                b"Error: Invalid grade %f (must be between 0 and 100)\n\0" as *const u8
                    as *const libc::c_char,
                *grades.offset(i as isize) as libc::c_double,
            );
            free(grades as *mut libc::c_void);
            return 1 as libc::c_int;
        }
        i += 1;
        i;
    }
    let mut course: Course = Course {
        courseName: 0 as *mut libc::c_char,
        courseCode: 0,
    };
    course
        .courseName = malloc(
        (strlen(courseName)).wrapping_add(1 as libc::c_int as libc::c_ulong),
    ) as *mut libc::c_char;
    strcpy(course.courseName, courseName);
    course.courseCode = courseCode;
    let mut student: Student = Student {
        name: 0 as *mut libc::c_char,
        age: 0,
        enrolledCourse: 0 as *mut Course,
        grades: 0 as *mut libc::c_float,
        numGrades: 0,
    };
    student.name = 0 as *mut libc::c_char;
    student.enrolledCourse = &mut course;
    student.grades = grades;
    student.numGrades = numGrades;
    updateStudentInfo(&mut student, studentName, age);
    printf(b"\nStudent Information:\n\0" as *const u8 as *const libc::c_char);
    printf(b"------------------\n\0" as *const u8 as *const libc::c_char);
    printf(b"Name: %s\n\0" as *const u8 as *const libc::c_char, student.name);
    printf(b"Age: %d\n\0" as *const u8 as *const libc::c_char, student.age);
    printf(
        b"Course: %s (Code: %d)\n\0" as *const u8 as *const libc::c_char,
        (*student.enrolledCourse).courseName,
        (*student.enrolledCourse).courseCode,
    );
    printf(b"Grades: \0" as *const u8 as *const libc::c_char);
    let mut i_0: libc::c_int = 0 as libc::c_int;
    while i_0 < student.numGrades {
        printf(
            b"%.1f \0" as *const u8 as *const libc::c_char,
            *(student.grades).offset(i_0 as isize) as libc::c_double,
        );
        i_0 += 1;
        i_0;
    }
    printf(b"\n\0" as *const u8 as *const libc::c_char);
    if student.numGrades > 0 as libc::c_int {
        let mut sum: libc::c_float = 0 as libc::c_int as libc::c_float;
        let mut i_1: libc::c_int = 0 as libc::c_int;
        while i_1 < student.numGrades {
            sum += *(student.grades).offset(i_1 as isize);
            i_1 += 1;
            i_1;
        }
        printf(
            b"Average Grade: %.2f\n\0" as *const u8 as *const libc::c_char,
            (sum / student.numGrades as libc::c_float) as libc::c_double,
        );
    }
    free(course.courseName as *mut libc::c_void);
    free(student.name as *mut libc::c_void);
    free(student.grades as *mut libc::c_void);
    return 0 as libc::c_int;
}
pub fn main() {
    let mut args: Vec::<*mut libc::c_char> = Vec::new();
    for arg in ::std::env::args() {
        args.push(
            (::std::ffi::CString::new(arg))
                .expect("Failed to convert argument into CString.")
                .into_raw(),
        );
    }
    args.push(::core::ptr::null_mut());
    unsafe {
        ::std::process::exit(
            main_0(
                (args.len() - 1) as libc::c_int,
                args.as_mut_ptr() as *mut *mut libc::c_char,
            ) as i32,
        )
    }
}
