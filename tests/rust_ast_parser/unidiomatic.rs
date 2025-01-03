extern crate libc;

#[no_mangle]
pub extern "C" fn add(a: libc::c_int, b: libc::c_int) -> libc::c_int {
    a + b
}
