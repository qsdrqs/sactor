pub fn main() -> () {
    use libc::{c_int, size_t};
    let values: [c_int; 5] = [1, 2, 3, 4, 5];
    let length: size_t = values.len() as size_t;
    let sum: c_int;
    let product: c_int;
    let avg: f64;
    let max: c_int;
    let dot: c_int;
    unsafe {
        sum = add_integers(values[0], values[1]);
        product = multiply_integers(values[2], values[3]);
        avg = average(values.as_ptr(), length);
        max = max_value(values.as_ptr(), length);
    }
    let other: [c_int; 5] = [5, 4, 3, 2, 1];
    unsafe {
        dot = dot_product(values.as_ptr(), other.as_ptr(), length);
    }
    println!(
        "sum={} product={} avg={:.2} max={} dot={}",
        sum, product, avg, max, dot
    );
}
