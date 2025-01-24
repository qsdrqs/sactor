use libc::c_int;
use std::env;
use std::process::exit;
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
    let day_str = &args[1];
    let day = day_str.parse::<i32>().unwrap_or_else(|_| {
        eprintln!("Invalid input. Please enter a valid integer.");
        exit(1);
    });
    if !(1..=7).contains(&day) {
        eprintln!("Day number must be between 1 and 7");
        exit(1);
    }
    let today: Days = day.into();
    println!("Day number: {}", today as i32);
}
