use std::env;
use std::process::exit;
const NUM_STUDENTS: i32 = 5;
const GRADES: [i32; 5] = [85, 90, 75, 95, 88];
pub fn printGrades(idx: i32) {
    if idx < 1 || idx > GRADES.len() as i32 {
        println!("Invalid student index: {}", idx);
        return;
    }
    println!("Student grades:");
    println!("Student {}: {}", idx, GRADES[(idx - 1) as usize]);
}
pub fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 2 {
        println!("Usage: {} <index>", args[0]);
        exit(1);
    }
    let idx = match args[1].parse::<i32>() {
        Ok(n) => n,
        Err(_) => {
            println!("Invalid index, should be a number");
            exit(-1);
        }
    };
    if idx < 1 || idx > NUM_STUDENTS {
        println!("Invalid index, should be between 1 and {}", NUM_STUDENTS);
        exit(-1);
    }
    printGrades(idx);
}
