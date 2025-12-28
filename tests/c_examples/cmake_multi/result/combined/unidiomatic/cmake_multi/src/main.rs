#![allow(unused_imports, unused_variables, dead_code)]
#[path = "math_utils.rs"]
mod math_utils;
#[path = "stats.rs"]
mod stats;
use crate::math_utils::add_integers;
use crate::math_utils::dot_product;
use crate::math_utils::multiply_integers;
use crate::stats::average;
use crate::stats::max_value;

pub fn main() {
    unsafe {
        let values: [libc::c_int; 5] = [1, 2, 3, 4, 5];
        let length: libc::size_t = (values.len()) as libc::size_t;
        let sum: libc::c_int = add_integers(values[0], values[1]);
        let product: libc::c_int = multiply_integers(values[2], values[3]);
        let avg: f64 = average(values.as_ptr(), length);
        let max: i32 = max_value(values.as_ptr() as *const i32, length);
        let other: [libc::c_int; 5] = [5, 4, 3, 2, 1];
        let dot: i32 = dot_product(
            values.as_ptr() as *const i32,
            other.as_ptr() as *const i32,
            length as usize,
        );
        libc::printf(
            b"sum=%d product=%d avg=%.2f max=%d dot=%d\n\0".as_ptr() as *const libc::c_char,
            sum,
            product,
            avg,
            max,
            dot,
        );
    }
}
