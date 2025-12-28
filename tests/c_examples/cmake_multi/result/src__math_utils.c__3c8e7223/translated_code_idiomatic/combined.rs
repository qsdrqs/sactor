pub fn add_integers(lhs: i32, rhs: i32) -> i32 {
    lhs + rhs
}
pub fn multiply_integers(lhs: i32, rhs: i32) -> i32 {
    lhs * rhs
}
pub fn dot_product(lhs: &[i32], rhs: &[i32], length: usize) -> i32 {
    let n = length.min(lhs.len()).min(rhs.len());
    lhs[..n]
        .iter()
        .zip(&rhs[..n])
        .fold(0i32, |acc, (&a, &b)| acc.wrapping_add(a.wrapping_mul(b)))
}
