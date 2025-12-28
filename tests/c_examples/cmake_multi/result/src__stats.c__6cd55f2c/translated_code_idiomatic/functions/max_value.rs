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
