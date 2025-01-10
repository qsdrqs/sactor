use libc;
extern "C" {
    fn sqrtf(x: libc::c_float) -> libc::c_float;
}
pub fn calculate_distance(p1: Point, p2: Point) -> libc::c_float {
    let dx = p2.x - p1.x;
    let dy = p2.y - p1.y;
    unsafe { sqrtf(dx * dx + dy * dy) }
}
