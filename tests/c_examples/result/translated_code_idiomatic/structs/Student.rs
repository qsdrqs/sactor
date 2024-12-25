#[derive(Clone)]
pub struct Student {
    pub name: String,
    pub age: i32,
    pub enrolled_course: Option<Box<Course>>,
    pub grades: Vec<f32>,
    pub num_grades: i32,
}
