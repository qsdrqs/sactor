pub unsafe fn average(values: *const libc::c_int, length: libc::size_t) -> f64 {
    if length == 0 {
        return 0.0;
    }
    let mut sum: libc::c_long = 0;
    let mut i: libc::size_t = 0;
    while i < length {
        sum += *values.add(i) as libc::c_long;
        i += 1;
    }
    (sum as f64) / (length as f64)
}
