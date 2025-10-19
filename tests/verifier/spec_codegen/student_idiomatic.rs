#[derive(Clone, Debug)]
pub struct Course {
    pub course_name: String,
    pub course_code: i32,
}

#[derive(Clone, Debug)]
pub struct Student {
    pub name: Option<String>,
    pub age: i32,
    pub enrolled_course: Option<Course>,
    pub grades: Vec<f32>,
}
