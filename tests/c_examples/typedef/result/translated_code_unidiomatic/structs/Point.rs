#[derive(Copy, Clone, Debug)]
#[repr(C)]
pub struct Point {
    pub x: libc::c_float,
    pub y: libc::c_float,
}
