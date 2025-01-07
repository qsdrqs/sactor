#[derive(Clone, Debug)]
pub struct Student {
    pub name: Option<String>,
    pub age: i32,
    pub enrolledCourse: Option<Box<Course>>,
    pub grades: Vec<f32>,
}
