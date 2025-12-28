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
