pub unsafe fn max_value(values: *const i32, length: libc::size_t) -> i32 {
    if length == 0 {
        return 0;
    }
    let mut current_max: i32 = *values;
    let mut i: libc::size_t = 1;
    while i < length {
        let v = *values.add(i as usize);
        if v > current_max {
            current_max = v;
        }
        i += 1;
    }
    current_max
}
