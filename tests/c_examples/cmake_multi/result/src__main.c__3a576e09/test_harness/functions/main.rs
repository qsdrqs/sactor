pub fn max_value(values: &[i32]) -> i32 {
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
pub fn average(values: &[i32]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let sum: i64 = values.iter().map(|&v| v as i64).sum();
    sum as f64 / values.len() as f64
}
pub fn add_integers(lhs: i32, rhs: i32) -> i32 {
    lhs + rhs
}
pub fn main() {
    let values: [i32; 5] = [1, 2, 3, 4, 5];
    let sum: i32 = add_integers(values[0], values[1]);
    let product: i32 = multiply_integers(values[2], values[3]);
    let avg: f64 = average(&values);
    let max: i32 = max_value(&values);
    let other: [i32; 5] = [5, 4, 3, 2, 1];
    let dot: i32 = dot_product(&values, &other, values.len());
    println!(
        "sum={} product={} avg={:.2} max={} dot={}",
        sum, product, avg, max, dot
    );
}
