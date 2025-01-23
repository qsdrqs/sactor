use libc::atoi;
use libc::c_int;
use libc::printf;
use std::env;
use std::process::exit;
const GRADES: [i32; 5] = [85, 90, 75, 95, 88];
const NUM_STUDENTS: i32 = 5;
pub unsafe fn printGrades(idx: c_int) {
    printf("Student grades:\n\0".as_ptr() as *const i8);
    printf(
        "Student %d: %d\n\0".as_ptr() as *const i8,
        idx,
        GRADES[(idx - 1) as usize],
    );
}
pub fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 2 {
        println!("Usage: {} <index>", args[0]);
        exit(1);
    }
    let idx = unsafe { atoi(args[1].as_ptr() as *const i8) };
    if !(1..=NUM_STUDENTS).contains(&idx) {
        println!("Invalid index, should be between 1 and {}", NUM_STUDENTS);
        exit(-1);
    }
    unsafe {
        printGrades(idx);
    }
}
