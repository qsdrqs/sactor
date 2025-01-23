use libc::{atoi, c_int};
use std::env;
use std::process::exit;
pub fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 2 {
        println!("Usage: {} <index>", args[0]);
        exit(1);
    }
    let idx = unsafe { atoi(args[1].as_ptr() as *const i8) };
    if idx < 1 || idx > NUM_STUDENTS {
        println!("Invalid index, should be between 1 and {}", NUM_STUDENTS);
        exit(-1);
    }
    unsafe {
        printGrades(idx);
    }
}
