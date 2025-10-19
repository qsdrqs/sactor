pub fn main() {
    let mut args = std::env::args();
    let prog = args.next().unwrap_or_else(|| "program".to_string());
    let arg = match (args.next(), args.next()) {
        (Some(a), None) => a,
        _ => {
            eprintln!("Usage: {} <number>", prog);
            std::process::exit(1);
        }
    };
    let value = atoi(&arg);
    println!("Parsed integer: {}", value);
}
