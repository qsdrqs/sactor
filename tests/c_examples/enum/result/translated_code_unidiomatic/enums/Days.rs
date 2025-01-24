use libc::c_int;

#[repr(C)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Days {
    MON = 1,
    TUE = 2,
    WED = 3,
    THU = 4,
    FRI = 5,
    SAT = 6,
    SUN = 7,
}

impl From<c_int> for Days {
    fn from(value: c_int) -> Self {
        match value {
            1 => Days::MON,
            2 => Days::TUE,
            3 => Days::WED,
            4 => Days::THU,
            5 => Days::FRI,
            6 => Days::SAT,
            7 => Days::SUN,
            _ => panic!("Invalid value for Days"),
        }
    }
}

impl From<Days> for c_int {
    fn from(day: Days) -> Self {
        day as c_int
    }
}
