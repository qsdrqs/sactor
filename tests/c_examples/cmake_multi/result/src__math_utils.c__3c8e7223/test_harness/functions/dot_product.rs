pub fn dot_product_idiomatic(lhs: &[i32], rhs: &[i32], length: usize) -> i32 {
    let n = length.min(lhs.len()).min(rhs.len());
    lhs[..n]
        .iter()
        .zip(&rhs[..n])
        .fold(0i32, |acc, (&a, &b)| acc.wrapping_add(a.wrapping_mul(b)))
}
fn dot_product(lhs: *const i32, rhs: *const i32, length: usize) -> i32 {
    let lhs_len = length as usize;
    let lhs_len_non_null = if lhs.is_null() { 0 } else { lhs_len };
    let lhs: &[i32] = if lhs_len_non_null == 0 {
        &[]
    } else {
        unsafe { std::slice::from_raw_parts(lhs as *const i32, lhs_len_non_null) }
    };
    let rhs_len = length as usize;
    let rhs_len_non_null = if rhs.is_null() { 0 } else { rhs_len };
    let rhs: &[i32] = if rhs_len_non_null == 0 {
        &[]
    } else {
        unsafe { std::slice::from_raw_parts(rhs as *const i32, rhs_len_non_null) }
    };
    let __ret = dot_product_idiomatic(lhs, rhs, length);
    return __ret;
}
