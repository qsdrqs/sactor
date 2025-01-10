#[derive(Clone, Debug)]
pub struct Course {
    pub courseName: String,
    pub courseCode: i32,
}
#[derive(Clone, Debug)]
pub struct Student {
    pub name: Option<String>,
    pub age: i32,
    pub enrolledCourse: Option<Box<Course>>,
    pub grades: Vec<f32>,
}
fn printUsage() {
    println ! ("Usage: ./program <student_name> <age> <course_name> <course_code> <grade1> [grade2] [grade3] ...");
    println!("Example: ./program \"John Doe\" 20 \"Computer Science\" 101 85.5 92.0 88.5");
}
pub fn updateStudentInfo(student: &mut Student, newName: &str, newAge: i32) {
    if newName.is_empty() {
        println!("Invalid input parameters");
        return;
    }
    student.name = Some(newName.to_owned());
    student.age = newAge;
}
fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 6 {
        println!("Error: Insufficient arguments");
        printUsage();
        std::process::exit(1);
    }
    let student_name = args[1].clone();
    let age: i32 = args[2].parse().unwrap_or(0);
    let course_name = args[3].clone();
    let course_code: i32 = args[4].parse().unwrap_or(0);
    if age <= 0 || age > 120 {
        println!("Error: Invalid age (must be between 1 and 120)");
        std::process::exit(1);
    }
    if course_code <= 0 {
        println!("Error: Invalid course code");
        std::process::exit(1);
    }
    let num_grades = args.len() - 5;
    let mut grades: Vec<f32> = Vec::with_capacity(num_grades);
    for arg in &args[5..] {
        let grade: f32 = arg.parse().unwrap_or(0.0);
        if !(0.0..=100.0).contains(&grade) {
            println!(
                "Error: Invalid grade {:.6} (must be between 0 and 100)",
                grade
            );
            std::process::exit(1);
        }
        grades.push(grade);
    }
    let course = Course {
        courseName: course_name,
        courseCode: course_code,
    };
    let mut student = Student {
        name: None,
        age: 0,
        enrolledCourse: Some(Box::new(course)),
        grades: grades.clone(),
    };
    updateStudentInfo(&mut student, &student_name, age);
    println!("\nStudent Information:");
    println!("------------------");
    if let Some(name) = &student.name {
        println!("Name: {}", name);
    }
    println!("Age: {}", student.age);
    if let Some(course) = &student.enrolledCourse {
        println!(
            "Course: {} (Code: {})",
            course.courseName, course.courseCode
        );
    }
    print!("Grades: ");
    for grade in &grades {
        print!("{:.1} ", grade);
    }
    println!();
    if !grades.is_empty() {
        let sum: f32 = grades.iter().sum();
        println!("Average Grade: {:.2}", sum / grades.len() as f32);
    }
}
