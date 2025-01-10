fn main() {
    let args: Vec<String> = std::env::args().collect();

    // Check minimum required arguments (program_name + 5 required args = 6)
    if args.len() < 6 {
        println!("Error: Insufficient arguments");
        printUsage();
        std::process::exit(1);
    }

    // Parse basic information
    let student_name = args[1].clone();
    let age: i32 = args[2].parse().unwrap_or(0);
    let course_name = args[3].clone();
    let course_code: i32 = args[4].parse().unwrap_or(0);

    // Validate age
    if age <= 0 || age > 120 {
        println!("Error: Invalid age (must be between 1 and 120)");
        std::process::exit(1);
    }

    // Validate course code
    if course_code <= 0 {
        println!("Error: Invalid course code");
        std::process::exit(1);
    }

    // Calculate number of grades provided
    let num_grades = args.len() - 5;
    let mut grades: Vec<f32> = Vec::with_capacity(num_grades);

    // Parse grades
    for arg in &args[5..] {
        let grade: f32 = arg.parse().unwrap_or(0.0);
        // Validate grade
        if grade < 0.0 || grade > 100.0 {
            println!("Error: Invalid grade {:.6} (must be between 0 and 100)", grade);
            std::process::exit(1);
        }
        grades.push(grade);
    }

    // Create course
    let course = Course {
        courseName: course_name,
        courseCode: course_code,
    };

    // Create student
    let mut student = Student {
        name: None,
        age: 0,
        enrolledCourse: Some(Box::new(course)),
        grades: grades.clone(),
    };

    // Update student information
    updateStudentInfo(&mut student, &student_name, age);

    // Print student information
    println!("\nStudent Information:");
    println!("------------------");
    if let Some(name) = &student.name {
        println!("Name: {}", name);
    }
    println!("Age: {}", student.age);
    if let Some(course) = &student.enrolledCourse {
        println!("Course: {} (Code: {})", course.courseName, course.courseCode);
    }

    print!("Grades: ");
    for grade in &grades {
        print!("{:.1} ", grade);
    }
    println!();

    // Calculate and print average grade
    if !grades.is_empty() {
        let sum: f32 = grades.iter().sum();
        println!("Average Grade: {:.2}", sum / grades.len() as f32);
    }
}
