pub unsafe fn atoi(mut str_: *mut libc::c_char) -> libc::c_int {
    let mut result: libc::c_int = 0;
    let mut sign: libc::c_int = 1;
    loop {
        let c = *str_ as u8;
        if c == b' ' || c == b'\t' || c == b'\n' || c == b'\r' || c == b'\x0b' || c == b'\x0c' {
            str_ = str_.add(1);
        } else {
            break;
        }
    }
    let c = *str_ as u8;
    if c == b'+' || c == b'-' {
        if c == b'-' {
            sign = -1;
        }
        str_ = str_.add(1);
    }
    loop {
        let c = *str_ as u8;
        if c >= b'0' && c <= b'9' {
            result = result
                .wrapping_mul(10)
                .wrapping_add((c - b'0') as libc::c_int);
            str_ = str_.add(1);
        } else {
            break;
        }
    }
    sign.wrapping_mul(result)
}
