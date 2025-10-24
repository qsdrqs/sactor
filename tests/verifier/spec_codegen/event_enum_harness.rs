use core::ptr;
use std::ffi;

unsafe fn CEvent_to_Event_mut(input: *mut CEvent) -> &'static mut Event {
    assert!(!input.is_null());
    let c_struct = &*input;
    let idiom_struct = match c_struct.tag {
        0 => Event::Message(if !c_struct.message.is_null() {
                unsafe { std::ffi::CStr::from_ptr(c_struct.message) }.to_string_lossy().into_owned()
            } else {
                String::new()
            }),
        1 => Event::Code(c_struct.code),
        _ => panic!("unsupported tag value"),
    };
    Box::leak(Box::new(idiom_struct))
}

unsafe fn Event_to_CEvent_mut(idiom_struct: &mut Event) -> *mut CEvent {
    let c_struct = match idiom_struct {
        Event::Message(v0) => {
            let _message_ptr: *mut libc::c_char = {
        let s = std::ffi::CString::new(v0.clone())
            .unwrap_or_else(|_| std::ffi::CString::new("").unwrap());
        s.into_raw()
    };
            let _tag: u8 = core::mem::zeroed();
            let _code: i32 = core::mem::zeroed();
            let _tag: u8 = (0) as u8;

            CEvent {
                tag: _tag,
                message: _message_ptr,
                code: _code,
            }
        },
        Event::Code(v0) => {
            let _code = v0;
            let _tag: u8 = core::mem::zeroed();
            let _message_ptr = core::ptr::null_mut();
            let _tag: u8 = (1) as u8;

            CEvent {
                tag: _tag,
                message: _message_ptr,
                code: _code,
            }
        },
        _ => panic!("unsupported variant"),
    };
    Box::into_raw(Box::new(c_struct))
}
