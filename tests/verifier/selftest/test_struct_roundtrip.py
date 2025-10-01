import json
from pathlib import Path

import pytest

from sactor.verifier.selftest.struct_roundtrip import StructRoundTripTester


def test_run_minimal_prefers_llm(monkeypatch):
    tester = StructRoundTripTester(llm=object())
    block = "c0.num = 42;"
    recorded = []

    monkeypatch.setattr(
        tester, "_generate_llm_fill_block", lambda code, name, idiom: (block, True)
    )
    monkeypatch.setattr(tester, "_render_sample_blocks", lambda name: [])
    monkeypatch.setattr(
        tester,
        "_materialize_lib_rs",
        lambda code, name, idiom, fill, compares: (
            recorded.append((fill[:], compares[:])) or "// stub"
        ),
    )
    monkeypatch.setattr(tester, "_run_cargo", lambda workdir: (True, "ok"))

    ok, snippet = tester.run_minimal("// code", "Foo")

    assert ok
    assert snippet == "ok"
    assert recorded == [([block], [])]


def test_run_minimal_fallback_to_zero(monkeypatch):
    tester = StructRoundTripTester(llm=object())
    block = "c0.num = 7;"
    recorded = []

    monkeypatch.setattr(
        tester, "_generate_llm_fill_block", lambda code, name, idiom: (block, True)
    )
    monkeypatch.setattr(tester, "_render_sample_blocks", lambda name: [])

    def fake_materialize(code, name, idiom, fill, compares):
        recorded.append((fill[:], compares[:]))
        return "// stub"

    monkeypatch.setattr(tester, "_materialize_lib_rs", fake_materialize)

    calls = {"count": 0}

    def fake_run(workdir):
        calls["count"] += 1
        if calls["count"] == 1:
            return False, "llm fail"
        return True, "zero ok"

    monkeypatch.setattr(tester, "_run_cargo", fake_run)

    ok, snippet = tester.run_minimal("// code", "Foo")

    assert ok
    assert snippet == "zero ok"
    assert recorded == [([block], []), ([], [])]


def test_run_minimal_uses_samples_when_no_llm(monkeypatch):
    tester = StructRoundTripTester()
    sample_block = "c0.num = 5;"
    recorded = []

    monkeypatch.setattr(
        tester, "_generate_llm_fill_block", lambda code, name, idiom: (None, False)
    )
    monkeypatch.setattr(tester, "_render_sample_blocks", lambda name: [sample_block])
    monkeypatch.setattr(
        tester,
        "_materialize_lib_rs",
        lambda code, name, idiom, fill, compares: (
            recorded.append((fill[:], compares[:])) or "// stub"
        ),
    )
    monkeypatch.setattr(tester, "_run_cargo", lambda workdir: (True, "ok"))

    ok, snippet = tester.run_minimal("// code", "Foo")

    assert ok
    assert snippet == "ok"
    assert recorded == [([sample_block], [])]


def test_gen_tests_respects_idiomatic_name():
    tester = StructRoundTripTester()
    code = tester._gen_tests("node", "Node", [], [])
    assert "Cnode_to_Node_mut" in code
    assert "Node_to_Cnode_mut" in code


def test_collect_compare_fields(tmp_path):
    spec = {
        "struct_name": "Foo",
        "fields": [
            {
                "u_field": {"name": "value", "type": "u32", "shape": "scalar"},
                "i_field": {"name": "value", "type": "u32"},
                "compare": "by_value",
            },
            {
                "u_field": {"name": "len", "type": "usize", "shape": "scalar"},
                "i_field": {"name": "bytes.len", "type": "usize"},
                "compare": "by_value",
            },
            {
                "u_field": {"name": "skip_me", "type": "u32", "shape": "scalar"},
                "i_field": {"name": "skip_me", "type": "u32"},
                "compare": "skip",
            },
        ],
    }
    (tmp_path / "Foo.json").write_text(json.dumps(spec))

    tester = StructRoundTripTester(spec_root=str(tmp_path))
    compare_fields = tester._collect_compare_fields("Foo")
    assert compare_fields == [
        {"path": "value", "mode": "by_value"},
        {"path": "bytes.len", "mode": "by_value"},
    ]

    compare_block = tester._render_compare_block("Foo", "Foo", compare_fields)
    assert "let actual_r: &'static mut Foo" in compare_block
    assert 'assert_eq!(&(expected_r.value), &(actual_r.value),' in compare_block
    assert 'assert_eq!((expected_r.bytes).len(), (actual_r.bytes).len()' in compare_block


