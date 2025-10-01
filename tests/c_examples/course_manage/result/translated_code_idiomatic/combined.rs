#[derive(Clone, Debug)]
pub struct Student {
    pub name: String,
    pub age: i32,
    pub enrolled_course: Course,
    pub grades: Vec<f32>,
}
#[derive(Clone, Debug)]
pub struct Course {
    pub course_name: String,
    pub course_code: i32,
}
pub fn printUsage() {
    println!(
        "Usage: ./program <student_name> <age> <course_name> <course_code> <grade1> [grade2] [grade3] ..."
    );
    println!("Example: ./program \"John Doe\" 20 \"Computer Science\" 101 85.5 92.0 88.5");
}
pub fn updateStudentInfo(student: &mut Student, new_name: Option<&str>, new_age: i32) {
    if let Some(name) = new_name {
        student.name = name.to_owned();
        student.age = new_age;
    } else {
        eprintln!("Invalid input parameters");
    }
}
pub fn main() {
    use std::env;
    use std::io::{self, Write};
    use std::process;
    fn parse_c_int_prefix(s: &str) -> i32 {
        let mut iter = s.chars().peekable();
        while let Some(&c) = iter.peek() {
            if c.is_whitespace() {
                iter.next();
            } else {
                break;
            }
        }
        let mut sign: i64 = 1;
        if let Some(&c) = iter.peek() {
            if c == '-' {
                sign = -1;
                iter.next();
            } else if c == '+' {
                iter.next();
            }
        }
        let mut any = false;
        let mut val: i64 = 0;
        while let Some(&c) = iter.peek() {
            if c.is_ascii_digit() {
                any = true;
                val = val
                    .saturating_mul(10)
                    .saturating_add((c as i64) - ('0' as i64));
                iter.next();
            } else {
                break;
            }
        }
        if !any {
            0
        } else {
            (val.saturating_mul(sign)) as i32
        }
    }
    fn parse_c_float_prefix(s: &str) -> f32 {
        let b = s.as_bytes();
        let mut i = 0usize;
        let n = b.len();
        while i < n {
            let c = b[i] as char;
            if c.is_whitespace() {
                i += 1;
            } else {
                break;
            }
        }
        let start = i;
        if i < n && (b[i] == b'+' || b[i] == b'-') {
            i += 1;
        }
        let mut digits = 0usize;
        while i < n && b[i].is_ascii_digit() {
            i += 1;
            digits += 1;
        }
        if i < n && b[i] == b'.' {
            i += 1;
            let mut fd = 0usize;
            while i < n && b[i].is_ascii_digit() {
                i += 1;
                fd += 1;
            }
            digits += fd;
        }
        if digits == 0 {
            return 0.0;
        }
        if i < n && (b[i] == b'e' || b[i] == b'E') {
            let exp_mark = i;
            let mut j = i + 1;
            if j < n && (b[j] == b'+' || b[j] == b'-') {
                j += 1;
            }
            let mut ed = 0usize;
            while j < n && b[j].is_ascii_digit() {
                j += 1;
                ed += 1;
            }
            if ed > 0 {
                i = j;
            } else {
                i = exp_mark;
            }
        }
        s[start..i].parse::<f32>().unwrap_or(0.0)
    }
    let args: Vec<String> = env::args().collect();
    let argc = args.len();
    if argc < 6 {
        println!("Error: Insufficient arguments");
        printUsage();
        let _ = io::stdout().flush();
        process::exit(1);
    }
    let student_name = &args[1];
    let age: i32 = {
        let a = parse_c_int_prefix(&args[2]);
        if (1..=120).contains(&a) {
            a
        } else {
            println!("Error: Invalid age (must be between 1 and 120)");
            let _ = io::stdout().flush();
            process::exit(1);
        }
    };
    let course_name_in = args[3].clone();
    let course_code: i32 = {
        let code = parse_c_int_prefix(&args[4]);
        if code > 0 {
            code
        } else {
            println!("Error: Invalid course code");
            let _ = io::stdout().flush();
            process::exit(1);
        }
    };
    let num_grades = argc - 5;
    let mut grades: Vec<f32> = Vec::with_capacity(num_grades);
    for i in 0..num_grades {
        let g = parse_c_float_prefix(&args[5 + i]);
        if !(0.0..=100.0).contains(&g) {
            println!("Error: Invalid grade {:.6} (must be between 0 and 100)", g);
            let _ = io::stdout().flush();
            process::exit(1);
        }
        grades.push(g);
    }
    let course = Course {
        course_name: course_name_in,
        course_code,
    };
    let mut student = Student {
        name: String::new(),
        age: 0,
        enrolled_course: course,
        grades,
    };
    updateStudentInfo(&mut student, Some(student_name), age);
    println!("\nStudent Information:");
    println!("------------------");
    println!("Name: {}", student.name);
    println!("Age: {}", student.age);
    println!(
        "Course: {} (Code: {})",
        student.enrolled_course.course_name, student.enrolled_course.course_code
    );
    print!("Grades: ");
    for g in &student.grades {
        print!("{:.1} ", g);
    }
    println!();
    if !student.grades.is_empty() {
        let sum: f32 = student.grades.iter().copied().sum();
        println!("Average Grade: {:.2}", sum / (student.grades.len() as f32));
    }
}
