use std::env;
use std::process;

pub fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 2 {
        println!("Usage: {} <number>", args[0]);
        process::exit(1);
    }

    let input = &args[1];
    let value = atoi(input);
    println!("Parsed integer: {}", value);
}
