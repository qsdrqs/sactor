use core::ptr;
use std::ffi;
use std::os::raw::c_char;
use std::os::raw::c_int;
#[derive(Clone, Debug)]
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
unsafe fn CCourse_to_Course_mut(input: *mut CCourse) -> &'static mut Course {
    assert!(!input.is_null());
    let c_struct = &*input;
    let idiom_struct = Course {
        course_name: if !c_struct.courseName.is_null() {
            unsafe { std::ffi::CStr::from_ptr(c_struct.courseName) }
                .to_string_lossy()
                .into_owned()
        } else {
            String::new()
        },
        course_code: c_struct.courseCode as i32,
    };
    Box::leak(Box::new(idiom_struct))
}
unsafe fn Course_to_CCourse_mut(idiom_struct: &mut Course) -> *mut CCourse {
    let _courseName_ptr: *mut libc::c_char = {
        let s = std::ffi::CString::new(idiom_struct.course_name.clone())
            .unwrap_or_else(|_| std::ffi::CString::new("").unwrap());
        s.into_raw()
    };
    let _courseCode = idiom_struct.course_code;
    let c_struct = CCourse {
        courseName: _courseName_ptr,
        courseCode: _courseCode,
    };
    Box::into_raw(Box::new(c_struct))
}
#[derive(Clone, Debug)]
pub struct Student {
    pub name: String,
    pub age: i32,
    pub enrolled_course: Option<Course>,
    pub grades: Vec<f32>,
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
unsafe fn CStudent_to_Student_mut(input: *mut CStudent) -> &'static mut Student {
    assert!(!input.is_null());
    let c_struct = &*input;
    let idiom_struct = Student {
        name: if !c_struct.name.is_null() {
            unsafe { std::ffi::CStr::from_ptr(c_struct.name) }
                .to_string_lossy()
                .into_owned()
        } else {
            String::new()
        },
        age: c_struct.age as i32,
        enrolled_course: if !c_struct.enrolledCourse.is_null() {
            let tmp = unsafe { CCourse_to_Course_mut(c_struct.enrolledCourse as *mut CCourse) };
            Some((*tmp).clone())
        } else {
            None
        },
        grades: if !c_struct.grades.is_null() && (c_struct.numGrades as usize) > 0 {
            unsafe {
                std::slice::from_raw_parts(
                    c_struct.grades as *const f32,
                    (c_struct.numGrades as usize),
                )
            }
            .to_vec()
        } else {
            Vec::<f32>::new()
        },
    };
    Box::leak(Box::new(idiom_struct))
}
unsafe fn Student_to_CStudent_mut(idiom_struct: &mut Student) -> *mut CStudent {
    let _name_ptr: *mut libc::c_char = {
        let s = std::ffi::CString::new(idiom_struct.name.clone())
            .unwrap_or_else(|_| std::ffi::CString::new("").unwrap());
        s.into_raw()
    };
    let _age = idiom_struct.age;
    let _enrolledCourse_ptr: *mut CCourse = match idiom_struct.enrolled_course.as_mut() {
        Some(v) => unsafe { Course_to_CCourse_mut(v) },
        None => core::ptr::null_mut(),
    };
    let _grades_ptr: *mut f32 = if idiom_struct.grades.is_empty() {
        core::ptr::null_mut()
    } else {
        let mut b = idiom_struct.grades.clone().into_boxed_slice();
        let p = b.as_mut_ptr();
        core::mem::forget(b);
        p
    };
    let _numGrades: libc::c_int = (idiom_struct.grades.len() as usize) as libc::c_int;
    let c_struct = CStudent {
        name: _name_ptr,
        age: _age,
        enrolledCourse: _enrolledCourse_ptr,
        grades: _grades_ptr,
        numGrades: _numGrades,
    };
    Box::into_raw(Box::new(c_struct))
}
pub fn update_student_info(student: &mut Student, new_name: Option<&str>, new_age: i32) {
    if let Some(name) = new_name {
        student.name = name.to_string();
    } else {
        eprintln!("Invalid input parameters");
        return;
    }
    student.age = new_age;
}
fn updateStudentInfo(student: *mut CStudent, newName: *const c_char, newAge: c_int) {
    let mut student_idiom: &'static mut Student = unsafe { CStudent_to_Student_mut(student) };
    let new_name_opt = if !newName.is_null() {
        Some(
            unsafe { std::ffi::CStr::from_ptr(newName) }
                .to_string_lossy()
                .into_owned(),
        )
    } else {
        None
    };
    update_student_info(student_idiom, new_name_opt.as_deref(), newAge);
    if !student.is_null() {
        let __c_student = unsafe { Student_to_CStudent_mut(student_idiom) };
        unsafe {
            *student = *__c_student;
        }
        unsafe {
            let _ = Box::from_raw(__c_student);
        }
    }
}
