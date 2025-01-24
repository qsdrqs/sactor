use libc::atoi;
use libc::c_int;
use std::env;
use std::process::exit;
#[repr(C)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Days {
    MON = 1,
    TUE = 2,
    WED = 3,
    THU = 4,
    FRI = 5,
    SAT = 6,
    SUN = 7,
}
impl From<c_int> for Days {
    fn from(value: c_int) -> Self {
        match value {
            1 => Days::MON,
            2 => Days::TUE,
            3 => Days::WED,
            4 => Days::THU,
            5 => Days::FRI,
            6 => Days::SAT,
            7 => Days::SUN,
            _ => panic!("Invalid value for Days"),
        }
    }
}
impl From<Days> for c_int {
    fn from(day: Days) -> Self {
        day as c_int
    }
}
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
