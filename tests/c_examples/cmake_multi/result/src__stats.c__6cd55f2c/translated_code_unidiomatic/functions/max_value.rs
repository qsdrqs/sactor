use libc::{c_int, size_t};
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
