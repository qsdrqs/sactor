pub fn printGrades(idx: i32) {
    if idx < 1 || idx > GRADES.len() as i32 {
        println!("Invalid student index: {}", idx);
        return;
    }
    println!("Student grades:");
    println!("Student {}: {}", idx, GRADES[(idx - 1) as usize]);
}
