#[derive(Clone, Debug)]
pub struct Student {
    pub name: String,
    pub age: i32,
    pub enrolled_course: Option<Course>,
    pub grades: Vec<f32>,
}
