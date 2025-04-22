use std::ffi::CStr;
use std::os::raw::c_char;
pub fn atoi_idiomatic(input: &str) -> i32 {
    let mut result: i32 = 0;
    let mut sign: i32 = 1;
    let mut chars = input.chars().peekable();
    while let Some(&c) = chars.peek() {
        if c.is_whitespace() {
            chars.next();
        } else {
            break;
        }
    }
    if let Some(&c) = chars.peek() {
        if c == '+' || c == '-' {
            if c == '-' {
                sign = -1;
            }
            chars.next();
        }
    }
    while let Some(c) = chars.next() {
        if let Some(digit) = c.to_digit(10) {
            if let Some(new_result) = result
                .checked_mul(10)
                .and_then(|r| r.checked_add(digit as i32))
            {
                result = new_result;
            } else {
                return if sign == 1 { i32::MAX } else { i32::MIN };
            }
        } else {
            break;
        }
    }
    sign * result
}
fn atoi(str: *const c_char) -> i32 {
    let c_str = unsafe { CStr::from_ptr(str) };
    let input = c_str.to_str().expect("Invalid UTF-8 string");
    let result = atoi_idiomatic(input);
    result
}
