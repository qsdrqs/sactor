use libc::{atoi, c_int};
use std::env;
use std::process::exit;
pub fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 2 {
        println!("Usage: {} <day number>", args[0]);
        exit(1);
    }
    let day: c_int = unsafe { atoi(args[1].as_ptr() as *const i8) };
    if day < Days::MON as c_int || day > Days::SUN as c_int {
        println!("Invalid day number, should be between 1 and 7");
        exit(1);
    }
    let today: Days = Days::from(day);
    println!("Day number: {}", c_int::from(today));
}