class _DummyLLM:
    def __init__(self, response: str):
        self.response = response
        self.prompt: str | None = None

    def query(self, prompt, model=None, override_system_message=None):
        self.prompt = prompt
        return self.response


def test_full_roundtrip_flow(monkeypatch, tmp_path: Path):
    spec = {
        "struct_name": "Foo",
        "fields": [
            {
                "u_field": {
                    "name": "name",
                    "type": "*mut ::std::os::raw::c_char",
                    "shape": {"ptr": {"kind": "cstring", "null": "nullable"}},
                },
                "i_field": {"name": "name", "type": "Option<String>"},
                "compare": "by_value",
            },
            {
                "u_field": {
                    "name": "values",
                    "type": "*mut u8",
                    "shape": {"ptr": {"kind": "slice", "len_from": "values_len"}},
                },
                "i_field": {"name": "values", "type": "Vec<u8>"},
                "compare": "by_slice",
            },
            {
                "u_field": {"name": "values_len", "type": "usize", "shape": "scalar"},
                "i_field": {"name": "values.len", "type": "usize"},
                "compare": "by_value",
            },
            {
                "u_field": {"name": "flag", "type": "bool", "shape": "scalar"},
                "i_field": {"name": "flag", "type": "bool"},
                "compare": "by_value",
            },
        ],
    }
    spec_path = tmp_path / "Foo.json"
    spec_path.write_text(json.dumps(spec))

    combined_code = """
use std::ffi::{CStr, CString};
use std::os::raw::c_char;

pub struct Foo {
    pub name: Option<String>,
    pub values: Vec<u8>,
    pub flag: bool,
}

#[repr(C)]
pub struct CFoo {
    pub name: *mut c_char,
    pub values: *mut u8,
    pub values_len: usize,
    pub flag: bool,
}

pub unsafe fn Foo_to_CFoo_mut(input: &mut Foo) -> *mut CFoo {
    let name_ptr = match input.name.clone() {
        Some(s) => CString::new(s).unwrap().into_raw(),
        None => std::ptr::null_mut(),
    };
    let mut values_box = input.values.clone().into_boxed_slice();
    let values_len = values_box.len();
    let values_ptr = if values_len == 0 {
        std::ptr::null_mut()
    } else {
        let ptr = values_box.as_mut_ptr();
        std::mem::forget(values_box);
        ptr
    };
    let c = CFoo {
        name: name_ptr,
        values: values_ptr,
        values_len,
        flag: input.flag,
    };
    Box::into_raw(Box::new(c))
}

pub unsafe fn CFoo_to_Foo_mut(input: *mut CFoo) -> &'static mut Foo {
    assert!(!input.is_null());
    let c = &mut *input;
    let name = if c.name.is_null() {
        None
    } else {
        Some(CStr::from_ptr(c.name).to_string_lossy().into_owned())
    };
    let values = if c.values.is_null() || c.values_len == 0 {
        Vec::new()
    } else {
        Vec::from_raw_parts(c.values, c.values_len, c.values_len)
    };
    c.values = std::ptr::null_mut();
    c.values_len = 0;
    let foo = Foo {
        name,
        values,
        flag: c.flag,
    };
    Box::leak(Box::new(foo))
}
"""

    llm_fill = """
let mut name = std::ffi::CString::new("Alice").unwrap();
c0.name = name.into_raw();
let mut vec_data = vec![1u8, 2, 3, 4];
c0.values_len = vec_data.len();
c0.values = vec_data.as_mut_ptr();
core::mem::forget(vec_data);
c0.flag = true;
"""

    llm = _DummyLLM("""----FILL----\n""" + llm_fill.strip() + "\n----END FILL----")

    tester = StructRoundTripTester(llm=llm, spec_root=str(tmp_path))

    generated: dict[str, str] = {}

    original_materialize = StructRoundTripTester._materialize_lib_rs

    def capture_materialize(self, code, struct_name, idiomatic_name, fill_blocks, compare_fields):
        lib = original_materialize(
            self, code, struct_name, idiomatic_name, fill_blocks, compare_fields
        )
        generated["lib"] = lib
        return lib

    monkeypatch.setattr(StructRoundTripTester, "_materialize_lib_rs", capture_materialize)

    ok, snippet = tester.run_minimal(combined_code, "Foo")

    assert ok
    assert "running 1 test" in snippet
    assert "test result: ok" in snippet
    assert "rt_generated_0" in generated["lib"]
    assert "let expected_ptr: *mut CFoo = &mut expected_c as *mut CFoo;" in generated["lib"]
    assert "assert_eq!(&(expected_r.name), &(actual_r.name)" in generated["lib"]
    assert "assert_eq!((expected_r.values).len(), (actual_r.values).len()" in generated["lib"]
    assert "assert_eq!(&(expected_r.flag), &(actual_r.flag)" in generated["lib"]
    assert "Some(CStr::from_ptr" in llm.prompt

