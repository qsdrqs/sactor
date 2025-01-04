use std::collections::HashMap;
use libc::c_int;

#[derive(Copy, Clone)]
struct Foo {
    a: i32,
    b: i32,
    self_ptr: *const Foo,
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

fn use_foo(foo: Foo) -> i32 {
    foo.a + foo.b
}

fn main() {
    let a = 1;
    let b = 2;
    unsafe {
        let a_ptr = &a as *const i32;
        *a_ptr = 3;
    }
    let c = add(a, b);
    fib(c);
    println!("{}", c);
}
