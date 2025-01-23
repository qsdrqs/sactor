use std::os::raw::c_int;
const GRADES: [i32; 5] = [85, 90, 75, 95, 88];
pub fn printGrades_idiomatic(idx: i32) {
    if idx < 1 || idx > GRADES.len() as i32 {
        println!("Invalid student index: {}", idx);
        return;
    }
    println!("Student grades:");
    println!("Student {}: {}", idx, GRADES[(idx - 1) as usize]);
}
fn printGrades(idx: c_int) {
    let idx_i32 = idx as i32;
    printGrades_idiomatic(idx_i32);
}