def test_full_roundtrip_detects_mismatch_complex(monkeypatch, tmp_path: Path):
    spec = {
        "struct_name": "Foo",
        "fields": [
            {
                "u_field": {
                    "name": "name",
                    "type": "*mut ::std::os::raw::c_char",
                    "shape": {"ptr": {"kind": "cstring", "null": "nullable"}},
                },
                "i_field": {"name": "name", "type": "Option<String>"},
                "compare": "by_value",
            },
            {
                "u_field": {
                    "name": "values",
                    "type": "*mut u8",
                    "shape": {"ptr": {"kind": "slice", "len_from": "values_len"}},
                },
                "i_field": {"name": "values", "type": "Vec<u8>"},
                "compare": "by_slice",
            },
            {
                "u_field": {"name": "values_len", "type": "usize", "shape": "scalar"},
                "i_field": {"name": "values.len", "type": "usize"},
                "compare": "by_value",
            },
            {
                "u_field": {"name": "flag", "type": "bool", "shape": "scalar"},
                "i_field": {"name": "flag", "type": "bool"},
                "compare": "by_value",
            },
        ],
    }
    spec_path = tmp_path / "Foo.json"
    spec_path.write_text(json.dumps(spec))

    combined_code = """
use std::ffi::{CStr, CString};
use std::os::raw::c_char;

pub struct Foo {
    pub name: Option<String>,
    pub values: Vec<u8>,
    pub flag: bool,
}

#[repr(C)]
pub struct CFoo {
    pub name: *mut c_char,
    pub values: *mut u8,
    pub values_len: usize,
    pub flag: bool,
}

pub unsafe fn Foo_to_CFoo_mut(input: &mut Foo) -> *mut CFoo {
    let name_ptr = match input.name.clone() {
        Some(s) => CString::new(s).unwrap().into_raw(),
        None => std::ptr::null_mut(),
    };
    let mut values_box = input.values.clone().into_boxed_slice();
    let values_len = values_box.len();
    let values_ptr = if values_len == 0 {
        std::ptr::null_mut()
    } else {
        let ptr = values_box.as_mut_ptr();
        std::mem::forget(values_box);
        ptr
    };
    let c = CFoo {
        name: name_ptr,
        values: values_ptr,
        values_len,
        flag: input.flag,
    };
    Box::into_raw(Box::new(c))
}

pub unsafe fn CFoo_to_Foo_mut(input: *mut CFoo) -> &'static mut Foo {
    assert!(!input.is_null());
    let c = &mut *input;
    let name = if c.name.is_null() {
        None
    } else {
        Some(CStr::from_ptr(c.name).to_string_lossy().into_owned())
    };
    let values = if c.values.is_null() || c.values_len == 0 {
        Vec::new()
    } else {
        Vec::from_raw_parts(c.values, c.values_len, c.values_len)
    };
    c.values = std::ptr::null_mut();
    c.values_len = 0;
    let foo = Foo {
        name,
        values,
        flag: !c.flag,
    };
    Box::leak(Box::new(foo))
}
"""

    llm_fill = """
let mut name = std::ffi::CString::new("Alice").unwrap();
c0.name = name.into_raw();
let mut vec_data = vec![1u8, 2, 3, 4];
c0.values_len = vec_data.len();
c0.values = vec_data.as_mut_ptr();
core::mem::forget(vec_data);
c0.flag = true;
"""

    llm = _DummyLLM("""----FILL----\n""" + llm_fill.strip() + "\n----END FILL----")
    tester = StructRoundTripTester(llm=llm, spec_root=str(tmp_path))

    captured: dict[str, str] = {}

    original_materialize = StructRoundTripTester._materialize_lib_rs

    def capture_materialize(self, code, struct_name, idiomatic_name, fill_blocks, compare_fields):
        lib = original_materialize(
            self, code, struct_name, idiomatic_name, fill_blocks, compare_fields
        )
        captured["lib"] = lib
        return lib

    monkeypatch.setattr(StructRoundTripTester, "_materialize_lib_rs", capture_materialize)

    ok, snippet = tester.run_minimal(combined_code, "Foo", allow_fallback=False)

    assert not ok
    assert "field flag mismatch" in snippet
    assert "assert_eq!(&(expected_r.flag), &(actual_r.flag)" in captured.get("lib", "")

