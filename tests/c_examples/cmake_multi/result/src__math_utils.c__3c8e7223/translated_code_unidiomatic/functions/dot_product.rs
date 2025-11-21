use libc::size_t;
pub unsafe fn dot_product(lhs: *const i32, rhs: *const i32, length: size_t) -> i32 {
    let mut total = 0;
    for i in 0..length {
        total += *lhs.add(i) * *rhs.add(i);
    }
    total
}
