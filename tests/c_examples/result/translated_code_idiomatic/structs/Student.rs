#[derive(Clone)]
pub struct Student {
    pub name: Vec<u8>, // Assuming UTF-8 encoding for the name
    pub age: i32,
    pub enrolled_course: Option<Box<Course>>, // Optional owned pointer
    pub grades: Vec<f32>, // Dynamic array of grades
}
