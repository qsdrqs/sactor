pub fn atoi(s: &str) -> i32 {
    let bytes = s.as_bytes();
    let mut i = 0usize;
    while i < bytes.len() {
        match bytes[i] {
            b' ' | b'\t' | b'\n' | b'\r' | 0x0b | 0x0c => i += 1,
            _ => break,
        }
    }
    let mut sign: i32 = 1;
    if i < bytes.len() {
        match bytes[i] {
            b'+' => i += 1,
            b'-' => {
                sign = -1;
                i += 1;
            }
            _ => {}
        }
    }
    let mut result: i32 = 0;
    while i < bytes.len() {
        let c = bytes[i];
        if c.is_ascii_digit() {
            result = result.wrapping_mul(10).wrapping_add((c - b'0') as i32);
            i += 1;
        } else {
            break;
        }
    }
    result.wrapping_mul(sign)
}
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
