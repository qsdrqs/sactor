use std::env;
use std::process;
#[derive(Copy, Clone, Debug)]
pub struct Point {
    pub x: f32,
    pub y: f32,
}
pub fn calculate_distance(p1: Point, p2: Point) -> f32 {
    let dx = p2.x - p1.x;
    let dy = p2.y - p1.y;
    (dx * dx + dy * dy).sqrt()
}
pub fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 5 {
        eprintln!("Usage: {} x1 y1 x2 y2", args[0]);
        eprintln!("Example: {} 0 0 3 4", args[0]);
        process::exit(1);
    }
    let parse_arg = |arg: &str| -> f32 {
        arg.parse::<f32>().unwrap_or_else(|_| {
            eprintln!("Invalid number format: {}", arg);
            process::exit(1);
        })
    };
    let p1 = Point {
        x: parse_arg(&args[1]),
        y: parse_arg(&args[2]),
    };
    let p2 = Point {
        x: parse_arg(&args[3]),
        y: parse_arg(&args[4]),
    };
    println!("Point 1: ({:.1}, {:.1})", p1.x, p1.y);
    println!("Point 2: ({:.1}, {:.1})", p2.x, p2.y);
    println!("Distance: {:.1}", calculate_distance(p1, p2));
}
