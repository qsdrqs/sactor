use libc::c_float;
#[derive(Copy, Clone, Debug)]
pub struct Point {
    pub x: f32,
    pub y: f32,
}
#[derive(Copy, Clone, Debug)]
#[repr(C)]
pub struct CPoint {
    pub x: libc::c_float,
    pub y: libc::c_float,
}
unsafe fn Point_to_CPoint_mut(input: &mut Point) -> *mut CPoint {
    let cpoint = CPoint {
        x: input.x as libc::c_float,
        y: input.y as libc::c_float,
    };
    Box::into_raw(Box::new(cpoint))
}
unsafe fn CPoint_to_Point_mut(input: *mut CPoint) -> &'static mut Point {
    assert!(!input.is_null(), "Input pointer is null");
    let cpoint_ref = &mut *input;
    let point = Point {
        x: cpoint_ref.x as f32,
        y: cpoint_ref.y as f32,
    };
    Box::leak(Box::new(point))
}
pub fn calculate_distance_idiomatic(p1: Point, p2: Point) -> f32 {
    let dx = p2.x - p1.x;
    let dy = p2.y - p1.y;
    (dx * dx + dy * dy).sqrt()
}
fn calculate_distance(mut p1: CPoint, mut p2: CPoint) -> libc::c_float {
    unsafe {
        let idiomatic_p1 = CPoint_to_Point_mut(&mut p1 as *mut CPoint);
        let idiomatic_p2 = CPoint_to_Point_mut(&mut p2 as *mut CPoint);
        let result = calculate_distance_idiomatic(*idiomatic_p1, *idiomatic_p2);
        result
    }
}
