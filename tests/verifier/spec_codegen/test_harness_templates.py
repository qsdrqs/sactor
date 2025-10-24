from __future__ import annotations

import pytest

from sactor.verifier.spec.harness_templates import (
    EnumHarnessContext,
    FunctionHarnessContext,
    StructHarnessContext,
)


def test_struct_harness_context_create_normalizes_sequences() -> None:
    context = StructHarnessContext.create(
        uses=["use std::ffi;"],
        struct_name="Course",
        idiomatic_type="Course",
        c_struct_bind="c_struct",
        idiom_struct_bind="idiom_struct",
        pointer_asserts=["    assert!(!c_struct.ptr.is_null());"],
        init_lines=["            field: value,"],
        back_lines=["    let _tmp = 1;"],
        c_struct_init_lines=["        field: _tmp,"],
    )

    template_args = context.as_template_args()
    assert template_args["uses"] == ("use std::ffi;",)
    assert template_args["pointer_asserts"] == ("    assert!(!c_struct.ptr.is_null());",)
    assert template_args["init_lines"] == ("            field: value,",)
    assert template_args["back_lines"] == ("    let _tmp = 1;",)
    assert template_args["c_struct_init_lines"] == ("        field: _tmp,",)


def test_struct_harness_context_allows_empty_strings() -> None:
    context = StructHarnessContext.create(
        uses=[],
        struct_name="",
        idiomatic_type="",
        c_struct_bind="c_struct",
        idiom_struct_bind="idiom_struct",
        pointer_asserts=[],
        init_lines=[],
        back_lines=[],
        c_struct_init_lines=[],
    )
    args = context.as_template_args()
    assert args["struct_name"] == ""
    assert args["idiomatic_type"] == ""


def test_enum_harness_context_normalizes_variants() -> None:
    context = EnumHarnessContext.create(
        uses=["use core::ptr;"],
        struct_name="Student",
        idiom_type="Student",
        tag_field="tag",
        to_rust_arms=[{"match_value": "0", "expression": "Student::Undergrad"}],
        variants=[
            {
                "pattern": "Student::Undergrad",
                "temps": ["    let _tag = 0;"],
                "struct_fields": ["                tag: _tag,"],
            }
        ],
    )

    args = context.as_template_args()
    variant = args["variants"][0]
    assert variant["temps"] == ("    let _tag = 0;",)
    assert variant["struct_fields"] == ("                tag: _tag,",)


def test_enum_harness_context_accepts_non_ascii() -> None:
    accent = "\u00E9"  # keep file ASCII-only via escape
    context = EnumHarnessContext.create(
        uses=[],
        struct_name="Student",
        idiom_type="Student",
        tag_field="tag",
        to_rust_arms=[{"match_value": accent, "expression": "Étudiant::Autre"}],
        variants=[],
    )
    args = context.as_template_args()
    assert args["to_rust_arms"][0]["match_value"] == accent


def test_function_harness_context_allows_empty_signature() -> None:
    context = FunctionHarnessContext.create(
        signature="",
        call_line="    do_call();",
        pre_lines=[],
        ret_lines=[],
        post_lines=[],
        return_line=None,
    )
    assert context.signature == ""


def test_function_harness_context_normalizes_body_lines() -> None:
    context = FunctionHarnessContext.create(
        signature="fn sample() -> u32",
        call_line="    let value = sample_impl();",
        pre_lines=["    // pre"],
        ret_lines=["    let intermediary = 1;"],
        post_lines=["    // post"],
        return_line=["    return value;"],
    )
    assert context.pre_lines == ("    // pre",)
    assert context.ret_lines == ("    let intermediary = 1;",)
    assert context.post_lines == ("    // post",)
    assert context.return_line == ("    return value;",)
