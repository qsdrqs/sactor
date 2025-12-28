pub fn average(values: &[i32]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let sum: i64 = values.iter().map(|&v| v as i64).sum();
    sum as f64 / values.len() as f64
}
