from dataclasses import dataclass


@dataclass(frozen=True)
class StructFewShot:
    label: str
    description: str
    unidiomatic: str
    idiomatic: str
    spec: str


@dataclass(frozen=True)
class FunctionFewShot:
    label: str
    description: str
    unidiomatic: str
    idiomatic: str
    spec: str


STRUCT_FEWSHOTS: tuple[StructFewShot, ...] = (
    StructFewShot(
        label="Example S1 (scalar + cstring + slice)",
        description="Basic struct with scalar field, C string, and slice with explicit length.",
        unidiomatic="""#[repr(C)]
pub struct A {
    pub num: u32,
    pub name: *const libc::c_char,
    pub data: *const u8,
    pub data_len: usize,
}""",
        idiomatic="""pub struct A {
    pub num: u32,
    pub name: String,
    pub data: Vec<u8>,
}""",
        spec="""{
  "struct_name": "A",
  "i_kind": "struct",
  "i_type": "A",
  "fields": [
    { "u_field": {"name": "num", "type": "u32", "shape": "scalar"},
      "i_field": {"name": "num", "type": "u32"} },
    { "u_field": {"name": "name", "type": "*const c_char", "shape": { "ptr": { "kind": "cstring" } }},
      "i_field": {"name": "name", "type": "String"} },
    { "u_field": {"name": "data", "type": "*const u8", "shape": { "ptr": { "kind": "slice", "len_from": "data_len" } }},
      "i_field": {"name": "data", "type": "Vec<u8>"} },
    { "u_field": {"name": "data_len", "type": "usize", "shape": "scalar"},
      "i_field": {"name": "data.len", "type": "usize"} }
  ]
}""",
    ),
    StructFewShot(
        label="Example S2 (nested dot paths + ref pointer)",
        description="Nested field paths and pointer treated as borrowed reference.",
        unidiomatic="""#[repr(C)]
pub struct Inner { pub x: i32, pub name: *const libc::c_char }
#[repr(C)]
pub struct Outer { pub id: u32, pub inn: Inner, pub pval: *const u32 }""",
        idiomatic="""pub struct Inner { pub x: i32, pub name: String }
pub struct Outer { pub id: u32, pub inner: Inner, pub val: u32 }""",
        spec="""{
  "struct_name": "Outer",
  "i_kind": "struct",
  "i_type": "Outer",
  "fields": [
    { "u_field": {"name": "id", "type": "u32", "shape": "scalar"},
      "i_field": {"name": "id", "type": "u32"} },
    { "u_field": {"name": "inn.x", "type": "i32", "shape": "scalar"},
      "i_field": {"name": "inner.x", "type": "i32"} },
    { "u_field": {"name": "inn.name", "type": "*const c_char", "shape": { "ptr": { "kind": "cstring" } }},
      "i_field": {"name": "inner.name", "type": "String"} },
    { "u_field": {"name": "pval", "type": "*const u32", "shape": { "ptr": { "kind": "ref" } }},
      "i_field": {"name": "val", "type": "u32"} }
  ]
}""",
    ),
    StructFewShot(
        label="Example S3 (nullable cstring to Option)",
        description="Nullable pointer mapped to Option<String> idiomatic field.",
        unidiomatic="""#[repr(C)]
pub struct S { pub name: *const libc::c_char }""",
        idiomatic="""pub struct S { pub name: Option<String> }""",
        spec="""{
  "struct_name": "S",
  "i_kind": "struct",
  "i_type": "S",
  "fields": [
    { "u_field": {"name": "name", "type": "*const c_char", "shape": { "ptr": { "kind": "cstring", "null": "nullable" } }},
      "i_field": {"name": "name", "type": "Option<String>"} }
  ]
}""",
    ),
)


FUNCTION_FEWSHOTS: tuple[FunctionFewShot, ...] = (
    FunctionFewShot(
        label="Example F1 (slice argument)",
        description="Raw slice pointer plus length translated to &[T] parameter.",
        unidiomatic="""pub unsafe extern "C" fn sum(xs: *const i32, n: usize) -> i32;""",
        idiomatic="""pub fn sum(xs: &[i32]) -> i32;""",
        spec="""{
  "function_name": "sum",
  "fields": [
    { "u_field": {"name": "xs", "type": "*const i32", "shape": { "ptr": { "kind": "slice", "len_from": "n" } }},
      "i_field": {"name": "xs", "type": "&[i32]"} },
    { "u_field": {"name": "n", "type": "usize", "shape": "scalar"},
      "i_field": {"name": "xs.len", "type": "usize"} },
    { "u_field": {"name": "ret", "type": "i32", "shape": "scalar"},
      "i_field": {"name": "ret", "type": "i32"} }
  ]
}""",
    ),
    FunctionFewShot(
        label="Example F2 (out pointer to return value)",
        description="Mutable pointer output replaced by direct return.",
        unidiomatic="""pub unsafe extern "C" fn get_value(out_value: *mut i32);""",
        idiomatic="""pub fn get_value() -> i32;""",
        spec="""{
  "function_name": "get_value",
  "fields": [
    { "u_field": {"name": "out_value", "type": "*mut i32", "shape": { "ptr": { "kind": "ref" } }},
      "i_field": {"name": "ret", "type": "i32"} }
  ]
}""",
    ),
    FunctionFewShot(
        label="Example F3 (nullable cstring to Option<&str>)",
        description="Nullable C string pointer converted to Option<&str> parameter.",
        unidiomatic="""pub unsafe extern "C" fn set_name(name: *const libc::c_char);""",
        idiomatic="""pub fn set_name(name: Option<&str>);""",
        spec="""{
  "function_name": "set_name",
  "fields": [
    { "u_field": {"name": "name", "type": "*const c_char", "shape": { "ptr": { "kind": "cstring", "null": "nullable" } }},
      "i_field": {"name": "name", "type": "Option<&str>"} }
  ]
}""",
    ),
)


__all__ = [
    "StructFewShot",
    "FunctionFewShot",
    "STRUCT_FEWSHOTS",
    "FUNCTION_FEWSHOTS",
]
