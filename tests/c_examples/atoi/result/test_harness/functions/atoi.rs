pub fn atoi_idiomatic(s: &str) -> i32 {
    let bytes = s.as_bytes();
    let mut i = 0usize;
    while i < bytes.len() {
        match bytes[i] {
            b' ' | b'\t' | b'\n' | b'\r' | 0x0b | 0x0c => i += 1,
            _ => break,
        }
    }
    let mut sign: i32 = 1;
    if i < bytes.len() {
        match bytes[i] {
            b'+' => i += 1,
            b'-' => {
                sign = -1;
                i += 1;
            }
            _ => {}
        }
    }
    let mut result: i32 = 0;
    while i < bytes.len() {
        let c = bytes[i];
        if (b'0'..=b'9').contains(&c) {
            result = result.wrapping_mul(10).wrapping_add((c - b'0') as i32);
            i += 1;
        } else {
            break;
        }
    }
    result.wrapping_mul(sign)
}
fn atoi(str_: *mut libc::c_char) -> libc::c_int {
    let s_str = if !str_.is_null() {
        unsafe { std::ffi::CStr::from_ptr(str_) }
            .to_string_lossy()
            .into_owned()
    } else {
        String::new()
    };
    let __ret = atoi_idiomatic(&s_str);
    return __ret;
}