def test_full_roundtrip_detects_mismatch_minimal(monkeypatch, tmp_path: Path):
    spec = {
        "struct_name": "Foo",
        "fields": [
            {
                "u_field": {"name": "flag", "type": "bool", "shape": "scalar"},
                "i_field": {"name": "flag", "type": "bool"},
                "compare": "by_value",
            }
        ],
    }
    spec_path = tmp_path / "Foo.json"
    spec_path.write_text(json.dumps(spec))

    combined_code = """
#[repr(C)]
pub struct CFoo { pub flag: bool }
pub struct Foo { pub flag: bool }
pub unsafe fn Foo_to_CFoo_mut(input: &mut Foo) -> *mut CFoo {
    let c = CFoo { flag: input.flag };
    Box::into_raw(Box::new(c))
}
pub unsafe fn CFoo_to_Foo_mut(input: *mut CFoo) -> &'static mut Foo {
    assert!(!input.is_null());
    let c = &mut *input;
    let foo = Foo { flag: !c.flag };
    Box::leak(Box::new(foo))
}
"""

    llm = _DummyLLM("""----FILL----\n""" + "c0.flag = true;" + "\n----END FILL----")
    tester = StructRoundTripTester(llm=llm, spec_root=str(tmp_path))

    captured: dict[str, str] = {}

    original_materialize = StructRoundTripTester._materialize_lib_rs

    def capture_materialize(self, code, struct_name, idiomatic_name, fill_blocks, compare_fields):
        lib = original_materialize(
            self, code, struct_name, idiomatic_name, fill_blocks, compare_fields
        )
        captured["lib"] = lib
        return lib

    monkeypatch.setattr(StructRoundTripTester, "_materialize_lib_rs", capture_materialize)

    ok, snippet = tester.run_minimal(combined_code, "Foo", allow_fallback=False)

    assert not ok
    assert "field flag mismatch" in snippet
    assert "assert_eq!(&(expected_r.flag), &(actual_r.flag)" in captured.get("lib", "")
