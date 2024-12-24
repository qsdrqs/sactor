use std::collections::HashMap;
use libc::c_int;

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

pub fn fib(n: i32) -> i32 {
    if n <= 1 {
        return n;
    }
    fib(n - 1) + fib(n - 2)
}

fn main() {
    let a = 1;
    let b = 2;
    let c = add(a, b);
    fib(c);
    println!("{}", c);
}
