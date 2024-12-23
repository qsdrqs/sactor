struct Foo {
    a: i32,
    b: i32,
}

union Bar {
    a: i32,
    b: i32,
}

pub fn add(a: i32, b: i32) -> i32 {
    a + b
}

fn main() {
    let a = 1;
    let b = 2;
    let c = add(a, b);
    println!("{}", c);
}
