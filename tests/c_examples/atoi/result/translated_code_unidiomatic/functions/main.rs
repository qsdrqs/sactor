pub fn main() -> () {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 2 {
        let prog = args.get(0).map(|s| s.as_str()).unwrap_or("program");
        println!("Usage: {} <number>", prog);
        std::process::exit(1);
    }
    let cstr = std::ffi::CString::new(args[1].as_bytes()).unwrap();
    let value: libc::c_int = unsafe { atoi(cstr.as_ptr() as *mut libc::c_char) };
    println!("Parsed integer: {}", value);
}
