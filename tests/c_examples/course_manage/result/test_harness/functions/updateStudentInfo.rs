use std::ffi::CStr;
use std::os::raw::c_char;
use std::os::raw::c_int;
#[derive(Clone)]
pub struct Student {
    pub name: String,
    pub age: i32,
    pub enrolled_course: Option<Box<Course>>,
    pub grades: Vec<f32>,
    pub num_grades: i32,
}
#[derive(Copy, Clone, Debug)]
#[repr(C)]
pub struct CStudent {
    pub name: *mut libc::c_char,
    pub age: libc::c_int,
    pub enrolledCourse: *mut CCourse,
    pub grades: *mut libc::c_float,
    pub numGrades: libc::c_int,
}
unsafe fn Student_to_CStudent_mut(input: &mut Student) -> *mut CStudent {
    let c_student = Box::new(CStudent {
        name: if !input.name.is_empty() {
            libc::strdup(input.name.as_ptr() as *const libc::c_char)
        } else {
            std::ptr::null_mut()
        },
        age: input.age as libc::c_int,
        enrolledCourse: if let Some(course) = input.enrolled_course.as_mut() {
            Course_to_CCourse_mut(course)
        } else {
            std::ptr::null_mut()
        },
        grades: if !input.grades.is_empty() {
            let array = libc::malloc(
                (input.grades.len() * std::mem::size_of::<libc::c_float>()) as libc::size_t,
            ) as *mut libc::c_float;
            if !array.is_null() {
                std::ptr::copy(input.grades.as_ptr(), array, input.grades.len());
            }
            array
        } else {
            std::ptr::null_mut()
        },
        numGrades: input.num_grades as libc::c_int,
    });
    Box::into_raw(c_student)
}
unsafe fn CStudent_to_Student_mut(input: *mut CStudent) -> &'static mut Student {
    if input.is_null() {
        panic!("Received null pointer for CStudent");
    }
    let c_student = &mut *input;
    let name = if !c_student.name.is_null() {
        let c_str = std::ffi::CStr::from_ptr(c_student.name);
        c_str.to_string_lossy().into_owned()
    } else {
        String::new()
    };
    let enrolled_course = if !c_student.enrolledCourse.is_null() {
        Some(Box::new(
            CCourse_to_Course_mut(c_student.enrolledCourse).clone(),
        ))
    } else {
        None
    };
    let grades = if !c_student.grades.is_null() {
        Vec::from_raw_parts(
            c_student.grades,
            c_student.numGrades as usize,
            c_student.numGrades as usize,
        )
    } else {
        Vec::new()
    };
    let student = Box::new(Student {
        name,
        age: c_student.age as i32,
        enrolled_course,
        grades,
        num_grades: c_student.numGrades as i32,
    });
    Box::leak(student)
}
#[derive(Clone)]
pub struct Course {
    pub course_name: String,
    pub course_code: i32,
}
#[derive(Copy, Clone, Debug)]
#[repr(C)]
pub struct CCourse {
    pub courseName: *mut libc::c_char,
    pub courseCode: libc::c_int,
}
unsafe fn Course_to_CCourse_mut(input: &mut Course) -> *mut CCourse {
    let course_name_cstring =
        std::ffi::CString::new(input.course_name.clone()).expect("CString::new failed");
    let course_name_ptr = course_name_cstring.into_raw();
    let c_course = CCourse {
        courseName: course_name_ptr,
        courseCode: input.course_code as libc::c_int,
    };
    Box::into_raw(Box::new(c_course))
}
unsafe fn CCourse_to_Course_mut(input: *mut CCourse) -> &'static mut Course {
    if input.is_null() {
        panic!("Null pointer received for CCourse");
    }
    let c_course = &mut *input;
    let course_name = if !c_course.courseName.is_null() {
        let c_str = std::ffi::CStr::from_ptr(c_course.courseName);
        c_str.to_str().expect("Invalid UTF-8").to_owned()
    } else {
        String::new()
    };
    let course_code = c_course.courseCode as i32;
    let course = Course {
        course_name,
        course_code,
    };
    Box::leak(Box::new(course))
}
pub fn updateStudentInfo_idiomatic(student: &mut Student, newName: &str, newAge: i32) {
    if newName.is_empty() {
        println!("Invalid input parameters");
        return;
    }
    student.name = newName.to_owned();
    student.age = newAge;
}
fn updateStudentInfo(student: *mut CStudent, newName: *const c_char, newAge: c_int) {
    unsafe {
        let student_idiomatic: &mut Student = CStudent_to_Student_mut(student);
        let name_str = CStr::from_ptr(newName)
            .to_str()
            .expect("Invalid UTF-8 string");
        updateStudentInfo_idiomatic(student_idiomatic, name_str, newAge as i32);
        let c_student_converted = Student_to_CStudent_mut(student_idiomatic);
        std::ptr::copy_nonoverlapping(c_student_converted, student, 1);
    }
}
