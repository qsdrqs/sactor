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

use core::ptr;
use std::ffi;

unsafe fn CCourse_to_Course_mut(input: *mut CCourse) -> &'static mut Course {
    assert!(!input.is_null());
    let c_struct = &*input;
    let idiom_struct = Course {
        // Field 'courseName' -> 'course_name' (C -> idiomatic)
        course_name: if !c_struct.courseName.is_null() {
            unsafe { std::ffi::CStr::from_ptr(c_struct.courseName) }
                .to_string_lossy()
                .into_owned()
        } else {
            String::new()
        },
        // Field 'courseCode' -> 'course_code' (C -> idiomatic)
        course_code: c_struct.courseCode as i32,
    };
    Box::leak(Box::new(idiom_struct))
}

unsafe fn Course_to_CCourse_mut(idiom_struct: &mut Course) -> *mut CCourse {
    // Field 'course_name' -> 'courseName' (idiomatic -> C)
    let _courseName_ptr: *mut libc::c_char = {
        let s = std::ffi::CString::new(idiom_struct.course_name.clone())
            .unwrap_or_else(|_| std::ffi::CString::new("").unwrap());
        s.into_raw()
    };
    // Field 'course_code' -> 'courseCode' (idiomatic -> C)
    let _courseCode = idiom_struct.course_code;

    let c_struct = CCourse {
        courseName: _courseName_ptr,
        courseCode: _courseCode,
    };
    Box::into_raw(Box::new(c_struct))
}
