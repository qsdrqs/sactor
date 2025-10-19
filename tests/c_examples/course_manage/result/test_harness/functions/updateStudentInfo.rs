use core::ptr;
use std::ffi;
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
    let c = &*input;
    let r = Course {
        course_name: if !c.courseName.is_null() {
            unsafe { std::ffi::CStr::from_ptr(c.courseName) }
                .to_string_lossy()
                .into_owned()
        } else {
            String::new()
        },
        course_code: c.courseCode,
    };
    Box::leak(Box::new(r))
}
unsafe fn Course_to_CCourse_mut(r: &mut Course) -> *mut CCourse {
    let _courseName_ptr: *mut libc::c_char = {
        let s = std::ffi::CString::new(r.course_name.clone())
            .unwrap_or_else(|_| std::ffi::CString::new("").unwrap());
        s.into_raw()
    };
    let _courseCode = r.course_code;
    let c = CCourse {
        courseName: _courseName_ptr,
        courseCode: _courseCode,
    };
    Box::into_raw(Box::new(c))
}
#[derive(Clone, Debug)]
pub struct Student {
    pub name: String,
    pub age: i32,
    pub enrolled_course: Course,
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
    let c = &*input;
    let r = Student {
        name: if !c.name.is_null() {
            unsafe { std::ffi::CStr::from_ptr(c.name) }
                .to_string_lossy()
                .into_owned()
        } else {
            String::new()
        },
        age: c.age,
        enrolled_course: {
            let tmp = unsafe { CCourse_to_Course_mut(c.enrolledCourse as *mut CCourse) };
            (*tmp).clone()
        },
        grades: if !c.grades.is_null() && (c.numGrades as usize) > 0 {
            unsafe { std::slice::from_raw_parts(c.grades as *const f32, (c.numGrades as usize)) }
                .to_vec()
        } else {
            Vec::<f32>::new()
        },
    };
    Box::leak(Box::new(r))
}
unsafe fn Student_to_CStudent_mut(r: &mut Student) -> *mut CStudent {
    let _name_ptr: *mut libc::c_char = {
        let s = std::ffi::CString::new(r.name.clone())
            .unwrap_or_else(|_| std::ffi::CString::new("").unwrap());
        s.into_raw()
    };
    let _age = r.age;
    let _enrolledCourse_ptr: *mut CCourse =
        unsafe { Course_to_CCourse_mut(&mut r.enrolled_course) };
    let _grades_ptr: *mut f32 = if r.grades.is_empty() {
        core::ptr::null_mut()
    } else {
        let mut boxed = r.grades.clone().into_boxed_slice();
        let ptr = boxed.as_mut_ptr();
        core::mem::forget(boxed);
        ptr
    };
    let _numGrades: libc::c_int = (r.grades.len() as usize) as libc::c_int;
    let c = CStudent {
        name: _name_ptr,
        age: _age,
        enrolledCourse: _enrolledCourse_ptr,
        grades: _grades_ptr,
        numGrades: _numGrades,
    };
    Box::into_raw(Box::new(c))
}
pub fn updateStudentInfo_idiomatic(student: &mut Student, new_name: Option<&str>, new_age: i32) {
    if let Some(name) = new_name {
        student.name = name.to_owned();
        student.age = new_age;
    } else {
        eprintln!("Invalid input parameters");
    }
}
fn updateStudentInfo(student: *mut CStudent, newName: *const libc::c_char, newAge: libc::c_int) {
    if student.is_null() {
        return;
    }
    let student_ref: &mut Student = unsafe { CStudent_to_Student_mut(student) };
    let new_name_opt = if !newName.is_null() {
        Some(
            unsafe { std::ffi::CStr::from_ptr(newName) }
                .to_string_lossy()
                .into_owned(),
        )
    } else {
        None
    };
    updateStudentInfo_idiomatic(student_ref, new_name_opt.as_deref(), newAge);
    let __c_student = unsafe { Student_to_CStudent_mut(student_ref) };
    unsafe {
        *student = *__c_student;
    }
    unsafe {
        let _ = Box::from_raw(__c_student);
    }
}
