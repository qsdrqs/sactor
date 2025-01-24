use std::env;
use std::process::exit;

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

    if day < 1 || day > 7 {
        eprintln!("Day number must be between 1 and 7");
        exit(1);
    }

    let today: Days = day.into();
    println!("Day number: {}", today as i32);
}
