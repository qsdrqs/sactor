use core::ptr;
use std::ffi;

unsafe fn CStudent_to_Student_mut(input: *mut CStudent) -> &'static mut Student {
    assert!(!input.is_null());
    let c_struct = &*input;
    let idiom_struct = Student {
            // Field 'name' -> 'name' (C -> idiomatic)
            name: if !c_struct.name.is_null() {
                Some(unsafe { std::ffi::CStr::from_ptr(c_struct.name) }.to_string_lossy().into_owned())
            } else {
                None
            },
            // Field 'age' -> 'age' (C -> idiomatic)
            age: c_struct.age as i32,
            // Field 'enrolledCourse' -> 'enrolled_course' (C -> idiomatic)
            enrolled_course: if !c_struct.enrolledCourse.is_null() {
                let tmp = unsafe { CCourse_to_Course_mut(c_struct.enrolledCourse as *mut CCourse) };
                Some((*tmp).clone())
            } else {
                None
            },
            // Field 'grades' -> 'grades' (C -> idiomatic)
            grades: if !c_struct.grades.is_null() && (c_struct.numGrades as usize) > 0 {
                unsafe { std::slice::from_raw_parts(c_struct.grades as *const f32, (c_struct.numGrades as usize)) }.to_vec()
            } else {
                Vec::<f32>::new()
            },
            // Field 'numGrades' -> 'grades.len' (C -> idiomatic)
            // Derived field 'grades.len' computed via slice metadata
    };
    Box::leak(Box::new(idiom_struct))
}

unsafe fn Student_to_CStudent_mut(idiom_struct: &mut Student) -> *mut CStudent {
    // Field 'name' -> 'name' (idiomatic -> C)
    let _name_ptr: *mut libc::c_char = match idiom_struct.name {
        Some(s) => {
            let s = std::ffi::CString::new(s)
                .unwrap_or_else(|_| std::ffi::CString::new("").unwrap());
            s.into_raw()
        },
        None => core::ptr::null_mut(),
    };
    // Field 'age' -> 'age' (idiomatic -> C)
    let _age = idiom_struct.age;
    // Field 'enrolled_course' -> 'enrolledCourse' (idiomatic -> C)
    let _enrolledCourse_ptr: *mut CCourse = match idiom_struct.enrolled_course.as_mut() {
        Some(v) => unsafe { Course_to_CCourse_mut(v) },
        None => core::ptr::null_mut(),
    };
    // Field 'grades' -> 'grades' (idiomatic -> C)
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
