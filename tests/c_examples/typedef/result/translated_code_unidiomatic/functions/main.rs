use libc;
use std::env;
use std::ffi::CString;
use std::process;
pub fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 5 {
        eprintln!("Usage: {} x1 y1 x2 y2", args[0]);
        eprintln!("Example: {} 0 0 3 4", args[0]);
        process::exit(1);
    }
    let p1 = Point {
        x: unsafe { libc::atof(CString::new(args[1].as_str()).unwrap().as_ptr()) as f32 },
        y: unsafe { libc::atof(CString::new(args[2].as_str()).unwrap().as_ptr()) as f32 },
    };
    let p2 = Point {
        x: unsafe { libc::atof(CString::new(args[3].as_str()).unwrap().as_ptr()) as f32 },
        y: unsafe { libc::atof(CString::new(args[4].as_str()).unwrap().as_ptr()) as f32 },
    };
    println!("Point 1: ({:.1}, {:.1})", p1.x, p1.y);
    println!("Point 2: ({:.1}, {:.1})", p2.x, p2.y);
    println!("Distance: {:.1}", unsafe { calculate_distance(p1, p2) });
}
