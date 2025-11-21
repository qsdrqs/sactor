use libc::size_t;
pub fn add_integers(lhs: i32, rhs: i32) -> i32 {
    lhs + rhs
}
pub unsafe fn multiply_integers(lhs: libc::c_int, rhs: libc::c_int) -> libc::c_int {
    lhs * rhs
}
pub unsafe fn dot_product(lhs: *const i32, rhs: *const i32, length: size_t) -> i32 {
    let mut total = 0;
    for i in 0..length {
        total += *lhs.add(i) * *rhs.add(i);
    }
    total
}
