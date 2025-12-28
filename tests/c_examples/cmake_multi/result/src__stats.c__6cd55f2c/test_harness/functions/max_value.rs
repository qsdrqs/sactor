pub fn max_value_idiomatic(values: &[i32]) -> i32 {
    match values.split_first() {
        None => 0,
        Some((first, rest)) => {
            let mut current_max = *first;
            for &v in rest {
                if v > current_max {
                    current_max = v;
                }
            }
            current_max
        }
    }
}
fn max_value(values: *const i32, length: libc::size_t) -> i32 {
    let values_len = length as usize;
    let values_len_non_null = if values.is_null() { 0 } else { values_len };
    let values: &[i32] = if values_len_non_null == 0 {
        &[]
    } else {
        unsafe { std::slice::from_raw_parts(values as *const i32, values_len_non_null) }
    };
    let __ret = max_value_idiomatic(values);
    return __ret;
}
