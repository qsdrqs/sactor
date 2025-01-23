use std::env;
use std::process::exit;

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
