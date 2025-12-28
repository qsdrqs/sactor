pub fn multiply_integers_idiomatic(lhs: i32, rhs: i32) -> i32 {
    lhs * rhs
}
fn multiply_integers(lhs: libc::c_int, rhs: libc::c_int) -> libc::c_int {
    let __ret = multiply_integers_idiomatic(lhs, rhs);
    return __ret;
}
