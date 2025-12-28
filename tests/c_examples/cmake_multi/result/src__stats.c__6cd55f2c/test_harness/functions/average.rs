pub fn average_idiomatic(values: &[i32]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let sum: i64 = values.iter().map(|&v| v as i64).sum();
    sum as f64 / values.len() as f64
}
fn average(values: *const libc::c_int, length: libc::size_t) -> f64 {
    let values_len = length as usize;
    let values_len_non_null = if values.is_null() { 0 } else { values_len };
    let values: &[i32] = if values_len_non_null == 0 {
        &[]
    } else {
        unsafe { std::slice::from_raw_parts(values as *const i32, values_len_non_null) }
    };
    let __ret = average_idiomatic(values);
    return __ret;
}
