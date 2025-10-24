#[derive(Clone, Debug)]
pub struct Student {
    pub name: String,
    pub age: i32,
    pub enrolled_course: Option<Course>,
    pub grades: Vec<f32>,
}
#[derive(Clone, Debug)]
pub struct Course {
    pub course_name: String,
    pub course_code: i32,
}
pub fn print_usage() {
    let usage_message = "Usage: ./program <student_name> <age> <course_name> <course_code> <grade1> [grade2] [grade3] ...\n";
    let example_message =
        "Example: ./program \"John Doe\" 20 \"Computer Science\" 101 85.5 92.0 88.5\n";
    println!("{}", usage_message);
    println!("{}", example_message);
}
pub fn update_student_info(student: &mut Student, new_name: Option<&str>, new_age: i32) {
    if let Some(name) = new_name {
        student.name = name.to_string();
    } else {
        eprintln!("Invalid input parameters");
        return;
    }
    student.age = new_age;
}
pub fn main() {
    use std::env;
    let args: Vec<String> = env::args().collect();
    let argc = args.len();
    if argc < 6 {
        println!("Error: Insufficient arguments");
        print_usage();
        std::process::exit(1);
    }
    let student_name = args[1].clone();
    let age: i32 = match args[2].parse() {
        Ok(n) if n > 0 && n <= 120 => n,
        _ => {
            println!("Error: Invalid age (must be between 1 and 120)");
            std::process::exit(1);
        }
    };
    let course_name = args[3].clone();
    let course_code: i32 = match args[4].parse() {
        Ok(n) if n > 0 => n,
        _ => {
            println!("Error: Invalid course code");
            std::process::exit(1);
        }
    };
    let num_grades = argc - 5;
    let mut grades = Vec::with_capacity(num_grades);
    for i in 0..num_grades {
        let grade: f32 = match args[i + 5].parse() {
            Ok(g) if (0.0..=100.0).contains(&g) => g,
            Ok(g) => {
                println!("Error: Invalid grade {:.6} (must be between 0 and 100)", g);
                std::process::exit(1);
            }
            _ => {
                println!("Error: Invalid grade (must be between 0 and 100)");
                std::process::exit(1);
            }
        };
        grades.push(grade);
    }
    let course = Course {
        course_name: course_name.clone(),
        course_code,
    };
    let mut student = Student {
        name: String::new(),
        age: 0,
        enrolled_course: Some(course),
        grades,
    };
    update_student_info(&mut student, Some(&student_name), age);
    println!("\nStudent Information:");
    println!("------------------");
    println!("Name: {}", student.name);
    println!("Age: {}", student.age);
    if let Some(course) = &student.enrolled_course {
        println!(
            "Course: {} (Code: {})",
            course.course_name, course.course_code
        );
    }
    print!("Grades: ");
    for grade in &student.grades {
        print!("{:.1} ", grade);
    }
    println!();
    if !student.grades.is_empty() {
        let sum: f32 = student.grades.iter().sum();
        println!("Average Grade: {:.2}", sum / student.grades.len() as f32);
    }
}
