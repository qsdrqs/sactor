from textwrap import dedent

from sactor import rust_ast_parser


def test_unidiomatic_function_cleanup_injects_libc_stdint():
    src = dedent(
        """
        type uint16_t = u16;
        unsafe fn foo(x: uint16_t) -> uint16_t {
            x
        }
        """
    )

    cleaned = rust_ast_parser.unidiomatic_function_cleanup(src)

    assert "type uint16_t" not in cleaned
    assert "use libc::uint16_t;" in cleaned
    assert cleaned.strip().startswith("use libc::uint16_t;\npub unsafe fn foo")


def test_unidiomatic_types_cleanup_adds_missing_stdint_use():
    src = dedent(
        """
        #[repr(C)]
        pub struct Foo {
            pub len: uint32_t,
        }
        """
    )

    cleaned = rust_ast_parser.unidiomatic_types_cleanup(src)

    assert cleaned.startswith("use libc::uint32_t;\n#[repr(C)]")
    assert "uint32_t" in cleaned


def test_existing_use_extended_with_stdint():
    src = dedent(
        """
        use libc::{c_int};
        type uint32_t = u32;
        unsafe fn foo(x: uint32_t) -> c_int {
            x as c_int
        }
        """
    )

    cleaned = rust_ast_parser.unidiomatic_function_cleanup(src)

    assert "type uint32_t" not in cleaned
    assert "use libc::{c_int, uint32_t};" in cleaned
    assert "pub unsafe fn foo" in cleaned


def test_dedup_items_removes_duplicate_aliases():
    code = dedent(
        """
        use libc::uint32_t;
        use libc::uint32_t;
        pub type Foo = u32;
        pub type Foo = u32;
        pub struct S;
        pub struct S;
        """
    )

    deduped = rust_ast_parser.dedup_items(code)
    assert deduped.count("use libc::uint32_t;") == 1
    assert deduped.count("pub type Foo = u32;") == 1
    assert deduped.count("pub struct S;") == 1


def test_strip_to_struct_items():
    code = dedent(
        """
        use libc::uint32_t;
        pub type size_t = libc::c_ulong;

        #[repr(C)]
        pub struct Foo {
            pub len: uint32_t,
        }

        #[repr(C)]
        pub union Bar {
            pub ptr: *mut Foo,
        }
        """
    )

    stripped = rust_ast_parser.strip_to_struct_items(code)
    assert "use libc" not in stripped
    assert "pub type size_t" not in stripped
    assert "pub struct Foo" in stripped
    assert "pub union Bar" in stripped
