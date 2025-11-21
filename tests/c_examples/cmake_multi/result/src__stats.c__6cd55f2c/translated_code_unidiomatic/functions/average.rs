use libc::{c_int, size_t};
pub unsafe fn average(values: *const c_int, length: size_t) -> f64 {
    if length == 0 {
        return 0.0;
    }
    let mut sum: libc::c_long = 0;
    for i in 0..length {
        sum += *values.add(i) as libc::c_long;
    }
    sum as f64 / length as f64
}
