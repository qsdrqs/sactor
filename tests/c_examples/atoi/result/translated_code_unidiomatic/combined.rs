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
        if c.is_ascii_digit() {
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
pub fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 2 {
        let prog = args.first().map(|s| s.as_str()).unwrap_or("program");
        println!("Usage: {} <number>", prog);
        std::process::exit(1);
    }
    let cstr = std::ffi::CString::new(args[1].as_bytes()).unwrap();
    let value: libc::c_int = unsafe { atoi(cstr.as_ptr() as *mut libc::c_char) };
    println!("Parsed integer: {}", value);
}
