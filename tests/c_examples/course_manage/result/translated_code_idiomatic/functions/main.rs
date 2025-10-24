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
            Ok(g) if g >= 0.0 && g <= 100.0 => g,
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
