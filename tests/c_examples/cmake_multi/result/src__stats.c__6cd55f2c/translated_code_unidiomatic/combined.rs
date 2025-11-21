use libc::c_int;
use libc::size_t;
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
pub unsafe fn max_value(values: *const c_int, length: size_t) -> c_int {
    if length == 0 {
        return 0;
    }
    let mut current_max = *values;
    for i in 1..length {
        let value = *values.add(i);
        if value > current_max {
            current_max = value;
        }
    }
    current_max
}
