pub fn add_integers(lhs: libc::c_int, rhs: libc::c_int) -> libc::c_int {
    lhs + rhs
}
pub fn multiply_integers(lhs: libc::c_int, rhs: libc::c_int) -> libc::c_int {
    lhs * rhs
}
pub unsafe fn dot_product(lhs: *const i32, rhs: *const i32, length: usize) -> i32 {
    let mut total: i32 = 0;
    for i in 0..length {
        total = total.wrapping_add((*lhs.add(i)).wrapping_mul(*rhs.add(i)));
    }
    total
}
